"""
Structured JSON/YAML -> Ontology Extractor (Phase 1 MVP)

Deterministic field -> triple mapping for JSON/YAML documents, per
docs/design-structured-json-yaml-ontology.md SS3 (mapping rules), SS4 (identity),
SS5 (typing) and SS8 (search verbalization).

Phase 1 scope ONLY:
    - No ontology alignment (SS6/SS7 - Phase 2/3).
    - No is_promoted checks.
    - No preview-review UI.
    - Just deterministic extraction + rdf:type + search chunks, for a fresh KB.

Output shape mirrors app.core.pipeline.IngestPipeline.process() so that the
existing downstream persistence code in app/api/ingest.py (Milvus insert_chunks +
Fuseki/Neo4j insert_triples) can be reused unmodified:
    {"nodes": [...], "embeddings": [...], "triples": [...],
     "node_count": int, "triple_count": int, "stats": [...]}

Triple dict shape matches app.core.fuseki_connector / neo4j_connector exactly:
    {"subject", "predicate", "object", "source_node_id", "confidence",
     "subject_type", "object_type"}
Note: "subject"/"predicate"/"object" here are the connectors' expected *local*
identity/name strings (NOT full URIs) -- both connectors sanitize + prepend the
`http://rag.local/inst/` (entity) / `http://rag.local/rel/` (relation) /
`http://rag.local/class/` (subject_type/object_type) namespaces themselves.
"""
import json
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from llama_index.core.schema import TextNode

from app.utils.file_utils import read_text_file


# ----------------------------------------------------------------------------
# Defaults (SS4 / SS5 heuristics) -- overridable per-instance for future
# KB/request-level mapping config (not wired in Phase 1, per design SS4 note).
# ----------------------------------------------------------------------------
DEFAULT_ID_KEYS = {"id", "@id", "uuid", "_id", "key"}
DEFAULT_TYPE_KEYS = ["type", "@type", "kind", "class"]
DEFAULT_LABEL_KEYS = ["name", "title", "label"]

MAX_DEPTH = 40  # Guard against pathological/circular nesting (design SS14).


def _sanitize_uri(text: str) -> str:
    """Sanitize text into a URI-safe local name.

    Mirrors fuseki_connector.FusekiConnector._sanitize_uri exactly so that
    identity/reference strings produced here sanitize identically to how the
    connectors will sanitize them when building final RDF/Cypher identifiers.
    """
    clean = re.sub(r'[^a-zA-Z0-9_가-힣Ѐ-ӿ]+', '_', str(text).strip())
    return clean or "unknown"


def _stringify_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _singularize(word: str) -> str:
    """Simple heuristic singularization for container-key -> class hints
    (design SS5.2 / task spec): strip trailing 'ies'->'y', else strip trailing
    's', else keep as-is. NOT a full English singularizer by design (Phase 1
    keeps this deterministic and dependency-free).
    """
    if not word:
        return word
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("s") and len(word) > 1:
        return word[:-1]
    return word


def _class_from_container_key(key: str) -> str:
    """'participants' -> 'Participant', 'games' -> 'Game'."""
    singular = _singularize(key)
    if not singular:
        return "Entity"
    return singular[0].upper() + singular[1:]


def _sanitize_class_name(value: str) -> str:
    clean = _sanitize_uri(value)
    if not clean:
        return "Entity"
    return clean[0].upper() + clean[1:]


class StructuredExtractor:
    """Deterministic JSON/YAML -> triples + search-chunk extractor (Phase 1)."""

    def __init__(
        self,
        id_keys: Optional[Set[str]] = None,
        type_keys: Optional[List[str]] = None,
        label_keys: Optional[List[str]] = None,
        max_depth: int = MAX_DEPTH,
    ):
        self.id_keys = id_keys or DEFAULT_ID_KEYS
        self.type_keys = type_keys or DEFAULT_TYPE_KEYS
        self.label_keys = label_keys or DEFAULT_LABEL_KEYS
        self.max_depth = max_depth

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------
    async def extract(
        self,
        file_path: str,
        kb_id: str,
        doc_id: str,
        embed_model: Any,
    ) -> Dict[str, Any]:
        """Parse a JSON/YAML file and produce the pipeline-compatible result dict."""
        start = time.time()
        stats: List[Dict[str, Any]] = []

        # --- Step 0: Read + Parse -----------------------------------------
        t0 = time.time()
        raw_text = await read_text_file(file_path)
        if not raw_text:
            raise ValueError(f"Could not read content from {file_path}")

        data = self._parse(file_path, raw_text)
        stats.append({"step": "Step 0: Parse", "duration": round(time.time() - t0, 2)})

        # --- Per-document mutable state -------------------------------------
        self._triples: List[Dict[str, Any]] = []
        self._entities: Dict[str, Dict[str, Any]] = {}  # identity -> {class,label,fields}
        self._entity_order: List[str] = []
        self._identity_cache: Dict[int, str] = {}  # id(python obj) -> identity (cycle guard)
        self._anon_counter = 0
        self.id_index: Set[str] = set()

        # --- Step 1: id index (1-pass, for reference detection, design SS4.2) --
        t1 = time.time()
        self._collect_ids(data)
        stats.append({
            "step": f"Step 1: ID Index ({len(self.id_index)} ids)",
            "duration": round(time.time() - t1, 2),
        })

        # --- Step 2: recursive mapping ---------------------------------------
        t2 = time.time()
        for idx, (record, container_key, is_collection) in enumerate(self._top_level_records(data)):
            self._process_object(
                record,
                path=f"root_{idx}",
                container_key=container_key,
                container_is_collection=is_collection,
                depth=0,
                visited=set(),
            )
        stats.append({
            "step": f"Step 2: Mapping ({len(self._entities)} entities, {len(self._triples)} triples)",
            "duration": round(time.time() - t2, 2),
        })

        # --- Step 3: verbalize (SS8) + embed ----------------------------------
        t3 = time.time()
        nodes: List[TextNode] = []
        embeddings: List[List[float]] = []
        for identity in self._entity_order:
            info = self._entities[identity]
            text = self._verbalize(identity, info)
            chunk_id = self._chunk_id(doc_id, identity)

            node = TextNode(
                text=text,
                id_=chunk_id,
                metadata={
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                    "source": "structured",
                    "entity_identity": identity,
                    "entity_class": info.get("class"),
                },
            )
            embedding = await embed_model.aget_text_embedding(text)
            nodes.append(node)
            embeddings.append(embedding)

            # Link this entity's own triples (where it is the subject) to its chunk,
            # so graph search can attach this chunk as evidence (design SS8).
            for t in self._triples:
                if t.get("subject") == identity and not t.get("source_node_id"):
                    t["source_node_id"] = chunk_id
        stats.append({
            "step": f"Step 3: Verbalize + Embed ({len(nodes)} chunks)",
            "duration": round(time.time() - t3, 2),
        })

        stats.append({"step": "Total Execution Time", "duration": round(time.time() - start, 2)})

        return {
            "nodes": nodes,
            "embeddings": embeddings,
            "triples": self._triples,
            "node_count": len(nodes),
            "triple_count": len(self._triples),
            "stats": stats,
        }

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse(self, file_path: str, raw_text: str) -> Any:
        lower = file_path.lower()
        if lower.endswith(".json"):
            return json.loads(raw_text)
        if lower.endswith(".yaml") or lower.endswith(".yml"):
            return yaml.safe_load(raw_text)
        # Fallback (should not normally hit -- caller only routes .json/.yaml/.yml here)
        try:
            return json.loads(raw_text)
        except (ValueError, TypeError):
            return yaml.safe_load(raw_text)

    def _top_level_records(self, data: Any) -> List[Tuple[Dict[str, Any], Optional[str], bool]]:
        """Determine the set of top-level entities to map (design SS3.3).

        - Top-level list -> each dict element is its own top-level entity.
        - Top-level dict that itself "looks like" a record (has an id/type/label
          key) -> treated as ONE entity.
        - Top-level dict that looks like a pure envelope/container (e.g.
          {"participants": [...], "games": [...]} from the design appendix) ->
          NOT turned into an entity itself; each collection's items become
          top-level entities instead (container key used as class hint, SS3.3).
        """
        # Each record carries (obj, container_key, container_is_collection):
        # container_is_collection distinguishes a plural array container (key is
        # singularized for the class hint) from a single nested object (key kept
        # as-is), so `"address": {...}` -> class "Address" not "Addres".
        records: List[Tuple[Dict[str, Any], Optional[str], bool]] = []

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    records.append((item, None, False))
            return records

        if not isinstance(data, dict):
            return records  # scalar top-level document: nothing to map

        looks_like_entity = any(
            k in data for k in (self.id_keys | set(self.type_keys) | set(self.label_keys))
        )
        if looks_like_entity:
            records.append((data, None, False))
            return records

        # Envelope: flatten each key's collection/nested object into top-level records
        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        records.append((item, key, True))
            elif isinstance(value, dict):
                records.append((value, key, False))
            # scalar stray top-level values have no owning entity in Phase 1 (skipped)

        return records

    # ------------------------------------------------------------------
    # Pass 1: id index (design SS4.2 -- reference vs literal detection)
    # ------------------------------------------------------------------
    def _collect_ids(self, node: Any, depth: int = 0, visited: Optional[Set[int]] = None) -> None:
        if depth > self.max_depth:
            return
        if visited is None:
            visited = set()

        if isinstance(node, dict):
            node_ref = id(node)
            if node_ref in visited:
                return
            visited = visited | {node_ref}
            for k, v in node.items():
                if k in self.id_keys and isinstance(v, (str, int, float)) and not isinstance(v, bool):
                    self.id_index.add(str(v))
                self._collect_ids(v, depth + 1, visited)
        elif isinstance(node, list):
            node_ref = id(node)
            if node_ref in visited:
                return
            visited = visited | {node_ref}
            for item in node:
                self._collect_ids(item, depth + 1, visited)

    # ------------------------------------------------------------------
    # Pass 2: recursive mapping (design SS3)
    # ------------------------------------------------------------------
    def _process_object(
        self,
        obj: Dict[str, Any],
        path: str,
        container_key: Optional[str],
        container_is_collection: bool,
        depth: int,
        visited: Set[int],
    ) -> str:
        if depth > self.max_depth:
            return self._anon_identity(path)

        obj_ref = id(obj)
        if obj_ref in visited:
            # Cycle guard (e.g. YAML anchors/aliases forming a real Python-object cycle).
            return self._identity_cache.get(obj_ref, self._anon_identity(path))
        visited = visited | {obj_ref}

        identity = self._determine_identity(obj, path)
        entity_class = self._determine_class(obj, container_key, container_is_collection)
        self._identity_cache[obj_ref] = identity

        entity = self._entities.get(identity)
        if entity is None:
            entity = {"class": entity_class, "label": None, "fields": []}
            self._entities[identity] = entity
            self._entity_order.append(identity)
        elif entity.get("class") in (None, "Entity") and entity_class != "Entity":
            entity["class"] = entity_class  # upgrade a fallback class if a better hint shows up later

        has_own_triple = False

        for key, value in obj.items():
            if key in self.id_keys:
                continue  # already captured via identity, not re-emitted (avoid noise)
            if key in self.type_keys:
                continue  # already captured via class assignment

            if value is None:
                continue

            is_label_field = (
                key in self.label_keys
                and isinstance(value, str)
                and value.strip()
                and entity.get("label") is None
            )
            if is_label_field:
                entity["label"] = value
                # Approximates "add rdfs:label" (design SS4.3): the connectors
                # only auto-derive rdfs:label from the literal subject/object
                # text they are given, so we emit an explicit "label" edge to
                # carry the human-readable value into the graph store without
                # touching connector code.
                self._emit_triple(identity, "label", value, entity_class, None)
                has_own_triple = True
                continue

            if isinstance(value, dict):
                child_identity = self._process_object(
                    value, path=f"{path}.{key}", container_key=key,
                    container_is_collection=False, depth=depth + 1, visited=visited
                )
                child_class = self._entities.get(child_identity, {}).get("class")
                self._emit_triple(identity, key, child_identity, entity_class, child_class)
                entity["fields"].append((key, self._entity_display(child_identity)))
                has_own_triple = True

            elif isinstance(value, list):
                display_values = []
                emitted_any = False
                for i, item in enumerate(value):
                    if item is None:
                        continue
                    if isinstance(item, dict):
                        child_identity = self._process_object(
                            item, path=f"{path}.{key}[{i}]", container_key=key,
                            container_is_collection=True, depth=depth + 1, visited=visited
                        )
                        child_class = self._entities.get(child_identity, {}).get("class")
                        self._emit_triple(identity, key, child_identity, entity_class, child_class)
                        display_values.append(self._entity_display(child_identity))
                        emitted_any = True
                    elif isinstance(item, list):
                        continue  # doubly-nested arrays unsupported in Phase 1 (rare)
                    else:
                        self._emit_scalar_or_ref(identity, key, item, entity_class)
                        display_values.append(_stringify_scalar(item))
                        emitted_any = True
                if emitted_any:
                    entity["fields"].append((key, "; ".join(display_values)))
                    has_own_triple = True

            else:
                self._emit_scalar_or_ref(identity, key, value, entity_class)
                entity["fields"].append((key, _stringify_scalar(value)))
                has_own_triple = True

        if not has_own_triple:
            # Safety net: guarantee at least one triple carries subject_type so
            # rdf:type still gets emitted for entities with no other outgoing
            # edges at all (e.g. a bare {"id": "x1"}).
            self._emit_triple(identity, "_type", entity_class, entity_class, None)

        return identity

    def _emit_scalar_or_ref(self, identity: str, key: str, value: Any, entity_class: str) -> None:
        str_value = _stringify_scalar(value)
        if isinstance(value, str) and str_value in self.id_index:
            # String value matches a known id elsewhere in the document -> treat
            # as a reference (object property), not a literal (design SS4.2).
            ref_identity = _sanitize_uri(str_value)
            self._emit_triple(identity, key, ref_identity, entity_class, None)
        else:
            self._emit_triple(identity, key, str_value, entity_class, None)

    def _emit_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        subject_type: Optional[str],
        object_type: Optional[str],
    ) -> None:
        self._triples.append({
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "source_node_id": None,  # filled in during verbalize pass (Step 3)
            "confidence": 1.0,  # deterministic mapping, not an LLM guess
            "subject_type": subject_type,
            "object_type": object_type,
        })

    def _entity_display(self, identity: str) -> str:
        info = self._entities.get(identity)
        if info and info.get("label"):
            return info["label"]
        return identity

    # ------------------------------------------------------------------
    # Identity (design SS4) / Type (design SS5)
    # ------------------------------------------------------------------
    def _determine_identity(self, obj: Dict[str, Any], path: str) -> str:
        for id_key in self.id_keys:
            if id_key in obj and obj[id_key] not in (None, ""):
                return _sanitize_uri(_stringify_scalar(obj[id_key]))
        for label_key in self.label_keys:
            v = obj.get(label_key)
            if isinstance(v, str) and v.strip():
                return _sanitize_uri(v)
        return self._anon_identity(path)

    def _anon_identity(self, path: str) -> str:
        self._anon_counter += 1
        return _sanitize_uri(f"{path}_{self._anon_counter}")

    def _determine_class(
        self, obj: Dict[str, Any], container_key: Optional[str], container_is_collection: bool
    ) -> str:
        for type_key in self.type_keys:
            v = obj.get(type_key)
            if isinstance(v, str) and v.strip():
                return _sanitize_class_name(v)
        if container_key:
            # Array container -> plural key, singularize ('participants'->'Participant').
            # Single nested object -> keep key as-is ('address'->'Address').
            if container_is_collection:
                return _class_from_container_key(container_key)
            return _sanitize_class_name(container_key)
        return "Entity"

    # ------------------------------------------------------------------
    # Verbalization (design SS8)
    # ------------------------------------------------------------------
    def _verbalize(self, identity: str, info: Dict[str, Any]) -> str:
        label = info.get("label") or identity
        class_name = info.get("class") or "Entity"
        fields = info.get("fields", [])
        field_text = ", ".join(f"{k}={v}" for k, v in fields)
        if field_text:
            return f"{label} ({class_name}): {field_text}"
        return f"{label} ({class_name})"

    def _chunk_id(self, doc_id: str, identity: str) -> str:
        raw = f"{doc_id}::struct::{identity}"
        if len(raw) <= 120:
            return raw
        import hashlib
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        return f"{doc_id}::struct::{digest}"


# Convenience singleton (mirrors milvus_connector / fuseki_connector style)
structured_extractor = StructuredExtractor()
