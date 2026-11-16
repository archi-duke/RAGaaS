"""KB 스키마 매핑 규칙 서비스 (docs/design-schema-mismatch.md §5).

- 검색용 규칙 로드 (동치·별칭)
- 인제스트 요청에 실을 규칙·어휘
- 인제스트 완료 후 제안 생성 (감지기 재실행)
- 제안 수락(규칙 생성 + 재정규화) / 거절(ignore 규칙)
- 재정규화 = 같은 doc_id 재인제스트 (replace_existing)
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.retrieval.entity_linking import _compact

logger = logging.getLogger(__name__)

RENORMALIZE_CONCURRENCY = 2


def _segs(path: Optional[str]) -> List[str]:
    return [s for s in str(path or "").split(".") if s]


# ---------------------------------------------------------------------------
# 규칙 로드
# ---------------------------------------------------------------------------

async def active_rules(kb_id: str):
    from app.models.schema_mapping import SchemaMappingRule
    return await SchemaMappingRule.find(
        SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.status == "active"
    ).to_list()


async def load_rules_for_retrieval(kb_id: str) -> Dict[str, Any]:
    """검색용: key 규칙 쌍(동치 rule 근거), ignore 쌍, 값 매핑, 별칭(원래 키 → 표준 키)."""
    out: Dict[str, Any] = {"key_pairs": [], "ignore_pairs": [], "value_map": {}, "aliases": {}}
    for r in await active_rules(kb_id):
        if r.rule_type == "key" and r.source_path and r.target_path:
            out["key_pairs"].append((r.source_path, r.target_path))
            src_leaf, tgt_leaf = _segs(r.source_path)[-1], _segs(r.target_path)[-1]
            out["aliases"][_compact(src_leaf)] = tgt_leaf
        elif r.rule_type == "value" and r.source_value and r.target_value:
            out["value_map"][_compact(r.source_value)] = r.target_value
        elif r.rule_type == "ignore" and r.pair and len(r.pair) == 2:
            out["ignore_pairs"].append((r.pair[0], r.pair[1]))
    return out


async def rules_for_ingest(kb_id: str, include_graph_rules: bool = False) -> List[Dict[str, Any]]:
    """인제스트·리플레이용 규칙. include_graph_rules=True 면 entity/class 규칙도 (텍스트 리플레이)."""
    kinds = ("key", "value", "entity", "class") if include_graph_rules else ("key", "value")
    return [
        {
            "id": str(r.id), "rule_type": r.rule_type, "source_path": r.source_path,
            "target_path": r.target_path, "source_value": r.source_value,
            "target_value": r.target_value, "scope_paths": r.scope_paths, "status": r.status,
        }
        for r in await active_rules(kb_id) if r.rule_type in kinds
    ]


def _is_structured_name(filename: str) -> bool:
    return str(filename or "").lower().rsplit(".", 1)[-1] in ("json", "yaml", "yml")


async def replay_documents(kb_id: str, doc_ids: List[str]) -> Dict[str, Any]:
    """텍스트 문서: 저장된 추출 트리플에 현재 규칙을 적용해 그래프만 교체 (LLM 비용 0, 멱등)."""
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase
    from app.services.ingestion.ingest_client import ingest_client
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend

    kb = await KnowledgeBase.get(kb_id)
    rules = await rules_for_ingest(kb_id, include_graph_rules=True)
    results = []
    for did in doc_ids:
        try:
            r = await ingest_client.replay_triples(
                kb_id, did, "fuseki" if kb.graph_backend == "ontology" else "neo4j", rules or None)
            results.append(r)
            doc = await Document.get(did)
            if doc:
                doc.schema_rules_version = kb.schema_rules_version
                await doc.save()
        except Exception as e:
            results.append({"doc_id": did, "error": str(e)[:200]})
    FusekiBackend.invalidate_class_catalog(kb_id)
    return {"replayed": results}


async def build_schema_vocab(kb_id: str) -> Dict[str, Any]:
    """자동 표기 정규화용 KB 어휘: 표준 경로 키 + enum 경로의 값 (데이터 기반 카탈로그)."""
    try:
        from app.services.retrieval.graph_backends.fuseki import FusekiBackend
        kinds, catalogs = await FusekiBackend()._class_catalog(kb_id, lambda _m: None, {})
    except Exception as e:
        logger.warning(f"[SchemaVocab] catalog unavailable for {kb_id}: {e}")
        return {}
    paths: List[str] = []
    enum_values: Dict[str, List[str]] = {}
    for k in kinds:
        small_kind = len(k["members"]) < 2
        for p in catalogs.get(k["name"], []):
            # 표기 정규화 기준은 다수 표기 — 멤버 2개 이상이 쓰는 경로·값만 어휘로
            if small_kind or len(p.get("member_ids") or ()) >= 2:
                paths.append(p["key"])
                if p.get("type") == "enum":
                    vals = [v["label"] for v in p.get("values") or [] if small_kind or v.get("members", 0) >= 2]
                    if vals:
                        enum_values[p["key"]] = vals
    return {"paths": sorted(set(paths)), "enum_values": enum_values}


async def ingest_schema_payload(kb_id: str) -> Dict[str, Any]:
    """인제스트 요청에 실을 schema_rules / schema_vocab."""
    try:
        rules = await rules_for_ingest(kb_id)
        vocab = await build_schema_vocab(kb_id)
        return {"schema_rules": rules or None, "schema_vocab": vocab or None}
    except Exception as e:
        logger.warning(f"[Schema] ingest payload skipped for {kb_id}: {e}")
        return {"schema_rules": None, "schema_vocab": None}


# ---------------------------------------------------------------------------
# 인제스트 완료 후 처리
# ---------------------------------------------------------------------------

async def _graph_llm_config(kb) -> Dict[str, Any]:
    """KB 파이프라인 그래프 단계의 llm_model (LLM 동치 패스용)."""
    try:
        for st in (kb.pipeline_config or {}).get("stages") or []:
            if st.get("type") == "graph" and (st.get("params") or {}).get("llm_model"):
                return st["params"]["llm_model"]
    except Exception:
        pass
    return {}


async def record_auto_rules(kb_id: str, doc_id: str, schema_report: Optional[Dict[str, Any]]) -> int:
    """인제스트가 자동 적용한 표기 정규화를 origin=auto 규칙으로 기록."""
    from app.models.schema_mapping import SchemaMappingRule
    if not schema_report:
        return 0
    n = 0
    for a in schema_report.get("auto") or []:
        if a.get("kind") == "key":
            exists = await SchemaMappingRule.find_one(
                SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "key",
                SchemaMappingRule.source_path == a["source"], SchemaMappingRule.target_path == a["target"])
            if not exists:
                await SchemaMappingRule(kb_id=kb_id, rule_type="key", source_path=a["source"],
                                        target_path=a["target"], origin="auto").insert()
                n += 1
        elif a.get("kind") == "value":
            exists = await SchemaMappingRule.find_one(
                SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "value",
                SchemaMappingRule.source_value == a["source"], SchemaMappingRule.target_value == a["target"])
            if not exists:
                await SchemaMappingRule(kb_id=kb_id, rule_type="value", source_value=a["source"],
                                        target_value=a["target"], origin="auto").insert()
                n += 1
    return n


def _docs_with_path(kb_id: str, uris: List[str]) -> List[str]:
    """경로를 가진 문서(named graph) 목록."""
    from app.core.fuseki import fuseki_client
    from app.services.retrieval.relation_targeting import STRUCT_NODE_REGEX
    if not uris:
        return []
    if len(uris) == 1:
        pat = f"?e <{uris[0]}> ?v ."
    elif len(uris) == 2:
        pat = f'?e <{uris[0]}> ?m . FILTER(REGEX(STR(?m), "{STRUCT_NODE_REGEX}")) ?m <{uris[1]}> ?v .'
    else:
        pat = (f'?e <{uris[0]}> ?m . ?m <{uris[1]}> ?m2 . ?m2 <{uris[2]}> ?v .')
    q = f"SELECT DISTINCT ?g WHERE {{ GRAPH ?g {{ {pat} }} }} LIMIT 200"
    try:
        res = fuseki_client.query_sparql(kb_id, q)
        return [b["g"]["value"].replace("urn:doc:", "") for b in res.get("results", {}).get("bindings", [])
                if b.get("g", {}).get("value", "").startswith("urn:doc:")]
    except Exception:
        return []


def _docs_with_value(kb_id: str, value_uri: str) -> List[str]:
    from app.core.fuseki import fuseki_client
    q = f"SELECT DISTINCT ?g WHERE {{ GRAPH ?g {{ ?s ?p <{value_uri}> }} }} LIMIT 200"
    try:
        res = fuseki_client.query_sparql(kb_id, q)
        return [b["g"]["value"].replace("urn:doc:", "") for b in res.get("results", {}).get("bindings", [])
                if b.get("g", {}).get("value", "").startswith("urn:doc:")]
    except Exception:
        return []


async def detect_proposals(kb_id: str) -> Dict[str, int]:
    """감지기를 실행해 규칙·ignore 에 없는 동치를 제안으로 upsert."""
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingProposal
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    from app.services.schema_alignment.equivalence import value_canonical

    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.graph_backend != "ontology":
        return {"paths": 0, "values": 0}
    FusekiBackend.invalidate_class_catalog(kb_id)
    llm_cfg = await _graph_llm_config(kb)
    kinds, catalogs = await FusekiBackend()._class_catalog(
        kb_id, lambda m: logger.info(m), {"llm_model_config": llm_cfg} if llm_cfg else {})

    rules = await load_rules_for_retrieval(kb_id)
    ruled = {tuple(sorted(p)) for p in rules["key_pairs"]} | {tuple(sorted(p)) for p in rules["ignore_pairs"]}
    value_ruled = set(rules["value_map"].keys())
    from app.models.schema_mapping import SchemaMappingRule
    ignored_values = {tuple(sorted(r.pair)) for r in await active_rules(kb_id)
                      if r.rule_type == "ignore" and r.pair and r.pair[0].startswith("value:")}

    n_paths = n_values = 0
    affected_docs: Dict[str, int] = {}

    async def upsert(kind, source, target, basis, evidence, doc_ids):
        nonlocal n_paths, n_values
        existing = await SchemaMappingProposal.find_one(
            SchemaMappingProposal.kb_id == kb_id, SchemaMappingProposal.kind == kind,
            SchemaMappingProposal.source == source, SchemaMappingProposal.target == target)
        if existing:
            if existing.status == "pending":
                existing.doc_ids = sorted(set(existing.doc_ids) | set(doc_ids))
                existing.evidence = evidence
                existing.updated_at = datetime.utcnow()
                await existing.save()
            return
        await SchemaMappingProposal(kb_id=kb_id, kind=kind, source=source, target=target, basis=basis,
                                    evidence=evidence, doc_ids=doc_ids).insert()
        for d in doc_ids:
            affected_docs[d] = affected_docs.get(d, 0) + 1
        if kind == "key":
            n_paths += 1
        else:
            n_values += 1

    for k in kinds:
        cat = catalogs.get(k["name"], [])
        by_key = {p["key"]: p for p in cat}
        for g in k.get("equiv_groups") or []:
            target = g["rep"]
            for src in g["keys"]:
                if src == target or tuple(sorted((src, target))) in ruled:
                    continue
                basis_vals = [v for pair, v in g["basis"].items() if src in pair.split("≡")]
                basis = basis_vals[0] if basis_vals else "normalized"
                if basis == "rule":
                    continue
                sp, tp = by_key[src], by_key[target]
                evidence = {"source_members": len(sp.get("member_ids") or ()),
                            "target_members": len(tp.get("member_ids") or ()),
                            "source_examples": sp.get("examples") or [], "target_examples": tp.get("examples") or []}
                await upsert("key", src, target, basis, evidence, _docs_with_path(kb_id, sp["uris"]))
        # 값 동치 — 같은 버킷의 다수 표기를 표준으로
        seen_buckets = set()
        for p in cat:
            for uri, eqs in (p.get("value_equiv") or {}).items():
                if not eqs:
                    continue
                bucket = sorted([uri] + [e["uri"] for e in eqs])
                bkey = tuple(bucket)
                if bkey in seen_buckets:
                    continue
                seen_buckets.add(bkey)
                labels = {v["uri"]: v for v in (p.get("values") or [])}
                for e in eqs:
                    labels.setdefault(e["uri"], e)
                if uri in labels:
                    pass
                vals = [labels[u] for u in bucket if u in labels]
                if len(vals) < 2:
                    continue
                target_v = max(vals, key=lambda v: (v.get("members", 0), v["label"].isascii()))
                for v in vals:
                    if v["uri"] == target_v["uri"] or _compact(v["label"]) in value_ruled:
                        continue
                    if tuple(sorted((f"value:{v['label']}", f"value:{target_v['label']}"))) in ignored_values:
                        continue
                    basis = "normalized" if _compact(v["label"]) == _compact(target_v["label"]) else (
                        "lexicon" if value_canonical(v["label"]) == value_canonical(target_v["label"]) else "llm")
                    await upsert("value", v["label"], target_v["label"], basis,
                                 {"path": p["key"], "source_members": v.get("members", 0),
                                  "target_members": target_v.get("members", 0)},
                                 _docs_with_value(kb_id, v["uri"]))
    await _refresh_doc_warnings(kb_id)
    return {"paths": n_paths, "values": n_values}


async def _refresh_doc_warnings(kb_id: str) -> None:
    from app.models.document import Document
    from app.models.schema_mapping import SchemaMappingProposal
    pending = await SchemaMappingProposal.find(
        SchemaMappingProposal.kb_id == kb_id, SchemaMappingProposal.status == "pending").to_list()
    per_doc: Dict[str, int] = {}
    for p in pending:
        for d in p.doc_ids:
            per_doc[d] = per_doc.get(d, 0) + 1
    for doc in await Document.find(Document.kb_id == kb_id).to_list():
        sw = dict(doc.schema_warnings or {})
        if sw.get("pending_proposals", 0) != per_doc.get(str(doc.id), 0):
            sw["pending_proposals"] = per_doc.get(str(doc.id), 0)
            doc.schema_warnings = sw
            await doc.save()


async def on_document_ingested(kb_id: str, doc_id: str, schema_report: Optional[Dict[str, Any]]) -> None:
    """인제스트 완료 콜백에서 백그라운드로: auto 규칙 기록 → 캐시 무효화 → 제안 생성."""
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    try:
        n_auto = await record_auto_rules(kb_id, doc_id, schema_report)
        kb = await KnowledgeBase.get(kb_id)
        doc = await Document.get(doc_id)
        if doc:
            sw = dict(doc.schema_warnings or {})
            sw["auto_applied"] = len((schema_report or {}).get("auto") or [])
            sw["applied"] = sum(a.get("count", 0) for a in (schema_report or {}).get("applied") or [])
            doc.schema_warnings = sw
            doc.schema_rules_version = kb.schema_rules_version if kb else 0
            await doc.save()
        if n_auto and kb:
            kb.schema_rules_version += 1
            await kb.save()
        FusekiBackend.invalidate_class_catalog(kb_id)
        # 구조화 문서 → KB 온톨로지 전환 표시 (UI 'Ontology' 배지, TBox, schema_info)
        if doc and _is_structured_name(doc.filename):
            try:
                promo = await mark_structured_ontology(kb_id)
                logger.info(f"[Schema] structured ontology for {kb_id}: {promo}")
                if promo.get("newly_promoted"):
                    try:
                        from app.core.websocket_manager import manager
                        await manager.broadcast(kb_id, {"type": "kb_ontology_promoted", "kb_id": kb_id,
                                                        "source": "structured"})
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[Schema] structured ontology marking skipped: {e}")
        result = await detect_proposals(kb_id)
        logger.info(f"[Schema] doc {doc_id}: auto rules {n_auto}, new proposals {result}")
        try:
            from app.core.websocket_manager import manager
            await manager.broadcast(kb_id, {"type": "schema_proposals_update", "kb_id": kb_id, **result})
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"[Schema] post-ingest processing skipped for {doc_id}: {e}")


# ---------------------------------------------------------------------------
# 제안 수락 / 거절
# ---------------------------------------------------------------------------

async def accept_proposal(kb_id: str, proposal_id: str, swap: bool = False,
                          target: Optional[str] = None, renormalize: bool = True) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingProposal, SchemaMappingRule
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend

    p = await SchemaMappingProposal.get(proposal_id)
    if not p or p.kb_id != kb_id:
        raise ValueError("proposal not found")
    source, tgt = (p.target, p.source) if swap else (p.source, p.target)
    if target:
        tgt = target
    if p.kind == "key":
        rule = SchemaMappingRule(kb_id=kb_id, rule_type="key", source_path=source, target_path=tgt,
                                 origin=f"proposal:{p.id}")
    elif p.kind in ("entity", "class"):
        rule = SchemaMappingRule(kb_id=kb_id, rule_type=p.kind, source_value=source, target_value=tgt,
                                 origin=f"proposal:{p.id}")
    else:
        rule = SchemaMappingRule(kb_id=kb_id, rule_type="value", source_value=source, target_value=tgt,
                                 origin=f"proposal:{p.id}")
    await rule.insert()
    p.status = "accepted"
    p.updated_at = datetime.utcnow()
    await p.save()
    kb = await KnowledgeBase.get(kb_id)
    if kb:
        kb.schema_rules_version += 1
        await kb.save()
    FusekiBackend.invalidate_class_catalog(kb_id)
    renorm = {"queued": [], "needs_source": []}
    if renormalize and p.doc_ids:
        renorm = await renormalize_documents(kb_id, p.doc_ids)
    await _refresh_doc_warnings(kb_id)
    return {"rule_id": str(rule.id), "renormalize": renorm}


async def reject_proposal(kb_id: str, proposal_id: str) -> Dict[str, Any]:
    from app.models.schema_mapping import SchemaMappingProposal, SchemaMappingRule
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    p = await SchemaMappingProposal.get(proposal_id)
    if not p or p.kb_id != kb_id:
        raise ValueError("proposal not found")
    pair = [p.source, p.target] if p.kind == "key" else [f"value:{p.source}", f"value:{p.target}"]
    rule = SchemaMappingRule(kb_id=kb_id, rule_type="ignore", pair=pair, origin=f"proposal:{p.id}")
    await rule.insert()
    p.status = "rejected"
    p.updated_at = datetime.utcnow()
    await p.save()
    FusekiBackend.invalidate_class_catalog(kb_id)
    await _refresh_doc_warnings(kb_id)
    return {"rule_id": str(rule.id)}


# ---------------------------------------------------------------------------
# 재정규화 = 같은 doc_id 재인제스트
# ---------------------------------------------------------------------------

async def _structured_ingest_job(kb, doc, replace_existing: bool) -> None:
    """구조화 문서 재인제스트 요청 (임베딩만 필요)."""
    from app.api.document import _build_and_validate_upload_model_configs
    from app.services.ingestion.ingest_client import ingest_client

    model_configs = await _build_and_validate_upload_model_configs(
        kb=kb, final_config={}, chunking_cfg={"strategy": "fixed_size"},
        graph_config={"extractor_type": "none"}, enable_subject_restoration=False,
        enable_entity_normalization=False)
    schema = await ingest_schema_payload(str(kb.id))
    callback_base = os.getenv("CALLBACK_BASE_URL", "http://127.0.0.1:8000")
    await ingest_client.create_ingest_job(
        kb_id=str(kb.id), doc_id=str(doc.id), file_path=doc.file_path,
        chunking_config={"strategy": "fixed_size", "chunk_size": 300, "chunk_overlap": 20},
        graph_config={"extractor_type": "simple", "generate_inverse_relations": False},
        graph_store="fuseki" if kb.graph_backend == "ontology" else "neo4j",
        enable_subject_restoration=False,
        callback_url=f"{callback_base.rstrip('/')}/api/v2/knowledge-bases/ingest/callback",
        embedding_model=model_configs["embedding_model"],
        schema_rules=schema["schema_rules"], schema_vocab=schema["schema_vocab"],
        replace_existing=replace_existing,
    )


async def renormalize_documents(kb_id: str, doc_ids: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """규칙 반영을 위해 문서를 재인제스트. 원본이 없으면 needs_source 로 응답."""
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase

    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise ValueError("KB not found")
    if doc_ids:
        docs = [d for d in [await Document.get(i) for i in doc_ids] if d and d.kb_id == kb_id]
    else:
        docs = [d for d in await Document.find(Document.kb_id == kb_id).to_list()
                if (d.schema_rules_version or 0) < (kb.schema_rules_version or 0)]
    queued, needs_source = [], []
    runnable = []
    text_docs = [d for d in docs if not _is_structured_name(d.filename)]
    docs = [d for d in docs if _is_structured_name(d.filename)]
    if text_docs:
        # 텍스트 문서는 원본 없이 저장된 추출 트리플 리플레이로 재정규화
        asyncio.create_task(replay_documents(kb_id, [str(d.id) for d in text_docs]))
        queued.extend(str(d.id) for d in text_docs)
    for d in docs:
        if d.file_path and os.path.exists(d.file_path):
            runnable.append(d)
            queued.append(str(d.id))
        else:
            needs_source.append(str(d.id))

    async def run_all():
        sem = asyncio.Semaphore(RENORMALIZE_CONCURRENCY)

        async def one(d):
            async with sem:
                from app.models.document import DocumentStatus
                d.status = DocumentStatus.PROCESSING.value
                d.pipeline_status = "RENORMALIZING"
                await d.save()
                try:
                    await _structured_ingest_job(kb, d, replace_existing=True)
                except Exception as e:
                    logger.warning(f"[Renormalize] submit failed for {d.id}: {e}")
                    return
                # 완료 콜백(상태 갱신)을 기다려 동시 실행 수를 제한
                for _ in range(150):
                    await asyncio.sleep(2)
                    cur = await Document.get(d.id)
                    if cur and cur.pipeline_status != "RENORMALIZING" and cur.status != DocumentStatus.PROCESSING.value:
                        break

        await asyncio.gather(*(one(d) for d in runnable))

    if runnable:
        asyncio.create_task(run_all())
    return {"queued": queued, "needs_source": needs_source}


# ---------------------------------------------------------------------------
# 구조화 문서 → 온톨로지 전환 (schema_source = "structured")
# ---------------------------------------------------------------------------

async def mark_structured_ontology(kb_id: str) -> Dict[str, Any]:
    """구조화(YAML/JSON) 문서가 인제스트된 ontology KB 를 온톨로지로 표시하고 TBox 를 갱신.

    구조화 문서는 필드 구조가 곧 스키마이므로 별도 승격(유도) 없이 온톨로지가 된다.
    - is_promoted=True (UI 'Ontology' 배지), schema_source='structured', schema_status='active'
      (단, 이미 declared/induced 인 KB 는 출처를 바꾸지 않는다)
    - TBox(urn:ontology:{kb}): 레코드·구조 클래스 + 속성(경로 세그먼트), 데이터와 같은 rag.local URI
    - promotion_metadata.schema_info: C 경로(SPARQL 생성)가 읽는 클래스·속성 목록
    """
    import re as _re
    import requests
    from app.core.fuseki import fuseki_client
    from app.models.knowledge_base import KnowledgeBase
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    from app.services.retrieval.relation_targeting import local_name

    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.graph_backend != "ontology":
        return {"skipped": "not an ontology KB"}
    if kb.schema_source in ("declared", "induced"):
        return {"skipped": f"schema_source={kb.schema_source}"}

    FusekiBackend.invalidate_class_catalog(kb_id)
    kinds, catalogs = await FusekiBackend()._class_catalog(kb_id, lambda _m: None, {})
    # 구조 노드에 붙은 rdf:type 클래스 (Tradeoffs, Avoid_signals …)
    q = """SELECT DISTINCT ?t (COUNT(DISTINCT ?s) AS ?n) WHERE { GRAPH ?g { ?s a ?t }
           FILTER(STRSTARTS(STR(?g), "urn:doc:")) FILTER(STRSTARTS(STR(?t), "http://rag.local/class/")) } GROUP BY ?t"""
    struct_classes = {}
    try:
        for b in fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", []):
            struct_classes[local_name(b["t"]["value"])] = int(b["n"]["value"])
    except Exception:
        pass

    def uri_part(x: str) -> str:
        return _re.sub(r"[^0-9A-Za-z가-힣_]", "_", str(x).strip())

    def lit(x: str) -> str:
        return '"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"'

    # 사람이 고친 유형 이름·설명은 카탈로그(apply_kind_overlay)에서 이미 반영됨 — orig_name 이 있으면 덧씌운 이름
    def kind_class(k):
        if k.get("orig_name"):
            return k["name"]
        return local_name(k["class_uri"]) if k.get("class_uri") else "Record"

    classes: Dict[str, Dict[str, Any]] = {}
    for k in kinds:
        name = kind_class(k)
        classes[name] = {"label": name, "count": len(k["members"]),
                         "description": k.get("description") or (
                             "구조화 문서의 최상위 레코드" if not k.get("class_uri") else "")}
    for name, n in struct_classes.items():
        classes.setdefault(name, {"label": name, "count": n, "description": "구조화 문서의 중첩 항목"})
    props: Dict[str, str] = {}
    prop_notes: Dict[str, Dict[str, Any]] = {}   # 마지막 세그먼트 → 정의·별칭 (덧씌우기)
    for k in kinds:
        dom = kind_class(k)
        for p in catalogs.get(k["name"], []):
            for i, seg in enumerate(p["segments"]):
                props.setdefault(seg, dom if i == 0 else "")
            if p.get("description") or p.get("aliases"):
                prop_notes.setdefault(p["segments"][-1], {"description": p.get("description"), "aliases": p.get("aliases")})

    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
    for name, c in classes.items():
        lines.append(f"<http://rag.local/class/{uri_part(name)}> a owl:Class ; rdfs:label {lit(name)}"
                     + (f" ; rdfs:comment {lit(c['description'])}" if c.get("description") else "") + " .")
    lines.insert(2, "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .")
    for seg, dom in props.items():
        note = prop_notes.get(seg) or {}
        lines.append(f"<http://rag.local/rel/{uri_part(seg)}> a owl:ObjectProperty ; rdfs:label {lit(seg)}"
                     + (f" ; rdfs:domain <http://rag.local/class/{uri_part(dom)}>" if dom else "")
                     + (f" ; rdfs:comment {lit(note['description'])}" if note.get("description") else "")
                     + "".join(f" ; skos:altLabel {lit(a)}" for a in note.get("aliases") or [])
                     + " .")
    ttl = "\n".join(lines) + "\n"
    graph_uri = f"urn:ontology:{kb_id}"
    tbox_ok = False
    try:
        fuseki_client.drop_graph(kb_id, graph_uri)
        resp = requests.post(f"{fuseki_client._get_dataset_url(kb_id)}/data?graph={graph_uri}",
                             data=ttl.encode("utf-8"), headers={"Content-Type": "text/turtle"},
                             auth=fuseki_client.auth, timeout=60)
        tbox_ok = resp.status_code in (200, 201, 204)
    except Exception as e:
        logger.warning(f"[Schema] structured TBox upload skipped: {e}")

    meta = dict(kb.promotion_metadata or {})
    meta["schema_info"] = {
        "classes": {f"http://rag.local/class/{uri_part(n)}": c for n, c in classes.items()},
        "properties": [f"http://rag.local/rel/{uri_part(s)}" for s in props],
    }
    meta["source"] = "structured"
    meta["promoted_at"] = datetime.utcnow().isoformat()
    kb.promotion_metadata = meta
    newly = not kb.is_promoted
    kb.is_promoted = True
    kb.schema_source = "structured"
    kb.schema_status = "active"
    await kb.save()
    return {"classes": len(classes), "properties": len(props), "tbox": tbox_ok, "newly_promoted": newly}
