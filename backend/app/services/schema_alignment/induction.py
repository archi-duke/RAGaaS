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
MAX_OBJ_ENTITIES = 200
PROFILE_LIMIT = 20000
OBJ_EXAMPLES = 8


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
    } ORDER BY ?s ?p ?o LIMIT %d""" % PROFILE_LIMIT
    rows = fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", [])
    triples = []
    for b in rows:
        s, p, o = b["s"]["value"], b["p"]["value"], b["o"]["value"]
        sl = (b.get("sl") or {}).get("value") or _local(s)
        ol = (b.get("ol") or {}).get("value") or (_local(o) if o.startswith("http") else o)
        triples.append({"s": sl.strip(), "p": _local(p), "o": ol.strip(), "o_entity": b["o"].get("type") == "uri"})
    pred_count = Counter(t["p"] for t in triples)
    pred_examples: Dict[str, List[str]] = defaultdict(list)
    subj_preds: Dict[str, Counter] = defaultdict(Counter)
    obj_count = Counter()
    for t in triples:
        if len(pred_examples[t["p"]]) < 3:
            pred_examples[t["p"]].append(f"{t['s'][:30]} → {t['o'][:40]}")
        subj_preds[t["s"]][t["p"]] += 1
        obj_count[t["o"]] += 1
    # 관계별 목적어 집계 + 목적어 엔티티(유입 관계) — LLM 이 range·목적어 클래스를 판단할 근거
    from app.services.retrieval.entity_linking import is_sentence_like
    pred_objs: Dict[str, Counter] = defaultdict(Counter)
    pred_sentence: Counter = Counter()
    obj_in_preds: Dict[str, Counter] = defaultdict(Counter)
    for t in triples:
        pred_objs[t["p"]][t["o"]] += 1
        if is_sentence_like(t["o"]) or len(t["o"]) > 40:
            pred_sentence[t["p"]] += 1
        elif t["o_entity"] and t["o"] not in subj_preds:
            obj_in_preds[t["o"]][t["p"]] += 1
    return {"triples": triples, "pred_count": pred_count, "pred_examples": pred_examples,
            "subj_preds": subj_preds, "obj_count": obj_count, "pred_objs": pred_objs,
            "pred_sentence": pred_sentence, "obj_in_preds": obj_in_preds,
            "truncated": len(rows) >= PROFILE_LIMIT}


def normalize_seed(seed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """사람이 정한 시드 스키마 정규화.

    형식: {"classes": [{"name", "description"}], "properties": [{"name", "description", "domain", "range"}]}
    properties 는 dict({이름: 설명}) 도 허용. 이름은 URI 로 쓰이므로 공백을 '_' 로 바꾼다.
    """
    if not seed:
        return None
    import re as _re

    def clean(x):
        return _re.sub(r"\s+", "_", str(x or "").strip())

    classes = []
    for c in seed.get("classes") or []:
        c = {"name": c} if isinstance(c, str) else c
        name = "".join(w[:1].upper() + w[1:] for w in str(c.get("name") or "").replace("_", " ").split())
        if name:
            classes.append({"name": name, "description": str(c.get("description") or "")[:300]})
    raw_props = seed.get("properties") or []
    if isinstance(raw_props, dict):
        raw_props = [{"name": k, "description": v} for k, v in raw_props.items()]
    props = []
    for p in raw_props:
        p = {"name": p} if isinstance(p, str) else p
        name = clean(p.get("name"))
        if name:
            props.append({"name": name, "description": str(p.get("description") or "")[:300],
                          "domain": str(p.get("domain") or ""), "range": str(p.get("range") or "")})
    if not classes and not props:
        return None
    return {"classes": classes, "properties": props}


_VERB_ENDINGS = ("시켰다", "했다", "하다", "하는", "한다", "되다", "된", "함", "한")


def _stem(x: str) -> str:
    t = _compact(x)
    for e in _VERB_ENDINGS:
        if t.endswith(e) and len(t) - len(e) >= 2:
            return t[: -len(e)]
    return t


def seed_target_for(rep: str, seed_props: List[Dict[str, Any]]) -> Optional[str]:
    """LLM 이 기존 관계 이름으로 만든 묶음이 시드 속성과 어간이 같으면 그 시드 이름.

    예: '지도' → '지도교수_of', '수상' → '수상함', '일반화한' → '일반화함'. 시드 이름의 첫 토큰 어간이
    묶음 대표 어간으로 시작해야 한다 (2자 이상). 후보가 여럿이면 매핑하지 않는다 (모호).
    """
    r = _stem(rep)
    if len(r) < 2:
        return None
    hits = [sp["name"] for sp in seed_props
            if _stem(sp["name"].split("_")[0]).startswith(r) or r == _stem(sp["name"])]
    return hits[0] if len(hits) == 1 else None


def _seed_block(seed: Dict[str, Any]) -> str:
    lines = ["[시드 스키마 — 사람이 정한 핵심 어휘. 이 이름을 그대로 쓴다]", "클래스:"]
    for c in seed["classes"]:
        lines.append(f"- {c['name']}: {c['description']}")
    lines.append("속성 (이름: 정의 / domain → range):")
    for p in seed["properties"]:
        dr = f" / {p['domain'] or '?'} → {p['range'] or '?'}" if (p["domain"] or p["range"]) else ""
        lines.append(f"- {p['name']}: {p['description']}{dr}")
    return "\n".join(lines)


def build_induction_messages(prof: Dict[str, Any], seed: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    preds = prof["pred_count"].most_common(MAX_PREDICATES)
    pred_objs = prof.get("pred_objs") or {}
    pred_sentence = prof.get("pred_sentence") or Counter()

    def pred_line(p, c):
        objs = pred_objs.get(p) or Counter()
        top = ", ".join(f"{o[:24]}({n})" for o, n in objs.most_common(OBJ_EXAMPLES))
        sent = pred_sentence.get(p, 0)
        sent_txt = f", 서술형 목적어 {round(100 * sent / c)}%" if sent else ""
        return (f"- {p} ({c}건, 서로 다른 목적어 {len(objs)}{sent_txt}): {' / '.join(prof['pred_examples'][p])}"
                + (f"\n    목적어: {top}" if top else ""))
    pred_lines = [pred_line(p, c) for p, c in preds]
    obj_ents = sorted((prof.get("obj_in_preds") or {}).items(), key=lambda kv: -sum(kv[1].values()))[:MAX_OBJ_ENTITIES]
    obj_lines = [f"- {o} (유입 {sum(c.values())}: {', '.join(p for p, _ in c.most_common(3))})" for o, c in obj_ents]
    subs = sorted(prof["subj_preds"].items(), key=lambda kv: -sum(kv[1].values()))[:MAX_ENTITIES]
    ent_lines = [f"- {s} (관계 {sum(c.values())}: {', '.join(p for p, _ in c.most_common(4))})" for s, c in subs]
    vals = [o for o, c in prof["obj_count"].most_common(300) if len(o) <= 20]
    user = f"""아래는 자연어 문서에서 LLM 이 추출한 지식 그래프의 프로파일이다. 이 그래프를 온톨로지로 승격하려 한다.

[관계(predicate) 이름 (건수): 예시 주어 → 목적어]
{chr(10).join(pred_lines)}

[주어 엔티티 (관계 수: 주요 관계)]
{chr(10).join(ent_lines)}

[목적어로만 나오는 엔티티 (유입 관계 수: 주요 관계)]
{chr(10).join(obj_lines) or '(없음)'}

[짧은 목적어 값들]
{', '.join(vals)}

{{seed_text}}다음을 JSON 으로 출력하라.
1. classes: 독립적으로 존재하고 여러 번 등장하는 대상의 종류. 이름은 영어 UpperCamelCase 단수,
   description 은 한 문장 정의. members 는 위 주어 엔티티·목적어 엔티티 이름 그대로 (목적어로만 나오는 대상도 넣는다 —
   예: 여러 관계의 목적어로 나오는 품질 속성들). 한 엔티티는 한 클래스에만.
   클래스가 아닌 것: 서술 문장, 점수·수치('-3점'), 한 대상에 붙은 속성 묶음, 지시어·일반명사 조각('결과', '이 실험').
2. entity_merges: 같은 대상을 다르게 적은 엔티티 이름 묶음 {{"canonical": 대표 이름, "aliases": [다른 표기]}}.
   대표와 별칭 모두 위 목록(주어 또는 값)에 있는 이름만.
3. properties: 같은 의미의 관계 묶음 {{"name": 대표, "members": [같은 의미 관계들], "domain": 클래스명,
   "range": 클래스명 또는 "", "description": "A | 대표 | B — 한 문장 정의"}}.
   name 은 반드시 members 중 하나(가장 명확한 것) — 새 이름을 짓지 마라. 의미가 다르면 묶지 마라.
   range: 목적어 대부분이 한 클래스의 멤버면 그 클래스명. 목적어가 서술·수치·등급(high/low 등)이면 "" (값 속성).
   description 은 domain 이 주어, range 가 목적어가 되도록 방향을 지켜 쓴다 (예: "Person | 제안함 | Theory — 인물이 이론을 처음 제시함").
   부호·강도만 다른 관계 계열(예: has_positive_effect_on / has_negative_effect_on / has_strong_negative_effect_on)은
   서로 묶지 말되 같은 domain·range 를 준다.{{seed_rules}}
4. value_groups: 같은 뜻의 다른 표기 값 {{"canonical": 대표, "aliases": [...]}} (예: medium ↔ 중간 ↔ 보통).
   대표와 별칭 모두 위 값 목록에 있는 것만.
JSON 만: {{"classes": [{{"name", "description", "members"}}], "entity_merges": [...],
          "properties": [{{"name", "members", "domain", "range", "description"}}], "value_groups": [...]}}"""
    if seed:
        seed_text = _seed_block(seed) + "\n\n"
        seed_rules = """
   [시드가 있을 때] 시드 속성마다 의미가 같은 기존 관계를 members 로 모아 name 을 **반드시 시드 속성 이름**으로 한다
   (시드 이름은 위 관계 목록에 없어도 된다. 예: name "지도교수_of", members ["지도", "지도하다"]). 기존 관계가 여러 의미로 쓰이면(예: '소속' 이 소속과 지도 관계를
   섞어 담음) 그 관계는 members 에 넣지 마라 — 문맥별 구분은 재추출이 한다. 시드에 없는 관계 묶음도 기존처럼 만들어도 된다.
   classes 는 시드 클래스 이름을 우선 쓰고, 시드로 담을 수 없는 종류만 새 클래스로. 멤버는 실제 대상(고유명)만 —
   '결과', '이 실험' 같은 지시어·일반명사 조각은 어떤 클래스에도 넣지 마라."""
    else:
        seed_text, seed_rules = "", ""
    user = user.replace("{seed_text}", seed_text).replace("{seed_rules}", seed_rules)
    return [
        {"role": "system", "content": "You induce an ontology schema from a noisy knowledge graph. Use only names that appear in the input. Output JSON only."},
        {"role": "user", "content": user},
    ]


def validate_induction(data: Optional[Dict[str, Any]], prof: Dict[str, Any],
                       seed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """LLM 응답에서 프로파일에 실재하는 이름만 채택. 시드 속성 이름은 대표로 허용하고,
    시드 클래스·속성은 응답에 없어도 스키마에 포함한다 (사람이 정한 어휘)."""
    if not data:
        return {"classes": [], "entity_merges": [], "properties": [], "value_groups": [], "dropped": ["응답 해석 불가"]}
    names = {_compact(x): x for x in list(prof["subj_preds"]) + list(prof["obj_count"])}
    preds = {_compact(p): p for p in prof["pred_count"]}
    seed_props = {_compact(p["name"]): p for p in (seed or {}).get("properties", [])}
    seed_classes = {_compact(c["name"]): c for c in (seed or {}).get("classes", [])}
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
        sc = seed_classes.get(_compact(name))
        if sc:
            name = sc["name"]
        if members:
            out_classes.append({"name": name, "description": (sc or {}).get("description") or str(c.get("description") or "")[:300],
                                "members": members, "seed": bool(sc)})
    have = {_compact(c["name"]) for c in out_classes}
    for k, sc in seed_classes.items():
        if k not in have:
            out_classes.append({"name": sc["name"], "description": sc["description"], "members": [], "seed": True})

    merges = []
    for m in data.get("entity_merges") or []:
        canon = ent(m.get("canonical"))
        aliases = [a for a in (ent(x) for x in m.get("aliases") or []) if a and a != canon]
        if canon and aliases:
            merges.append({"canonical": canon, "aliases": aliases})

    class_keys = {_compact(c["name"]): c["name"] for c in out_classes}
    props, used = [], set()
    split_family: List[Tuple[str, Dict[str, Any]]] = []
    for p in data.get("properties") or []:
        members = [preds[_compact(x)] for x in p.get("members") or [] if _compact(x) in preds]
        sp = seed_props.get(_compact(str(p.get("name"))))
        if not sp and seed_props:
            # 기존 이름으로 만든 묶음이 시드 속성과 어간이 같으면 시드로 합친다
            tgt = seed_target_for(str(p.get("name")), list(seed_props.values()))
            if tgt:
                sp = seed_props[_compact(tgt)]
                members = [preds[_compact(str(p.get("name")))]] + members if _compact(str(p.get("name"))) in preds else members
        rep = sp["name"] if sp else preds.get(_compact(str(p.get("name"))))
        if rep is None:
            dropped.append(f"속성 대표 '{p.get('name')}'(목록에 없음)")
            continue
        # 한 기존 관계는 한 묶음에만 (먼저 나온 묶음 우선)
        members = [m for m in members if m not in used and m != rep]
        # 부호·강도만 다른 계열 관계(has_moderate_negative_effect_on ↔ has_negative_effect_on)는 묶지 않는다 —
        # key 규칙은 이름만 바꾸므로 묶으면 강도·부호가 그래프에서 사라진다. 프롬프트 지시만으로는 지켜지지 않아 결정적으로 막는다.
        from app.services.schema_alignment.schema_editor import family_key
        fam_split = [m for m in members if family_key(m) == family_key(rep) and _compact(m) != _compact(rep)]
        if fam_split:
            members = [m for m in members if m not in fam_split]
            dropped.append(f"계열 관계 분리: {rep} ← {', '.join(fam_split)}")
            split_family.extend((m, p) for m in fam_split)
        used.update(members)
        if not sp:
            members.insert(0, rep)
        if _compact(rep) in {_compact(x["name"]) for x in props}:
            for x in props:
                if _compact(x["name"]) == _compact(rep):
                    x["members"] = list(dict.fromkeys(x["members"] + members))
            continue
        # 비시드 range·정의는 LLM 응답에서 받는다 (range 는 채택된 클래스명일 때만). 시드 값은 덮지 않는다.
        llm_range = "".join(w[:1].upper() + w[1:] for w in str(p.get("range") or "").replace("_", " ").split())
        llm_range = class_keys.get(_compact(llm_range), "") if llm_range else ""
        props.append({"name": rep, "members": list(dict.fromkeys(([rep] if sp else []) + members)),
                      "domain": (sp or {}).get("domain") or str(p.get("domain") or ""),
                      "range": (sp or {}).get("range") or ("" if sp else llm_range),
                      "range_source": "seed" if sp and sp.get("range") else ("llm" if llm_range else ""),
                      "description": (sp or {}).get("description") or ("" if sp else str(p.get("description") or "")[:300]),
                      "seed": bool(sp)})
    # 분리한 계열 관계는 각자 속성으로 — 묶으려던 대표와 같은 domain·range (정의는 대표 정의를 이름만 바꿔)
    for m, src in split_family:
        if _compact(m) in {_compact(x["name"]) for x in props} or m in used:
            continue
        base = next((x for x in props if _compact(x["name"]) == _compact(str(src.get("name")))), {})
        desc = str(base.get("description") or "").replace(str(base.get("name") or ""), m) if base else ""
        props.append({"name": m, "members": [m], "domain": base.get("domain", ""), "range": base.get("range", ""),
                      "range_source": base.get("range_source", ""), "description": desc, "seed": False})
        used.add(m)
    have = {_compact(x["name"]) for x in props}
    for k, sp in seed_props.items():
        if k not in have:
            props.append({"name": sp["name"], "members": [sp["name"]], "domain": sp["domain"], "range": sp["range"],
                          "description": sp["description"], "seed": True})

    vgroups = []
    for v in data.get("value_groups") or []:
        canon = ent(v.get("canonical"))
        aliases = [a for a in (ent(x) for x in v.get("aliases") or []) if a and a != canon]
        if canon and aliases:
            vgroups.append({"canonical": canon, "aliases": aliases})
    return {"classes": out_classes, "entity_merges": merges, "properties": props, "value_groups": vgroups,
            "dropped": dropped[:30]}


async def run_induction(kb_id: str, llm_model_config: Dict[str, Any],
                        seed: Optional[Dict[str, Any]] = None, dry_run: bool = False) -> Dict[str, Any]:
    """유도 실행 → 제안 생성. 반환: {run_id, summary, proposals}
    seed(시드 스키마)가 있으면 그 어휘에 기존 관계를 매핑한다. 없으면 KB 에 저장된 시드를 쓴다.
    dry_run=True 면 저장·제안 없이 결과와 현재 스키마와의 차이만 돌려준다 (평가용 KB 보호)."""
    from app.core.llm import achat, no_thinking_extra_body
    from app.core.models_resolver import resolve_model_config
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingProposal
    from app.services.retrieval.relation_targeting import parse_json_loose

    kb0 = await KnowledgeBase.get(kb_id)
    seed = normalize_seed(seed) or normalize_seed((kb0.promotion_metadata or {}).get("seed"))
    prof = profile_graph(kb_id)
    if not prof["triples"]:
        raise ValueError("문서 그래프에 관계 트리플이 없습니다.")
    cfg = await resolve_model_config(llm_model_config)
    content = await achat(cfg, build_induction_messages(prof, seed), model=cfg.get("model"),
                          response_format={"type": "json_object"},
                          extra_body=no_thinking_extra_body(cfg.get("model")), timeout=600)
    result = validate_induction(parse_json_loose(content), prof, seed)
    run_id = uuid.uuid4().hex[:12]
    if dry_run:
        cur = (kb0.promotion_metadata or {}).get("induction") or {}
        cur_p = {x["name"]: x for x in cur.get("properties") or []}
        changes = []
        for p in result["properties"]:
            o = cur_p.get(p["name"])
            if not o:
                changes.append({"property": p["name"], "change": "추가", "seed": p.get("seed")})
            else:
                for k in ("domain", "range"):
                    if (o.get(k) or "") != (p.get(k) or ""):
                        changes.append({"property": p["name"], "change": k, "before": o.get(k), "after": p.get(k),
                                        "seed": p.get("seed")})
        for name in set(cur_p) - {p["name"] for p in result["properties"]}:
            changes.append({"property": name, "change": "삭제"})
        return {"dry_run": True, "run_id": run_id, "result": result, "changes": changes,
                "profile": {"triples": len(prof["triples"]), "truncated": prof.get("truncated")}}

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
                await add("key", mbr, p["name"], {"domain": p["domain"], "seed": p.get("seed", False)})
                n["key"] += 1
    for v in result["value_groups"]:
        for a in v["aliases"]:
            await add("value", a, v["canonical"], {})
            n["value"] += 1

    kb = await KnowledgeBase.get(kb_id)
    meta = dict(kb.promotion_metadata or {})
    if seed:
        meta["seed"] = seed
    # 재유도는 사람이 편집한 스키마를 덮으므로, 지금 스키마를 편집기 이력에 남긴다 (되돌리기 가능)
    cur = meta.get("induction") or {}
    if cur.get("classes") or cur.get("properties"):
        hist = list(meta.get("schema_history") or [])
        hist.append({"version": int(meta.get("schema_version") or 1), "at": meta.get("schema_updated_at") or meta.get("promoted_at"),
                     "summary": (meta.get("schema_last_summary") or "승격 스키마") + " (재유도 전)",
                     "spec": {"classes": cur.get("classes") or [], "properties": cur.get("properties") or []}})
        meta["schema_history"] = hist[-20:]
        meta["schema_version"] = int(meta.get("schema_version") or 1) + 1
        meta["schema_last_summary"] = f"스키마 재유도 ({run_id})"
        meta["schema_updated_at"] = datetime.utcnow().isoformat()
    meta["induction"] = {"run_id": run_id, "at": datetime.utcnow().isoformat(), "model": cfg.get("model"),
                         "classes": [{"name": c["name"], "description": c["description"], "members": len(c["members"]),
                                      "seed": c.get("seed", False)} for c in result["classes"]],
                         "properties": [{"name": p["name"], "members": p["members"], "domain": p["domain"],
                                         "range": p.get("range", ""), "description": p.get("description", ""),
                                         "range_source": p.get("range_source", ""),
                                         "seed": p.get("seed", False)} for p in result["properties"]],
                         "seeded": bool(seed),
                         "dropped": result["dropped"],
                         "profile": {"triples": len(prof["triples"]), "predicates": len(prof["pred_count"]),
                                     "subjects": len(prof["subj_preds"]), "truncated": prof.get("truncated", False)}}
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
        if p.get("range") and uri_part(p["range"]) in {uri_part(c["name"]) for c in classes}:
            parts.append(f"rdfs:range <{CLASS_NS}{uri_part(p['range'])}>")
        if p.get("description"):
            parts.append(f"rdfs:comment {lit(p['description'])}")
        for a in p.get("members") or []:
            if a != p["name"]:
                parts.append(f"skos:altLabel {lit(a)}")
        lines.append(" ; ".join(parts) + " .")
    return "\n".join(lines) + "\n"


async def apply_induction(kb_id: str, run_id: str, reextract: bool = False,
                          reextract_model: str = "ingest") -> Dict[str, Any]:
    """초안 일괄 수락 → 규칙 → TBox 업로드 → 텍스트 문서 리플레이 → (옵션) 스키마 기준 재추출 시작."""
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
    # 재유도: 같은 대상(엔티티·술어)에 대한 이전 규칙은 이번 초안으로 대체 — 규칙이 중복으로 쌓여
    # 적용 순서에 따라 결과가 달라지지 않게 (사람이 편집기로 만든 규칙은 남긴다)
    from app.models.schema_mapping import SchemaMappingRule
    superseded = 0
    for p in props:
        field = "source_path" if p.kind == "key" else "source_value"
        rtype = p.kind if p.kind in ("key", "entity", "class") else "value"
        for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == rtype,
                                              SchemaMappingRule.status == "active").to_list():
            if getattr(r, field) == p.source and not str(r.origin or "").startswith("schema_editor"):
                r.status = "disabled"
                await r.save()
                superseded += 1
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
    replay_errors = [r for r in replay["replayed"] if r.get("error")]
    result = {"accepted": accepted, "superseded_rules": superseded, "tbox_uploaded": tbox_ok, "classes": len(classes),
              "properties": len(properties), "replayed": len(replay["replayed"]),
              "replay_errors": len(replay_errors)}

    # range 데이터 검증 — 리플레이 뒤에 (별칭→대표·엔티티 병합이 반영된 그래프 기준). 시드·사람 range 는 지킨다.
    if not replay_errors:
        from app.services.schema_alignment.schema_editor import range_check, upload_tbox
        chk = await range_check(kb_id, properties)
        changed = 0
        for p in properties:
            c = chk.get(p["name"])
            if not c:
                continue
            p["range_check"] = {k: c[k] for k in ("n", "data_class", "data_ratio", "declared_ratio", "decision")}
            if c["range"] != (p.get("range") or ""):
                p["range"] = c["range"]
                p["range_source"] = "data" if c["range"] else ""
                changed += 1
        kb = await KnowledgeBase.get(kb_id)
        meta = dict(kb.promotion_metadata or {})
        ind2 = dict(meta.get("induction") or {})
        ind2["properties"] = properties
        meta["induction"] = ind2
        kb.promotion_metadata = meta
        await kb.save()
        if changed:
            result["tbox_uploaded"] = await upload_tbox(kb_id, classes, properties)
        result["range_changed"] = changed
        result["range_decisions"] = Counter(c["decision"] for c in chk.values())
    if reextract and text_ids:
        from app.services.schema_alignment import reextract as rx
        try:
            result["reextract"] = await rx.start(kb_id, text_ids, reextract_model)
        except ValueError as e:
            result["reextract"] = {"error": str(e)}
    return result
