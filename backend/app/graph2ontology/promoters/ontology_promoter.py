"""Ontology Promoter - KG → OWL Ontology 승격 파이프라인"""

from pathlib import Path
from typing import Union, Optional
from datetime import datetime
from collections import defaultdict

from rdflib import Graph, Dataset, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD, SKOS
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()


# 커스텀 네임스페이스
EVIDENCE = Namespace("http://example.org/evidence/")
PROV = Namespace("http://www.w3.org/ns/prov#")

# Step 2 그래프 프로파일링 상한 (design-ontology-schema-extraction-v2.md §3 참고)
MAX_RELATIONS = 60
SAMPLES_PER_RELATION = 5
MAX_FREQUENT_CONCEPTS = 80


class OntologyPromoter:
    """7단계 Ontology 승격 파이프라인
    
    Step 1: Candidate Selection - confidence 필터링, 다중 근거 검증
    Step 2: Schema Stabilization - Class/Property 확정, 동의어 병합
    Step 3: Hierarchy Finalization - 계층 확정, cycle 제거
    Step 4: Constraint Injection - domain/range, cardinality
    Step 5: Evidence Removal - 순수 OWL 생성
    Step 6: Reasoner Validation - consistency check
    Step 7: Export & Versioning - OWL 파일 생성
    """
    
    def __init__(
        self,
        confidence_threshold: float = 0.85,
        min_evidence_count: int = 2,
        detect_cycles: bool = True,
        remove_hypothetical: bool = True,
    ):
        self.confidence_threshold = confidence_threshold
        self.min_evidence_count = min_evidence_count
        self.detect_cycles = detect_cycles
        self.remove_hypothetical = remove_hypothetical
        
        self.stats = {
            "input_triples": 0,
            "step1_candidates": 0,
            "step2_classes": 0,
            "step2_properties": 0,
            "step3_cycles_removed": 0,
            "step4_constraints": 0,
            "step5_evidence_removed": 0,
            "output_triples": 0,
        }
    
    def load_kg(self, kg_path: Union[str, Path]) -> Dataset:
        """Knowledge Graph 로드 (TriG)"""
        kg_path = Path(kg_path)
        ds = Dataset()
        ds.parse(kg_path, format="trig")
        
        # 전체 트리플 수 계산
        for g in ds.graphs():
            self.stats["input_triples"] += len(g)
        
        return ds
    
    def promote(
        self,
        base_trig: Union[str, Path],
        evidence_trig: Optional[Union[str, Path]] = None,
        output_dir: Union[str, Path] = "./ontology",
        version: str = "v1.0",
        dry_run: bool = False,
    ) -> dict:
        """전체 승격 파이프라인 실행"""
        output_dir = Path(output_dir)
        
        # Step 0: KG 로드
        base_ds = self.load_kg(base_trig)
        evidence_ds = None
        if evidence_trig and Path(evidence_trig).exists():
            evidence_ds = self.load_kg(evidence_trig)
        
        # 모든 그래프를 하나로 병합
        # 모든 그래프를 하나로 병합 (Base + Evidence)
        merged_graph = Graph()
        for g in base_ds.graphs():
            for triple in g:
                merged_graph.add(triple)
        
        if evidence_ds:
            for g in evidence_ds.graphs():
                for triple in g:
                    merged_graph.add(triple)
        
        # Evidence 정보 수집
        evidence_info = self._collect_evidence(evidence_ds) if evidence_ds else {}
        
        # Step 1: Candidate Selection
        candidates = self._step1_candidate_selection(merged_graph, evidence_info)
        
        # Step 2: Schema Stabilization
        schema = self._step2_schema_stabilization(candidates)
        
        # Step 3: Hierarchy Finalization
        hierarchy = self._step3_hierarchy_finalization(schema)
        
        # Step 4: Constraint Injection
        constrained = self._step4_constraint_injection(hierarchy)
        
        # Step 5: Evidence Removal
        clean_owl = self._step5_evidence_removal(constrained)
        
        # Step 6: Reasoner Validation
        validation = self._step6_reasoner_validation(clean_owl)
        
        # Step 7: Export & Versioning
        self.stats["output_triples"] = len(clean_owl)
        
        result = {
            "version": version,
            "stats": self.stats.copy(),
            "validation": validation,
            "dry_run": dry_run,
            "excluded_items": getattr(self, "excluded_items", []),
            "schema_info": getattr(self, "schema_info", {})
        }
        
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # ontology.owl 저장
            owl_path = output_dir / f"ontology_{version}.owl"
            clean_owl.serialize(owl_path, format="xml")
            result["ontology_path"] = str(owl_path)
            
            # schema_snapshot.ttl 저장
            schema_path = output_dir / "schema_snapshot.ttl"
            self._export_schema_snapshot(clean_owl, schema_path)
            result["schema_path"] = str(schema_path)
            
            # instance_types.ttl 저장
            abox_path = output_dir / "instance_types.ttl"
            self._export_instance_types(clean_owl, abox_path)
            result["instance_types_path"] = str(abox_path)
            
            # promotion_report.md 저장
            report_path = output_dir / "promotion_report.md"
            self._generate_report(result, report_path)
            result["report_path"] = str(report_path)
        
        return result
    
    def _collect_evidence(self, ds: Dataset) -> dict:
        """Evidence 정보 수집 (triple -> evidence count, max confidence)"""
        evidence_info = defaultdict(lambda: {"count": 0, "max_confidence": 0.0})
        
        for g in ds.graphs():
            # RDF-star 또는 reified statement에서 evidence 추출
            for stmt in g.subjects(RDF.type, RDF.Statement):
                subj = g.value(stmt, RDF.subject)
                pred = g.value(stmt, RDF.predicate)
                obj = g.value(stmt, RDF.object)
                conf = g.value(stmt, EVIDENCE.confidence)
                
                if subj and pred and obj:
                    key = (str(subj), str(pred), str(obj))
                    evidence_info[key]["count"] += 1
                    if conf:
                        try:
                            conf_val = float(conf)
                            evidence_info[key]["max_confidence"] = max(
                                evidence_info[key]["max_confidence"], conf_val
                            )
                        except (ValueError, TypeError):
                            pass
        
        return dict(evidence_info)
    
    
    def _step1_candidate_selection(self, g: Graph, evidence_info: dict) -> Graph:
        """Step 1: Candidate Selection - confidence/evidence 기반 필터링"""
        result = Graph()
        self.excluded_items = [] # Reset or init log

        # evidence가 없으면 모든 트리플 통과 (기본값 사용)
        if not evidence_info:
            for s, p, o in g:
                result.add((s, p, o))
            self.stats["step1_candidates"] = len(g)
            return result
        
        # evidence가 있으면 필터링 적용
        for s, p, o in g:
            key = (str(s), str(p), str(o))
            info = evidence_info.get(key, {"count": 1, "max_confidence": 1.0})
            
            # 필터링 조건
            passed = True
            reason = []
            
            # Whitelist: 구조적/메타데이터 속성은 항상 통과
            is_structural = (
                p in {RDF.type, RDFS.label, RDFS.comment, RDFS.domain, RDFS.range, RDFS.subClassOf} or
                str(p).startswith(str(OWL))
            )
            
            if not is_structural:
                if info["max_confidence"] < self.confidence_threshold:
                    passed = False
                    reason.append(f"Low Confidence ({info['max_confidence']:.2f} < {self.confidence_threshold})")
                    
                if info["count"] < self.min_evidence_count:
                    passed = False
                    reason.append(f"Insufficient Evidence ({info['count']} < {self.min_evidence_count})")
            
            if passed:
                result.add((s, p, o))
                self.stats["step1_candidates"] += 1
            else:
                self.excluded_items.append({
                    "triple": f"{s} {p} {o}",
                    "subject": str(s),
                    "predicate": str(p),
                    "object": str(o),
                    "reason": ", ".join(reason),
                    "confidence": info["max_confidence"],
                    "evidence_count": info["count"]
                })
        
        return result
    
    def _call_llm_for_schema(self, prompt: str) -> dict:
        """LLM API 호출"""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
             raise ValueError("Ontology promoter model API key is not configured.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
        }
        
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=180,  # o1 takes longer
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            
            # Debug: Print raw response
            print(f"[OntologyPromoter] LLM Raw Response (first 500 chars): {content[:500]}")
            
            # JSON clean up
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            result = json.loads(content.strip())
            print(f"[OntologyPromoter] Parsed JSON keys: {list(result.keys())}")
            return result
        except Exception as e:
            print(f"[OntologyPromoter] LLM Call Failed: {e}")
            return {}

    def _label_of(self, g: Graph, uri) -> str:
        """URI의 표시용 라벨을 반환.

        rdfs:label이 있으면 그 값을 사용(여러 개면 정렬 후 첫 번째),
        없으면 URI 로컬네임으로 폴백. Literal이 들어오면 그대로 문자열화.
        """
        if isinstance(uri, Literal):
            return str(uri)
        if not isinstance(uri, URIRef):
            return str(uri)
        labels = sorted(str(l) for l in g.objects(uri, RDFS.label))
        if labels:
            return labels[0]
        return str(uri).split('/')[-1].split('#')[-1]

    def _build_graph_profile(self, g: Graph) -> dict:
        """그래프를 단일 순회하여 관계 프로파일/개념 빈도/타입 힌트를 추출.

        design-ontology-schema-extraction-v2.md §3.2 참고.
        """
        built_in_namespaces = [str(RDF), str(RDFS), str(OWL), str(XSD), str(SKOS)]

        relation_counts = defaultdict(int)
        relation_triples = defaultdict(list)  # predicate localname -> [(s, o)]
        relation_pairs = defaultdict(list)     # predicate localname -> [(subj_uri, obj_uri)] (URIRef만)
        entity_counts = defaultdict(int)
        type_hints = defaultdict(list)         # class localname -> [instance label]

        for s, p, o in g:
            # rdf:type 엣지는 관계 목록이 아니라 type_hints 수집용으로 별도 처리
            if p == RDF.type:
                if o == RDF.Statement:
                    continue
                if isinstance(o, URIRef):
                    cls_local = str(o).split('/')[-1].split('#')[-1]
                    type_hints[cls_local].append(self._label_of(g, s))
                continue

            p_str = str(p)
            # Built-in 네임스페이스 predicate 제외
            if any(p_str.startswith(ns) for ns in built_in_namespaces):
                continue
            # rdfs:label은 라벨 조회 전용이므로 관계 목록에서 제외 (위 built-in 체크에 이미 포함되지만 명시)
            if p == RDFS.label:
                continue

            p_local = p_str.split('/')[-1].split('#')[-1]
            relation_counts[p_local] += 1
            relation_triples[p_local].append((s, o))

            # 인스턴스 타이핑(§3.5)에 쓸 실제 URIRef 쌍만 별도 보관
            if isinstance(s, URIRef) and isinstance(o, URIRef):
                relation_pairs[p_local].append((s, o))

            # 개념(엔티티) 빈도: subject / URIRef object만 카운트
            entity_counts[s] += 1
            if isinstance(o, URIRef):
                entity_counts[o] += 1

        # 관계 정렬(빈도 내림차순) + 상한 적용 (무음 절단 금지)
        sorted_relation_names = sorted(
            relation_counts.keys(), key=lambda k: relation_counts[k], reverse=True
        )
        if len(sorted_relation_names) > MAX_RELATIONS:
            dropped = len(sorted_relation_names) - MAX_RELATIONS
            print(
                f"[OntologyPromoter] _build_graph_profile: {dropped} relations dropped "
                f"(exceeded MAX_RELATIONS={MAX_RELATIONS})"
            )
            sorted_relation_names = sorted_relation_names[:MAX_RELATIONS]

        relations = []
        for name in sorted_relation_names:
            pairs = relation_triples[name]
            # 서로 다른 subject를 우선 채택해 예시 다양성 확보
            seen_subjects = set()
            ordered = []
            remainder = []
            for s, o in pairs:
                if s not in seen_subjects:
                    seen_subjects.add(s)
                    ordered.append((s, o))
                else:
                    remainder.append((s, o))
            examples_src = (ordered + remainder)[:SAMPLES_PER_RELATION]

            examples = [
                {
                    "s": self._label_of(g, s),
                    "o": self._label_of(g, o),
                    "o_is_literal": isinstance(o, Literal),
                }
                for s, o in examples_src
            ]

            relations.append({
                "name": name,
                "count": relation_counts[name],
                "examples": examples,
            })

        # 빈도 상위 개념 (상한 초과분은 로그로 남기고 절단)
        sorted_entities = sorted(entity_counts.keys(), key=lambda k: entity_counts[k], reverse=True)
        if len(sorted_entities) > MAX_FREQUENT_CONCEPTS:
            dropped = len(sorted_entities) - MAX_FREQUENT_CONCEPTS
            print(
                f"[OntologyPromoter] _build_graph_profile: {dropped} frequent concepts dropped "
                f"(exceeded MAX_FREQUENT_CONCEPTS={MAX_FREQUENT_CONCEPTS})"
            )
        top_entities = sorted_entities[:MAX_FREQUENT_CONCEPTS]
        frequent_concepts = [self._label_of(g, e) for e in top_entities]

        return {
            "relations": relations,
            "frequent_concepts": frequent_concepts,
            "type_hints": dict(type_hints),
            "_relation_pairs": dict(relation_pairs),
        }

    def _step2_schema_stabilization(self, g: Graph) -> Graph:
        """Step 2: Schema Stabilization - Class/Property 확정 (LLM 활용)"""

        # 0. 그래프 요약 (Concept & Relation 추출)
        # LLM에게 보낼 컨텍스트를 만들기 위해 그래프의 주요 요소(주어, 목적어, 서술어)를 수집
        subjects = set(g.subjects())
        objects = set()
        for o in g.objects():
            if isinstance(o, URIRef):
                objects.add(o)

        predicates = set(g.predicates())

        # 그래프 프로파일 생성: 관계별 빈도/예시 트리플, 개념 빈도, 타입 힌트
        # (design-ontology-schema-extraction-v2.md §3.2)
        profile = self._build_graph_profile(g)

        # 프롬프트용 렌더링: 관계 (빈도, 예시 트리플)
        relations_lines = []
        for rel in profile["relations"]:
            example_strs = []
            for ex in rel["examples"]:
                o_display = f"{ex['o']}[lit]" if ex["o_is_literal"] else ex["o"]
                example_strs.append(f"{ex['s']}→{o_display}")
            relations_lines.append(f"- {rel['name']} ({rel['count']}×): {', '.join(example_strs)}")
        relations_block = '\n'.join(relations_lines) if relations_lines else "(no relations observed)"

        frequent_concepts_str = (
            ', '.join(profile["frequent_concepts"]) if profile["frequent_concepts"] else "(none)"
        )

        type_hints = profile.get("type_hints", {})
        if not type_hints:
            known_types_str = "none — infer from patterns"
        else:
            type_lines = []
            for cls_name, instances in type_hints.items():
                sample = instances[:10]
                suffix = f", ... (+{len(instances) - 10} more)" if len(instances) > 10 else ""
                type_lines.append(f"{cls_name}: {', '.join(sample)}{suffix}")
            known_types_str = '; '.join(type_lines)

        # 1. LLM에게 스키마 생성 요청 (Structured 7-Step Prompt)
        prompt = f"""You are an ontology schema extraction agent.

Your task is to extract a SCHEMA (TBox) from an EXISTING GRAPH.
The graph already contains nodes and relationships (instances),
but no explicit ontology schema is defined.

You must reverse-engineer the ontology schema from graph patterns.

## OBSERVED GRAPH PATTERNS

Relations (name, frequency, example triples):
{relations_block}

Frequent entities: {frequent_concepts_str}

Known types: {known_types_str}

## STRICT RULES

1. Extract ONLY schema-level concepts (classes, properties).
2. Do NOT output instances or individuals.
3. Do NOT invent concepts not supported by graph patterns.
4. Do NOT assume domain knowledge outside the graph.
5. Prefer general, reusable concepts over overly specific ones. However, keep meaningful recurring distinctions as separate classes; do not over-merge.
6. If something is ambiguous, exclude it.
7. Do NOT create artificial root classes like "Thing", "Entity", "Object", "Concept", or "Resource".
8. Every class MUST be connected to at least one other class - NO orphan classes allowed.

## EXTRACTION STEPS (Follow in order)

STEP 1. Class Extraction
- Identify candidate Classes from node labels or rdf:type patterns.
- Exclude literal/value-only nodes.
- Exclude obvious instance identifiers (e.g., specific person names, IDs).

STEP 2. Data Property Extraction
- For each class, extract properties that hold literal values.
- Infer datatype ranges (string, integer, date, boolean, etc.).
- Include a data property only if it appears consistently.

STEP 3. Object Property Extraction
- Identify relationship types between nodes.
- Normalize relationship names into ontology-style predicates.
- Treat relationships as ObjectProperties, not classes.
- For each ObjectProperty, record in `source_relations` the ORIGINAL relation name(s)
  from the Relations list above that it was derived from. Copy them VERBATIM as shown
  (e.g. "출연"), even if you renamed the property. This is required for instance typing.

STEP 4. Domain & Range Identification (CRITICAL)
- For each ObjectProperty, determine:
  - Domain class (source node type)
  - Range class (target node type)
- Determine domain/range ONLY from the subject/object types observed in the example triples above.
- EVERY ObjectProperty MUST have both domain and range defined.

STEP 5. Intermediate Node Evaluation
- If a node exists only to connect two others and has no meaningful properties,
  collapse it into a direct ObjectProperty.
- If it has its own attributes or semantic meaning, keep it as a Class.

STEP 6. Class Hierarchy (Optional)
- Introduce superclass relationships ONLY if:
  - Multiple classes share clear structural patterns
  - The superclass is semantically meaningful

STEP 7. Connectivity Verification
- Verify EVERY class participates in at least one relationship.
- If a class has no connections, either find a relationship or remove it.

## REQUIRED OUTPUT FORMAT (JSON)

{{
  "classes": [
    {{"name": "ClassName", "description": "Brief description"}}
  ],
  "object_properties": [
    {{
      "name": "propertyName",
      "domain": "SourceClass",
      "range": "TargetClass",
      "source_relations": ["<original relation name(s) from the Relations list above, verbatim>"],
      "description": "Brief description"
    }}
  ],
  "data_properties": [
    {{
      "name": "attributeName",
      "domain": "OwnerClass",
      "range": "xsd:string"
    }}
  ],
  "class_hierarchy": [
    {{"child": "ChildClass", "parent": "ParentClass"}}
  ]
}}

## EXAMPLE

For a TV show domain with concepts [성기훈, 오일남, 프론트맨, 시즌1, 에피소드, 게임] and relations [출연, 등장, 포함]:

{{
  "classes": [
    {{"name": "Person", "description": "A character in the show"}},
    {{"name": "Season", "description": "A season of the TV series"}},
    {{"name": "Episode", "description": "An episode within a season"}},
    {{"name": "Game", "description": "A game event in the show"}}
  ],
  "object_properties": [
    {{"name": "appearsIn", "domain": "Person", "range": "Episode", "source_relations": ["출연", "등장"], "description": "Character appears in episode"}},
    {{"name": "participatesIn", "domain": "Person", "range": "Game", "source_relations": ["참가"], "description": "Character participates in game"}},
    {{"name": "hasSeason", "domain": "Episode", "range": "Season", "source_relations": ["포함"], "description": "Episode belongs to season"}},
    {{"name": "featuresGame", "domain": "Episode", "range": "Game", "source_relations": ["포함"], "description": "Episode features a game"}}
  ],
  "data_properties": [
    {{"name": "name", "domain": "Person", "range": "xsd:string"}},
    {{"name": "title", "domain": "Episode", "range": "xsd:string"}}
  ],
  "class_hierarchy": []
}}

NOTE: The example above is for FORMAT ONLY. It is a small illustration of the JSON shape and naming
style — it is NOT a target size. The number of classes and properties you output MUST match the
actual complexity of the OBSERVED GRAPH PATTERNS above, not the size of this example.

IMPORTANT: Output schema ONLY (TBox). Do NOT include example instances. Do NOT explain the graph itself.
Now analyze the input and generate the schema.
"""
        print("[OntologyPromoter] Requesting Schema to LLM (Improved Prompt)...")
        llm_schema = self._call_llm_for_schema(prompt)
        
        # Parse new structured format
        raw_classes = llm_schema.get("classes", [])
        raw_obj_props = llm_schema.get("object_properties", [])
        raw_data_props = llm_schema.get("data_properties", [])
        raw_hierarchy = llm_schema.get("class_hierarchy", [])
        
        # Extract class names (handle both old format ["name"] and new format [{"name": "..."}])
        generated_classes = set()
        for c in raw_classes:
            if isinstance(c, dict):
                generated_classes.add(c.get("name", ""))
            else:
                generated_classes.add(c)
        
        print(f"[OntologyPromoter] LLM Generated: {len(generated_classes)} Classes, {len(raw_obj_props) + len(raw_data_props)} Properties")

        # 2. 그래프에 스키마 적용 (매핑)
        explicit_classes = set()
        explicit_props = set()
        
        # URI 매핑 딕셔너리 구축 (LocalName -> URI List)
        local_name_map = defaultdict(list)
        all_uris = subjects | objects | predicates
        for u in all_uris:
            local = str(u).split('/')[-1].split('#')[-1]
            local_name_map[local].append(u)
            
        base_uri = "http://example.org/onto/class/"
        prop_base_uri = "http://example.org/onto/prop/"
        
        # Helper: Get or create class URI
        def get_class_uri(cls_name):
            candidates = local_name_map.get(cls_name, [])
            for cand in candidates:
                if "/class/" in str(cand):
                    return cand
            from urllib.parse import quote
            return URIRef(f"{base_uri}{quote(cls_name)}")
        
        # Helper: Get or create property URI
        def get_prop_uri(prop_name):
            candidates = local_name_map.get(prop_name, [])
            for cand in candidates:
                if "/prop/" in str(cand) or "/rel/" in str(cand):
                    return cand
            from urllib.parse import quote
            return URIRef(f"{prop_base_uri}{quote(prop_name)}")
        
        # A. Add Classes
        class_uri_map = {}  # name -> URI
        for cls_name in generated_classes:
            if not cls_name:
                continue
            target_uri = get_class_uri(cls_name)
            g.add((target_uri, RDF.type, OWL.Class))
            explicit_classes.add(target_uri)
            class_uri_map[cls_name] = target_uri
            
        # B. Add Object Properties with Domain/Range
        for prop in raw_obj_props:
            if isinstance(prop, dict):
                prop_name = prop.get("name", "")
                domain_name = prop.get("domain", "")
                range_name = prop.get("range", "")
            else:
                prop_name = prop
                domain_name = ""
                range_name = ""
            
            if not prop_name:
                continue
                
            prop_uri = get_prop_uri(prop_name)
            g.add((prop_uri, RDF.type, OWL.ObjectProperty))
            explicit_props.add(prop_uri)
            
            # Add domain/range if specified
            if domain_name and domain_name in class_uri_map:
                g.add((prop_uri, RDFS.domain, class_uri_map[domain_name]))
            if range_name and range_name in class_uri_map:
                g.add((prop_uri, RDFS.range, class_uri_map[range_name]))

        # C. Add Data Properties with Domain
        for prop in raw_data_props:
            if isinstance(prop, dict):
                prop_name = prop.get("name", "")
                domain_name = prop.get("domain", "")
            else:
                prop_name = prop
                domain_name = ""
            
            if not prop_name:
                continue
                
            prop_uri = get_prop_uri(prop_name)
            g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
            explicit_props.add(prop_uri)
            
            if domain_name and domain_name in class_uri_map:
                g.add((prop_uri, RDFS.domain, class_uri_map[domain_name]))
        
        # D. Add Class Hierarchy (subClassOf)
        for hier in raw_hierarchy:
            if isinstance(hier, dict):
                child_name = hier.get("child", "")
                parent_name = hier.get("parent", "")
                if child_name in class_uri_map and parent_name in class_uri_map:
                    g.add((class_uri_map[child_name], RDFS.subClassOf, class_uri_map[parent_name]))

        # E. 인스턴스-타입 링크 부여 (design-ontology-schema-extraction-v2.md §3.5, 버그 ④ 수정)
        # domain/range가 모두 확정된 ObjectProperty에 한해, 프로파일에서 수집해 둔
        # 실제 (subject, object) URI 쌍에 rdf:type을 부여한다. LLM이 관계명을 정규화(rename)
        # 하므로, 원본 관계명은 LLM이 반환한 source_relations로 매칭한다. (없으면 name으로 폴백)
        relation_pairs = profile.get("_relation_pairs", {})
        instance_types_assigned = 0
        typed_pairs_seen = set()  # (subj, cls) / (obj, cls) 중복 카운트 방지
        for prop in raw_obj_props:
            if not isinstance(prop, dict):
                continue
            prop_name = prop.get("name", "")
            domain_name = prop.get("domain", "")
            range_name = prop.get("range", "")
            if not prop_name or not domain_name or not range_name:
                continue

            domain_uri = class_uri_map.get(domain_name)
            range_uri = class_uri_map.get(range_name)
            if domain_uri is None or range_uri is None:
                continue

            # 원본 관계명 후보: source_relations 우선, 없으면 정규화된 name으로 폴백
            source_rels = prop.get("source_relations")
            if isinstance(source_rels, str):
                source_rels = [source_rels]
            elif not isinstance(source_rels, list) or not source_rels:
                source_rels = [prop_name]

            for rel_name in source_rels:
                pairs = relation_pairs.get(rel_name)
                if not pairs:
                    continue
                for subj_uri, obj_uri in pairs:
                    if (subj_uri, domain_uri) not in typed_pairs_seen:
                        g.add((subj_uri, RDF.type, domain_uri))
                        typed_pairs_seen.add((subj_uri, domain_uri))
                        instance_types_assigned += 1
                    if (obj_uri, range_uri) not in typed_pairs_seen:
                        g.add((obj_uri, RDF.type, range_uri))
                        typed_pairs_seen.add((obj_uri, range_uri))
                        instance_types_assigned += 1

        print(f"[OntologyPromoter] Instance-type assignment: {instance_types_assigned} type edges added")

        # 3. 통계 및 Info 업데이트
        self.stats["step2_classes"] = len(explicit_classes)
        self.stats["step2_properties"] = len(explicit_props)
        
        # Save for schema export (only LLM-generated schema)
        self.explicit_classes = explicit_classes
        self.explicit_props = explicit_props
        
        # Schema Info 저장 (frontend 표시용)
        classes_info = {}
        for cls in explicit_classes:
            instances = list(g.subjects(RDF.type, cls))
            classes_info[str(cls)] = {
                "count": len(instances),
                "instances": sorted([str(inst) for inst in instances])
            }
            
        self.schema_info = {
            "classes": classes_info,
            "properties": sorted([str(p) for p in explicit_props])
        }
        
        return g
        
        # owl:sameAs 동의어 병합
        same_as_pairs = list(g.subject_objects(OWL.sameAs))
        for canonical, alias in same_as_pairs:
            # alias를 canonical로 대체
            for s, p, o in list(result.triples((alias, None, None))):
                result.remove((s, p, o))
                result.add((canonical, p, o))
            for s, p, o in list(result.triples((None, None, alias))):
                result.remove((s, p, o))
                result.add((s, p, canonical))
        
        return result
    
    def _step3_hierarchy_finalization(self, g: Graph) -> Graph:
        """Step 3: Hierarchy Finalization - cycle 제거"""
        result = Graph()
        
        for s, p, o in g:
            result.add((s, p, o))
        
        if self.detect_cycles:
            # rdfs:subClassOf cycle 제거
            self.stats["step3_cycles_removed"] += self._remove_cycles(result, RDFS.subClassOf)
            self.stats["step3_cycles_removed"] += self._remove_cycles(result, RDFS.subPropertyOf)
        
        return result
    
    def _remove_cycles(self, g: Graph, relation: URIRef) -> int:
        """Cycle 제거"""
        removed = 0
        
        # 직접 cycle (A -> A)
        for s, p, o in list(g.triples((None, relation, None))):
            if s == o:
                g.remove((s, p, o))
                removed += 1
        
        # 2-hop cycle (A -> B -> A)
        for a, _, b in list(g.triples((None, relation, None))):
            for _, _, c in list(g.triples((b, relation, None))):
                if c == a:
                    g.remove((b, relation, a))
                    removed += 1
        
        return removed
    
    def _step4_constraint_injection(self, g: Graph) -> Graph:
        """Step 4: Constraint Injection - domain/range 등"""
        result = Graph()
        
        for s, p, o in g:
            result.add((s, p, o))
        
        # 기존 domain/range 유지
        constraints = 0
        for prop in result.subjects(RDF.type, OWL.ObjectProperty):
            if (prop, RDFS.domain, None) in result:
                constraints += 1
            if (prop, RDFS.range, None) in result:
                constraints += 1
        
        self.stats["step4_constraints"] = constraints
        return result
    
    def _step5_evidence_removal(self, g: Graph) -> Graph:
        """Step 5: Evidence Removal - 순수 OWL만 유지"""
        result = Graph()
        
        evidence_ns = str(EVIDENCE)
        prov_ns = str(PROV)
        
        removed = 0
        for s, p, o in g:
            # Evidence 관련 트리플 제외
            if str(p).startswith(evidence_ns):
                removed += 1
                continue
            if str(p).startswith(prov_ns):
                removed += 1
                continue
            
            # RDF Statement (reification) 제외
            if p == RDF.type and o == RDF.Statement:
                removed += 1
                continue
            if p in [RDF.subject, RDF.predicate, RDF.object]:
                if isinstance(s, BNode):
                    removed += 1
                    continue
            
            result.add((s, p, o))
        
        self.stats["step5_evidence_removed"] = removed
        
        # 네임스페이스 바인딩
        result.bind("owl", OWL)
        result.bind("rdfs", RDFS)
        result.bind("skos", SKOS)
        
        return result
    
    def _step6_reasoner_validation(self, g: Graph) -> dict:
        """Step 6: Reasoner Validation"""
        validation = {
            "consistent": True,
            "inferred_triples": 0,
            "errors": [],
        }
        
        try:
            # owlrl 사용 시도
            import owlrl
            
            # RDFS + OWL RL 추론
            owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
            validation["inferred_triples"] = len(g) - self.stats["output_triples"]
            
            # Post-reasoning cleanup: Remove generic OWL vocabulary triples
            # that are auto-generated by the reasoner
            from rdflib.namespace import OWL, RDFS
            
            triples_to_remove = []
            # Generic classes that should be removed when they appear as SUBJECT
            # Do NOT include OWL.Class here - it's used as object in class definitions (X a owl:Class)
            generic_subject_classes = {OWL.Thing, OWL.Nothing, RDFS.Resource}
            
            for s, p, o in g:
                # Remove triples where subject IS a generic OWL class (e.g., owl:Thing rdfs:subClassOf owl:Thing)
                if s in generic_subject_classes:
                    triples_to_remove.append((s, p, o))
                # Remove triples pointing TO owl:Thing (e.g., X subClassOf owl:Thing)
                elif o == OWL.Thing:
                    triples_to_remove.append((s, p, o))
            
            for triple in triples_to_remove:
                g.remove(triple)
            
            print(f"[OntologyPromoter] Removed {len(triples_to_remove)} generic OWL triples")
            
        except ImportError:
            validation["errors"].append("owlrl 패키지 없음 - Reasoner 검증 생략")
        except Exception as e:
            validation["consistent"] = False
            validation["errors"].append(str(e))
        
        return validation
    
    def _export_schema_snapshot(self, g: Graph, path: Path) -> None:
        """스키마 스냅샷 저장 (LLM 생성 스키마만)"""
        schema = Graph()
        
        # Only export LLM-generated classes (from self.explicit_classes)
        explicit_classes = getattr(self, 'explicit_classes', set())
        explicit_props = getattr(self, 'explicit_props', set())
        
        # Add class definitions
        for cls in explicit_classes:
            schema.add((cls, RDF.type, OWL.Class))
            # Add labels if exist
            for s, p, o in g.triples((cls, None, None)):
                if p in [RDFS.label, RDFS.comment]:
                    schema.add((s, p, o))
        
        # Add property definitions with domain/range
        for prop in explicit_props:
            for s, p, o in g.triples((prop, None, None)):
                schema.add((s, p, o))
        
        schema.bind("owl", OWL)
        schema.bind("rdfs", RDFS)
        schema.serialize(path, format="turtle")
        
        print(f"[OntologyPromoter] Exported schema snapshot: {len(explicit_classes)} classes, {len(explicit_props)} properties")
        print(f"[OntologyPromoter] Exported schema snapshot: {len(explicit_classes)} classes, {len(explicit_props)} properties")
    
    def _export_instance_types(self, g: Graph, path: Path) -> None:
        """인스턴스 타입 정보 저장 (ABox)"""
        abox = Graph()
        
        explicit_classes = getattr(self, 'explicit_classes', set())
        
        # Collect instance types for explicit classes only
        count = 0
        for cls in explicit_classes:
            for inst in g.subjects(RDF.type, cls):
                abox.add((inst, RDF.type, cls))
                count += 1
                
        abox.bind("owl", OWL)
        abox.bind("rdfs", RDFS)
        abox.serialize(path, format="turtle")
        
        print(f"[OntologyPromoter] Exported instance types: {count} type assignments")
    def _generate_report(self, result: dict, path: Path) -> None:
        """Promotion Report 생성"""
        stats = result["stats"]
        validation = result["validation"]
        
        report = f"""# Ontology Promotion Report

## 버전
- **Version**: {result['version']}
- **생성일**: {datetime.now().isoformat()}

## 통계

| 단계 | 결과 |
|------|------|
| 입력 트리플 | {stats['input_triples']} |
| Step 1 후보 | {stats['step1_candidates']} |
| Step 2 클래스 | {stats['step2_classes']} |
| Step 2 속성 | {stats['step2_properties']} |
| Step 3 cycle 제거 | {stats['step3_cycles_removed']} |
| Step 4 제약 | {stats['step4_constraints']} |
| Step 5 evidence 제거 | {stats['step5_evidence_removed']} |
| 출력 트리플 | {stats['output_triples']} |

## Reasoner 검증

| 항목 | 결과 |
|------|------|
| Consistent | {'✅' if validation['consistent'] else '❌'} |
| 추론 트리플 | {validation['inferred_triples']} |
| 에러 | {', '.join(validation['errors']) or '없음'} |

## 산출물

- `{result.get('ontology_path', 'ontology.owl')}`
- `{result.get('schema_path', 'schema_snapshot.ttl')}`
"""
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)
