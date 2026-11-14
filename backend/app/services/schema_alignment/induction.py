"""그래프 → 스키마 유도 (승격 S2) — docs/design-graph-promotion.md §3(a)

텍스트(LLM 추출) 그래프에서 스키마를 유도해 **스키마 정렬 제안**으로 만든다.
새 메커니즘을 만들지 않고 제안 → 수락(규칙) → 리플레이(ABox 재구성)를 재사용한다.

  1. 프로파일: 문서 그래프(urn:doc:*)의 관계 트리플만 (meta·reification·inverse 제외)
  2. LLM 1회: 레코드 클래스와 멤버, 엔티티 병합, 속성 동의어 묶음(대표는 기존 predicate 중 선택),
     값 동의어 묶음. 속성·클래스 이름을 새로 지어 데이터와 URI 가 갈라지지 않게 한다.
  3. 검증: 응답의 엔티티·predicate·값이 프로파일에 실재하는 것만 채택
  4. 제안 생성: kind = class | entity | key | value  (evidence.run_id 로 묶음)
  5. 적용(apply): 제안 일괄 수락 → 규칙 → TBox(rag.local URI) → 텍스트 문서 리플레이
"""

import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.retrieval.entity_linking import _compact

logger = logging.getLogger(__name__)

REL_NS = "http://rag.local/rel/"
CLASS_NS = "http://rag.local/class/"
MAX_PREDICATES = 150
MAX_ENTITIES = 200


def _local(uri: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(uri.rsplit("/", 1)[-1])


def profile_graph(kb_id: str) -> Dict[str, Any]:
    """문서 그래프의 관계 트리플 프로파일 (라벨 기준)."""
    from app.core.fuseki import fuseki_client
    q = """SELECT ?s ?p ?o ?sl ?ol WHERE {
      GRAPH ?g { ?s ?p ?o
        OPTIONAL { ?s <http://www.w3.org/2000/01/rdf-schema#label> ?sl }
        OPTIONAL { ?o <http://www.w3.org/2000/01/rdf-schema#label> ?ol } }
      FILTER(STRSTARTS(STR(?g), "urn:doc:"))
      FILTER(STRSTARTS(STR(?p), "http://rag.local/rel/"))
      FILTER(!CONTAINS(STR(?p), "/inverse_"))
    } LIMIT 20000"""
    rows = fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", [])
    triples = []
    for b in rows:
        s, p, o = b["s"]["value"], b["p"]["value"], b["o"]["value"]
        sl = (b.get("sl") or {}).get("value") or _local(s)
        ol = (b.get("ol") or {}).get("value") or (_local(o) if o.startswith("http") else o)
        triples.append({"s": sl.strip(), "p": _local(p), "o": ol.strip()})
    pred_count = Counter(t["p"] for t in triples)
    pred_examples: Dict[str, List[str]] = defaultdict(list)
    subj_preds: Dict[str, Counter] = defaultdict(Counter)
    obj_count = Counter()
    for t in triples:
        if len(pred_examples[t["p"]]) < 3:
            pred_examples[t["p"]].append(f"{t['s'][:30]} → {t['o'][:40]}")
        subj_preds[t["s"]][t["p"]] += 1
        obj_count[t["o"]] += 1
    return {"triples": triples, "pred_count": pred_count, "pred_examples": pred_examples,
            "subj_preds": subj_preds, "obj_count": obj_count}


def build_induction_messages(prof: Dict[str, Any]) -> List[Dict[str, str]]:
    preds = prof["pred_count"].most_common(MAX_PREDICATES)
    pred_lines = [f"- {p} ({c}): {' / '.join(prof['pred_examples'][p])}" for p, c in preds]
    subs = sorted(prof["subj_preds"].items(), key=lambda kv: -sum(kv[1].values()))[:MAX_ENTITIES]
    ent_lines = [f"- {s} (관계 {sum(c.values())}: {', '.join(p for p, _ in c.most_common(4))})" for s, c in subs]
    vals = [o for o, c in prof["obj_count"].most_common(300) if len(o) <= 20]
    user = f"""아래는 자연어 문서에서 LLM 이 추출한 지식 그래프의 프로파일이다. 이 그래프를 온톨로지로 승격하려 한다.

[관계(predicate) 이름 (건수): 예시 주어 → 목적어]
{chr(10).join(pred_lines)}

[주어 엔티티 (관계 수: 주요 관계)]
{chr(10).join(ent_lines)}

[짧은 목적어 값들]
{', '.join(vals)}

다음을 JSON 으로 출력하라.
1. classes: 핵심 레코드 클래스. 이름은 영어 UpperCamelCase, members 는 위 주어 엔티티 이름 그대로.
   같은 종류의 주된 대상(예: 문서들이 각각 설명하는 대상)을 하나의 클래스로 묶고, 부수 개념(품질 속성 등)은
   필요할 때만 별도 클래스로. 한 엔티티는 한 클래스에만.
2. entity_merges: 같은 대상을 다르게 적은 엔티티 이름 묶음 {{"canonical": 대표 이름, "aliases": [다른 표기]}}.
   대표와 별칭 모두 위 목록(주어 또는 값)에 있는 이름만.
3. properties: 같은 의미의 관계 묶음 {{"name": 대표, "members": [같은 의미 관계들], "domain": 클래스명}}.
   name 은 반드시 members 중 하나(가장 명확한 것) — 새 이름을 짓지 마라. 의미가 다르면 묶지 마라.
4. value_groups: 같은 뜻의 다른 표기 값 {{"canonical": 대표, "aliases": [...]}} (예: medium ↔ 중간 ↔ 보통).
   대표와 별칭 모두 위 값 목록에 있는 것만.
JSON 만: {{"classes": [...], "entity_merges": [...], "properties": [...], "value_groups": [...]}}"""
    return [
        {"role": "system", "content": "You induce an ontology schema from a noisy knowledge graph. Use only names that appear in the input. Output JSON only."},
        {"role": "user", "content": user},
    ]


def validate_induction(data: Optional[Dict[str, Any]], prof: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 응답에서 프로파일에 실재하는 이름만 채택."""
    if not data:
        return {"classes": [], "entity_merges": [], "properties": [], "value_groups": [], "dropped": ["응답 해석 불가"]}
    names = {_compact(x): x for x in list(prof["subj_preds"]) + list(prof["obj_count"])}
    preds = {_compact(p): p for p in prof["pred_count"]}
    dropped: List[str] = []

    def ent(x):
        r = names.get(_compact(str(x)))
        if r is None:
            dropped.append(f"엔티티 '{x}'")
        return r

    out_classes, assigned = [], set()
    for c in data.get("classes") or []:
        name = "".join(w[:1].upper() + w[1:] for w in str(c.get("name") or "").replace("_", " ").split())
        if not name:
            continue
        members = []
        for m in c.get("members") or []:
            e = ent(m)
            if e and e not in assigned:
                members.append(e)
                assigned.add(e)
        if members:
            out_classes.append({"name": name, "description": str(c.get("description") or "")[:200], "members": members})

    merges = []
    for m in data.get("entity_merges") or []:
        canon = ent(m.get("canonical"))
        aliases = [a for a in (ent(x) for x in m.get("aliases") or []) if a and a != canon]
        if canon and aliases:
            merges.append({"canonical": canon, "aliases": aliases})

    props = []
    for p in data.get("properties") or []:
        members = [preds[_compact(x)] for x in p.get("members") or [] if _compact(x) in preds]
        rep = preds.get(_compact(str(p.get("name"))))
        if rep is None:
            dropped.append(f"속성 대표 '{p.get('name')}'(목록에 없음)")
            continue
        if rep not in members:
            members.insert(0, rep)
        props.append({"name": rep, "members": list(dict.fromkeys(members)), "domain": str(p.get("domain") or "")})

    vgroups = []
    for v in data.get("value_groups") or []:
        canon = ent(v.get("canonical"))
        aliases = [a for a in (ent(x) for x in v.get("aliases") or []) if a and a != canon]
        if canon and aliases:
            vgroups.append({"canonical": canon, "aliases": aliases})
    return {"classes": out_classes, "entity_merges": merges, "properties": props, "value_groups": vgroups,
            "dropped": dropped[:30]}


async def run_induction(kb_id: str, llm_model_config: Dict[str, Any]) -> Dict[str, Any]:
    """유도 실행 → 제안 생성. 반환: {run_id, summary, proposals}"""
    from app.core.llm import achat, no_thinking_extra_body
    from app.core.models_resolver import resolve_model_config
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingProposal
    from app.services.retrieval.relation_targeting import parse_json_loose

    prof = profile_graph(kb_id)
    if not prof["triples"]:
        raise ValueError("문서 그래프에 관계 트리플이 없습니다.")
    cfg = await resolve_model_config(llm_model_config)
    content = await achat(cfg, build_induction_messages(prof), model=cfg.get("model"),
                          response_format={"type": "json_object"},
                          extra_body=no_thinking_extra_body(cfg.get("model")), timeout=600)
    result = validate_induction(parse_json_loose(content), prof)
    run_id = uuid.uuid4().hex[:12]

    # 이전 유도 초안(대기 중) 정리
    for old in await SchemaMappingProposal.find(SchemaMappingProposal.kb_id == kb_id,
                                                SchemaMappingProposal.status == "pending").to_list():
        if (old.evidence or {}).get("run_id"):
            old.status = "superseded"
            await old.save()

    merge_to = {}
    for m in result["entity_merges"]:
        for a in m["aliases"]:
            merge_to[a] = m["canonical"]

    async def add(kind, source, target, extra):
        await SchemaMappingProposal(kb_id=kb_id, kind=kind, source=source, target=target, basis="llm",
                                    evidence={"run_id": run_id, "origin": "promotion", **extra}).insert()

    n = Counter()
    for m in result["entity_merges"]:
        for a in m["aliases"]:
            await add("entity", a, m["canonical"], {})
            n["entity"] += 1
    for c in result["classes"]:
        for e in dict.fromkeys(merge_to.get(x, x) for x in c["members"]):
            await add("class", e, c["name"], {"description": c["description"]})
            n["class"] += 1
    for p in result["properties"]:
        for mbr in p["members"]:
            if mbr != p["name"]:
                await add("key", mbr, p["name"], {"domain": p["domain"]})
                n["key"] += 1
    for v in result["value_groups"]:
        for a in v["aliases"]:
            await add("value", a, v["canonical"], {})
            n["value"] += 1

    kb = await KnowledgeBase.get(kb_id)
    meta = dict(kb.promotion_metadata or {})
    meta["induction"] = {"run_id": run_id, "at": datetime.utcnow().isoformat(), "model": cfg.get("model"),
                         "classes": [{"name": c["name"], "description": c["description"], "members": len(c["members"])}
                                     for c in result["classes"]],
                         "properties": [{"name": p["name"], "members": p["members"], "domain": p["domain"]}
                                        for p in result["properties"]],
                         "dropped": result["dropped"],
                         "profile": {"triples": len(prof["triples"]), "predicates": len(prof["pred_count"]),
                                     "subjects": len(prof["subj_preds"])}}
    kb.promotion_metadata = meta
    kb.schema_source = "induced"
    kb.schema_status = "draft"
    await kb.save()
    return {"run_id": run_id, "proposals": dict(n), "summary": meta["induction"]}


def build_tbox_turtle(classes: List[Dict[str, Any]], properties: List[Dict[str, Any]]) -> str:
    """데이터와 같은 rag.local URI 로 TBox (클래스, 속성 domain, 별칭 altLabel)."""
    import re as _re

    def uri_part(x: str) -> str:
        return _re.sub(r"[^0-9A-Za-z가-힣_]", "_", x.strip())

    def lit(x: str) -> str:
        return '"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
             "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .", ""]
    for c in classes:
        lines.append(f"<{CLASS_NS}{uri_part(c['name'])}> a owl:Class ; rdfs:label {lit(c['name'])}"
                     + (f" ; rdfs:comment {lit(c['description'])}" if c.get("description") else "") + " .")
    for p in properties:
        parts = [f"<{REL_NS}{uri_part(p['name'])}> a owl:ObjectProperty", f"rdfs:label {lit(p['name'])}"]
        if p.get("domain"):
            parts.append(f"rdfs:domain <{CLASS_NS}{uri_part(p['domain'])}>")
        for a in p.get("members") or []:
            if a != p["name"]:
                parts.append(f"skos:altLabel {lit(a)}")
        lines.append(" ; ".join(parts) + " .")
    return "\n".join(lines) + "\n"


async def apply_induction(kb_id: str, run_id: str) -> Dict[str, Any]:
    """초안 일괄 수락 → 규칙 → TBox 업로드 → 텍스트 문서 리플레이."""
    import requests
    from app.core.fuseki import fuseki_client
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingProposal
    from app.services.schema_alignment.service import (
        _is_structured_name, accept_proposal, replay_documents)
    from app.models.document import Document

    props = [p for p in await SchemaMappingProposal.find(
        SchemaMappingProposal.kb_id == kb_id, SchemaMappingProposal.status == "pending").to_list()
        if (p.evidence or {}).get("run_id") == run_id]
    accepted = 0
    for p in props:
        await accept_proposal(kb_id, str(p.id), renormalize=False)
        accepted += 1

    kb = await KnowledgeBase.get(kb_id)
    ind = (kb.promotion_metadata or {}).get("induction") or {}
    class_members = Counter(p.target for p in props if p.kind == "class")
    classes = [{"name": c["name"], "description": c.get("description", "")} for c in ind.get("classes", [])]
    properties = ind.get("properties", [])
    ttl = build_tbox_turtle(classes, properties)
    graph_uri = f"urn:ontology:{kb_id}"
    fuseki_client.drop_graph(kb_id, graph_uri)
    url = f"{fuseki_client._get_dataset_url(kb_id)}/data?graph={graph_uri}"
    resp = requests.post(url, data=ttl.encode("utf-8"), headers={"Content-Type": "text/turtle"},
                         auth=fuseki_client.auth, timeout=60)
    tbox_ok = resp.status_code in (200, 201, 204)

    meta = dict(kb.promotion_metadata or {})
    meta["schema_info"] = {
        "classes": {f"{CLASS_NS}{c['name']}": {"label": c["name"], "description": c.get("description", ""),
                                               "count": class_members.get(c["name"], 0)} for c in classes},
        "properties": [f"{REL_NS}{p['name']}" for p in properties],
    }
    meta["promoted_at"] = datetime.utcnow().isoformat()
    meta["source"] = "induced"
    kb.promotion_metadata = meta
    kb.is_promoted = True
    kb.schema_source = "induced"
    kb.schema_status = "active"
    await kb.save()

    text_ids = [str(d.id) for d in await Document.find(Document.kb_id == kb_id).to_list()
                if not _is_structured_name(d.filename)]
    replay = await replay_documents(kb_id, text_ids)
    return {"accepted": accepted, "tbox_uploaded": tbox_ok, "classes": len(classes),
            "properties": len(properties), "replayed": len(replay["replayed"])}
