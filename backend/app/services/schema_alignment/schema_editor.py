"""스키마 편집기 (사람 검수 1단계) — docs/design-schema-editor.md

승격(유도·시드)으로 확정된 텍스트 KB 스키마(promotion_metadata.induction)를 사람이 직접 고친다.
- 편집 대상: 클래스(이름·설명), 속성(이름·정의·domain·range·별칭)
- 저장하면: 검증 → 이전 버전을 이력에 보관 → TBox(urn:ontology) 재생성 → 클래스 카탈로그 무효화
- 이름 변경: 속성은 key 규칙(옛 이름 → 새 이름)을, 클래스는 class 규칙의 대상 이름을 바꾼 뒤
  텍스트 문서를 리플레이해 기존 그래프에 반영한다 (LLM 비용 0, 저장된 추출 트리플 기준·멱등).
- 정의·방향(domain/range)·별칭의 의미 변경은 '스키마 기준 재추출'을 돌려야 데이터에 반영된다 (선택).
구조화(YAML/JSON) KB 는 필드 구조에서 스키마가 매번 다시 만들어지므로, 편집 내용을 '덧씌우기'
(promotion_metadata.schema_overlay)와 매핑 규칙으로 저장해 재업로드·새 문서에도 유지한다 (§7):
- 유형 이름·설명, 속성 정의·별칭 → 덧씌우기 (카탈로그·TBox 생성 때 적용)
- 속성 이름(경로) 변경 → key 규칙 + 해당 문서 재정규화
- 속성 추가·방향 변경은 불가 (데이터 구조가 YAML 필드에서 나옴)
"""

import copy
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HISTORY_MAX = 20
EDITABLE_SOURCES = ("induced", "declared")
STRUCTURED = "structured"


class SchemaEditError(ValueError):
    def __init__(self, errors: List[str], status: int = 400):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.status = status


def clean_prop_name(x: str) -> str:
    return re.sub(r"\s+", "_", str(x or "").strip())


def clean_class_name(x: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_]", "", re.sub(r"\s+", "", str(x or "").strip()))


def _norm_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """입력 정규화 — 이름 정리, 별칭 목록화, 대표 이름을 별칭 맨 앞에."""
    classes = []
    for c in spec.get("classes") or []:
        classes.append({
            "name": clean_class_name(c.get("name")),
            "description": str(c.get("description") or "").strip()[:500],
            **({"renamed_from": clean_class_name(c["renamed_from"])} if c.get("renamed_from") else {}),
        })
    props = []
    for p in spec.get("properties") or []:
        name = clean_prop_name(p.get("name"))
        aliases = p.get("aliases", p.get("members")) or []
        if isinstance(aliases, str):
            aliases = re.split(r"[,\n]", aliases)
        al = []
        for a in [name] + [clean_prop_name(a) for a in aliases]:
            if a and a not in al:
                al.append(a)
        item = {"name": name, "description": str(p.get("description") or "").strip()[:500],
                "domain": clean_class_name(p.get("domain")), "range": str(p.get("range") or "").strip(),
                "members": al}
        if p.get("seed"):
            item["seed"] = True
        if p.get("renamed_from"):
            item["renamed_from"] = clean_prop_name(p["renamed_from"])
        props.append(item)
    return {"classes": classes, "properties": props}


def validate_spec(spec: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """(오류, 경고). 오류가 있으면 저장하지 않는다."""
    errors, warnings = [], []
    cnames = [c["name"] for c in spec["classes"]]
    for c in spec["classes"]:
        if not c["name"]:
            errors.append("이름 없는 클래스가 있습니다")
    dup = {n for n in cnames if n and cnames.count(n) > 1}
    if dup:
        errors.append(f"클래스 이름 중복: {', '.join(sorted(dup))}")
    pnames = [p["name"] for p in spec["properties"]]
    for p in spec["properties"]:
        if not p["name"]:
            errors.append("이름 없는 속성이 있습니다")
        if p["domain"] and p["domain"] not in cnames:
            errors.append(f"속성 '{p['name']}' 의 domain '{p['domain']}' 이 클래스 목록에 없습니다")
        if p["range"] and clean_class_name(p["range"]) not in cnames and p["range"] == clean_class_name(p["range"]) \
                and p["range"][:1].isupper():
            warnings.append(f"속성 '{p['name']}' 의 range '{p['range']}' 는 클래스가 아니라 값(리터럴)으로 취급됩니다")
        if not p["description"]:
            warnings.append(f"속성 '{p['name']}' 에 정의가 없습니다 — 재추출 정확도가 떨어질 수 있습니다")
    dup = {n for n in pnames if n and pnames.count(n) > 1}
    if dup:
        errors.append(f"속성 이름 중복: {', '.join(sorted(dup))}")
    owner: Dict[str, str] = {}
    for p in spec["properties"]:
        for a in p["members"]:
            if a in owner and owner[a] != p["name"]:
                errors.append(f"별칭 '{a}' 이 두 속성('{owner[a]}', '{p['name']}')에 들어 있습니다")
            owner.setdefault(a, p["name"])
    return errors, warnings


def diff_spec(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """변경 요약 — 이름 변경은 renamed_from 으로만 인정 (같은 이름 삭제+추가와 구별)."""
    def names(xs):
        return {x["name"] for x in xs}

    oc, nc = names(old.get("classes") or []), names(new["classes"])
    op, np_ = names(old.get("properties") or []), names(new["properties"])
    c_ren = {c["renamed_from"]: c["name"] for c in new["classes"]
             if c.get("renamed_from") and c["renamed_from"] in oc and c["renamed_from"] != c["name"]}
    p_ren = {p["renamed_from"]: p["name"] for p in new["properties"]
             if p.get("renamed_from") and p["renamed_from"] in op and p["renamed_from"] != p["name"]}
    old_p = {p["name"]: p for p in old.get("properties") or []}
    changed = []
    for p in new["properties"]:
        o = old_p.get(p.get("renamed_from") or p["name"])
        if o and any((o.get(k) or "") != (p.get(k) or "") for k in ("description", "domain", "range")):
            changed.append(p["name"])
        elif o and sorted(o.get("members") or []) != sorted(p["members"]) and not p.get("renamed_from"):
            changed.append(p["name"])
    return {
        "classes_added": sorted(nc - oc - set(c_ren.values())),
        "classes_removed": sorted(oc - nc - set(c_ren)),
        "classes_renamed": c_ren,
        "properties_added": sorted(np_ - op - set(p_ren.values())),
        "properties_removed": sorted(op - np_ - set(p_ren)),
        "properties_renamed": p_ren,
        "properties_changed": sorted(set(changed)),
    }


def _strip(spec: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(spec)
    for x in out["classes"] + out["properties"]:
        x.pop("renamed_from", None)
    return out


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

def _usage_counts(kb_id: str) -> Dict[str, int]:
    """속성별 문서 그래프 트리플 수 (rel 네임스페이스)."""
    from app.core.fuseki import fuseki_client
    from app.services.schema_alignment.induction import REL_NS
    q = f"""SELECT ?p (COUNT(*) AS ?n) WHERE {{ GRAPH ?g {{ ?s ?p ?o }}
            FILTER(STRSTARTS(STR(?g), "urn:doc:") && STRSTARTS(STR(?p), "{REL_NS}")) }} GROUP BY ?p"""
    out = {}
    try:
        for b in fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", []):
            out[b["p"]["value"][len(REL_NS):]] = int(b["n"]["value"])
    except Exception:
        pass
    return out


RANGE_MIN_RATIO = 0.6       # 데이터가 한 클래스를 이 비율 이상 지지하면 데이터가 이긴다
RANGE_KEEP_RATIO = 0.3      # LLM·사람이 선언한 range 의 일치율이 이 미만이면 근거 없음으로 비운다 (사람 선언 제외)
RANGE_MIN_N = 5             # 서로 다른 목적어(서술·수치 제외)가 이보다 적으면 판정하지 않는다
_NUMERIC_RE = re.compile(r"^[+\-−]?\d")
_FAMILY_TOKENS = re.compile(
    r"(^|_)(very|strong|strongly|moderate|moderately|weak|weakly|slight|slightly|positive|negative|"
    r"긍정|부정|강한|약한|중간|매우)(?=_|$)")


def family_key(name: str) -> str:
    """부호·강도만 다른 관계 계열의 키 (has_moderate_negative_effect_on → has_effect_on)."""
    k = _FAMILY_TOKENS.sub(r"\1", str(name or ""))
    k = re.sub(r"_+", "_", k).strip("_")
    return k or str(name)


def _usable_object(label: str) -> bool:
    from app.services.retrieval.entity_linking import _compact, is_sentence_like
    t = (label or "").strip()
    return bool(t) and len(t) <= 30 and not is_sentence_like(t) and not _NUMERIC_RE.match(t) and bool(_compact(t))


async def _class_index(kb_id: str) -> Dict[str, str]:
    from app.services.retrieval.entity_linking import _compact
    from app.services.schema_alignment.service import active_rules
    return {_compact(r.source_value): r.target_value for r in await active_rules(kb_id)
            if r.rule_type == "class" and r.source_value and r.target_value}


def _objects_of(kb_id: str, pred_names: List[str]) -> Dict[str, int]:
    """술어들(대표 + 별칭)의 목적어 라벨 → 등장 수 (문서 그래프)."""
    from app.core.fuseki import fuseki_client
    from app.services.schema_alignment.induction import REL_NS
    out: Dict[str, int] = {}
    for name in dict.fromkeys(pred_names):
        uri = REL_NS + re.sub(r"[^0-9A-Za-z가-힣_]", "_", name.strip())
        q = f"""SELECT ?o (SAMPLE(?l) AS ?lab) (COUNT(*) AS ?n) WHERE {{ GRAPH ?g {{ ?s <{uri}> ?o
                 OPTIONAL {{ ?o <http://www.w3.org/2000/01/rdf-schema#label> ?l }} }}
                 FILTER(STRSTARTS(STR(?g), "urn:doc:")) }} GROUP BY ?o LIMIT 2000"""
        try:
            rows = fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", [])
        except Exception:
            continue
        for b in rows:
            o = b["o"]["value"]
            lab = b.get("lab", {}).get("value") or (o.rstrip("/").rsplit("/", 1)[-1] if o.startswith("http") else o)
            out[lab] = out.get(lab, 0) + int(b["n"]["value"])
    return out


async def range_check(kb_id: str, props: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """속성별 range 데이터 검증 (docs/design-schema-editor.md §10).

    - 목적어: 대표 이름 + 별칭 술어의 목적어 합산, 서술·수치·20자 초과 제외, 서로 다른 목적어 기준
    - 부호·강도 계열(family_key 가 같은 속성 2개 이상)은 목적어를 합쳐 판정 → 같은 range
    - 판정: 데이터 최다 클래스 비율 ≥ 0.6 → 데이터 채택 (선언과 다르면 충돌 기록)
            선언 range 일치율 < 0.3 → 비움 (사람·시드 선언은 비우지 않고 경고만)
            그 사이 → 선언 유지, 멤버 누락 제안 대상
    반환: {속성: {n, data_class, data_ratio, declared, declared_ratio, decision, range, gaps:[...]}}
    """
    from app.services.retrieval.entity_linking import _compact
    cls = await _class_index(kb_id)
    objs = {p["name"]: _objects_of(kb_id, [p["name"]] + list(p.get("members") or [])) for p in props if p.get("name")}
    fam: Dict[str, List[str]] = {}
    for p in props:
        fam.setdefault(family_key(p["name"]), []).append(p["name"])
    out = {}
    for p in props:
        name = p["name"]
        peers = fam.get(family_key(name)) or [name]
        pooled: Dict[str, int] = {}
        for x in (peers if len(peers) > 1 else [name]):
            for lab, n in (objs.get(x) or {}).items():
                pooled[lab] = pooled.get(lab, 0) + n
        usable = {lab: n for lab, n in pooled.items() if _usable_object(lab)}
        counts: Dict[str, int] = {}
        for lab in usable:
            c = cls.get(_compact(lab))
            if c:
                counts[c] = counts.get(c, 0) + 1
        n = len(usable)
        declared = p.get("range") or ""
        data_class = max(counts, key=counts.get) if counts else ""
        data_ratio = round(counts.get(data_class, 0) / n, 2) if n else 0.0
        declared_ratio = round(counts.get(declared, 0) / n, 2) if n and declared else None
        source = p.get("range_source") or ("seed" if p.get("seed") else ("user" if declared else ""))
        decision, rng = "keep", declared
        if n < RANGE_MIN_N:
            decision = "insufficient"
        elif data_class and data_ratio >= RANGE_MIN_RATIO:
            if declared and declared != data_class:
                decision = "conflict" if source in ("seed", "user") else "data_override"
                rng = declared if source in ("seed", "user") else data_class
            else:
                decision, rng = ("confirmed" if declared else "data"), data_class
        elif declared and declared_ratio is not None and declared_ratio < RANGE_KEEP_RATIO:
            if source in ("seed", "user"):
                decision = "weak"          # 사람이 정한 range — 비우지 않고 멤버 누락을 먼저 의심
            else:
                decision, rng = "dropped", ""
        elif declared:
            decision = "weak" if (declared_ratio or 0) < RANGE_MIN_RATIO else "confirmed"
        target = rng or ""
        gaps = sorted(((lab, usable[lab]) for lab in usable if target and not cls.get(_compact(lab))),
                      key=lambda x: -x[1]) if target else []
        violations = sorted(((lab, cls.get(_compact(lab))) for lab in usable
                             if target and cls.get(_compact(lab)) and cls.get(_compact(lab)) != target))
        out[name] = {"n": n, "data_class": data_class, "data_ratio": data_ratio, "declared": declared,
                     "declared_ratio": declared_ratio, "decision": decision, "range": rng,
                     "family": peers if len(peers) > 1 else [],
                     "gaps": [{"name": lab, "count": c} for lab, c in gaps[:60]],
                     "violations": [{"name": lab, "class": c} for lab, c in violations[:30]]}
    return out


async def infer_ranges(kb_id: str, prop_names: List[str]) -> Dict[str, Dict[str, Any]]:
    """(호환) range 가 빈 속성의 데이터 추천: {속성: {class, ratio, n, hits}}."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    ind = ((kb.promotion_metadata or {}).get("induction") or {}) if kb else {}
    props = [p for p in ind.get("properties") or [] if p["name"] in set(prop_names)]
    chk = await range_check(kb_id, [{**p, "range": ""} for p in props])
    return {k: {"class": v["range"], "ratio": v["data_ratio"], "n": v["n"], "hits": round(v["data_ratio"] * v["n"])}
            for k, v in chk.items() if v["decision"] == "data" and v["range"]}


async def get_spec(kb_id: str) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    from app.services.schema_alignment.service import active_rules
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise SchemaEditError(["KB 없음"], 404)
    meta = kb.promotion_metadata or {}
    if kb.schema_source == STRUCTURED and kb.is_promoted:
        return await _get_structured_spec(kb)
    ind = meta.get("induction") or {}
    editable = kb.schema_source in EDITABLE_SOURCES and bool(ind.get("classes") or ind.get("properties"))
    members: Dict[str, int] = {}
    for r in await active_rules(kb_id):
        if r.rule_type == "class" and r.target_value:
            members[r.target_value] = members.get(r.target_value, 0) + 1
    usage = _usage_counts(kb_id) if editable else {}
    chk = await range_check(kb_id, ind.get("properties") or []) if editable else {}
    # 멤버 누락: range 클래스로 이어지는데 클래스가 없는 목적어 → 클래스별로 모아 사람이 체크 (§10)
    member_gaps: Dict[str, Dict[str, Dict[str, Any]]] = {}
    violations: List[Dict[str, Any]] = []
    for name, c in chk.items():
        tgt = c["range"]
        for g in c["gaps"]:
            e = member_gaps.setdefault(tgt, {}).setdefault(g["name"], {"name": g["name"], "count": 0, "via": []})
            e["count"] += g["count"]
            if name not in e["via"]:
                e["via"].append(name)
        for v in c["violations"]:
            violations.append({"property": name, "range": tgt, **v})
    classes = [{"name": c["name"], "description": c.get("description", ""), "member_count": members.get(c["name"], 0)}
               for c in ind.get("classes") or []]
    props = []
    for p in ind.get("properties") or []:
        props.append({"name": p["name"], "description": p.get("description", ""), "domain": p.get("domain", ""),
                      "range": p.get("range", ""), "aliases": [a for a in p.get("members") or [] if a != p["name"]],
                      "seed": bool(p.get("seed")), "triple_count": usage.get(p["name"], 0),
                      "range_source": p.get("range_source", ""),
                      **({"range_check": {k: chk[p["name"]][k] for k in
                                          ("n", "data_class", "data_ratio", "declared_ratio", "decision", "family")}}
                         if p["name"] in chk else {}),
                      **({"range_suggestion": {"class": chk[p["name"]]["range"], "ratio": chk[p["name"]]["data_ratio"],
                                               "n": chk[p["name"]]["n"],
                                               "hits": round(chk[p["name"]]["data_ratio"] * chk[p["name"]]["n"])}}
                         if p["name"] in chk and chk[p["name"]]["range"] and chk[p["name"]]["range"] != (p.get("range") or "")
                         else {})})
    known = {p["name"] for p in props}
    out_of_schema = sorted(((k, v) for k, v in usage.items() if k not in known), key=lambda x: -x[1])[:30]
    hist = meta.get("schema_history") or []
    return {
        "kb_id": kb_id, "editable": editable, "mode": "induced", "schema_source": kb.schema_source,
        "reason": None if editable else (
            "구조화(YAML/JSON) KB 는 필드 구조가 스키마입니다 — 스키마 정렬의 매핑 규칙으로 고치세요"
            if kb.schema_source == "structured" else "승격(스키마 유도)된 KB 만 편집할 수 있습니다"),
        "version": int(meta.get("schema_version") or 1),
        "updated_at": meta.get("schema_updated_at") or meta.get("promoted_at"),
        "classes": classes, "properties": props,
        "out_of_schema": [{"name": k, "triple_count": v} for k, v in out_of_schema],
        "member_gaps": {k: sorted(v.values(), key=lambda x: (-len(x["via"]), -x["count"]))[:80]
                        for k, v in member_gaps.items()},
        "range_violations": violations[:60],
        "history": [{"version": h["version"], "at": h.get("at"), "summary": h.get("summary")} for h in reversed(hist)],
    }


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------

async def upload_tbox(kb_id: str, classes: List[Dict[str, Any]], properties: List[Dict[str, Any]]) -> bool:
    import requests
    from app.core.fuseki import fuseki_client
    from app.services.schema_alignment.induction import build_tbox_turtle
    ttl = build_tbox_turtle([{"name": c["name"], "description": c.get("description", "")} for c in classes], properties)
    graph_uri = f"urn:ontology:{kb_id}"
    fuseki_client.drop_graph(kb_id, graph_uri)
    url = f"{fuseki_client._get_dataset_url(kb_id)}/data?graph={graph_uri}"
    resp = requests.post(url, data=ttl.encode("utf-8"), headers={"Content-Type": "text/turtle"},
                         auth=fuseki_client.auth, timeout=60)
    return resp.status_code in (200, 201, 204)


async def _apply_renames(kb_id: str, diff: Dict[str, Any]) -> int:
    """이름 변경을 규칙에 반영. 반환: 바뀐 규칙 수."""
    from app.models.schema_mapping import SchemaMappingRule
    n = 0
    for old, new in diff["properties_renamed"].items():
        # 기존 별칭 규칙(x → old)은 new 를 가리키게 (리플레이 key 매핑은 한 번만 적용되므로 체인 불가)
        for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "key",
                                              SchemaMappingRule.target_path == old).to_list():
            if r.source_path == new:
                await r.delete()   # new → old 였던 규칙은 new → new 가 되므로 지운다 (되돌리기)
            else:
                r.target_path = new
                await r.save()
            n += 1
        # new 에서 나가는 다른 규칙이 남아 있으면 새 이름이 다시 바뀌므로 끈다
        for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "key",
                                              SchemaMappingRule.source_path == new,
                                              SchemaMappingRule.status == "active").to_list():
            r.status = "disabled"
            await r.save()
            n += 1
        exists = await SchemaMappingRule.find_one(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "key",
                                                  SchemaMappingRule.source_path == old)
        if exists:
            exists.target_path, exists.status = new, "active"
            await exists.save()
        else:
            await SchemaMappingRule(kb_id=kb_id, rule_type="key", source_path=old, target_path=new,
                                    origin="schema_editor").insert()
        n += 1
    for old, new in diff["classes_renamed"].items():
        for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "class",
                                              SchemaMappingRule.target_value == old).to_list():
            r.target_value = new
            await r.save()
            n += 1
    for old in diff["classes_removed"]:
        for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "class",
                                              SchemaMappingRule.target_value == old,
                                              SchemaMappingRule.status == "active").to_list():
            r.status = "disabled"
            await r.save()
            n += 1
    return n


def _summary_text(diff: Dict[str, Any]) -> str:
    parts = []
    lab = {"classes_added": "클래스 추가", "classes_removed": "클래스 삭제", "properties_added": "속성 추가",
           "properties_removed": "속성 삭제", "properties_changed": "속성 수정"}
    for k, v in lab.items():
        if diff[k]:
            parts.append(f"{v} {', '.join(diff[k][:5])}" + (" …" if len(diff[k]) > 5 else ""))
    for k, v in (("classes_renamed", "클래스 이름"), ("properties_renamed", "속성 이름")):
        if diff[k]:
            parts.append(f"{v} " + ", ".join(f"{a}→{b}" for a, b in list(diff[k].items())[:5]))
    return " / ".join(parts) or "변경 없음"


async def save_spec(kb_id: str, spec_in: Dict[str, Any], base_version: Optional[int] = None,
                    replay: bool = True, note: str = "") -> Dict[str, Any]:
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    from app.services.schema_alignment.induction import CLASS_NS, REL_NS
    from app.services.schema_alignment.service import _is_structured_name, replay_documents

    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise SchemaEditError(["KB 없음"], 404)
    if kb.schema_source == STRUCTURED:
        return await _save_structured_spec(kb, spec_in, base_version, note)
    if kb.schema_source not in EDITABLE_SOURCES:
        raise SchemaEditError([f"편집할 수 없는 KB 입니다 (schema_source={kb.schema_source})"])
    meta = dict(kb.promotion_metadata or {})
    ind = dict(meta.get("induction") or {})
    version = int(meta.get("schema_version") or 1)
    if base_version is not None and int(base_version) != version:
        raise SchemaEditError([f"다른 곳에서 먼저 저장했습니다 (현재 버전 {version}, 편집 기준 {base_version}) — 새로 불러온 뒤 다시 편집하세요"], 409)

    spec = _norm_spec(spec_in)
    errors, warnings = validate_spec(spec)
    if errors:
        raise SchemaEditError(errors)
    old = {"classes": ind.get("classes") or [], "properties": ind.get("properties") or []}
    diff = diff_spec(old, spec)
    summary = _summary_text(diff)
    if summary == "변경 없음":
        return {"version": version, "diff": diff, "summary": summary, "warnings": warnings, "saved": False}

    # 이력: 바꾸기 전 스키마를 보관
    hist = list(meta.get("schema_history") or [])
    hist.append({"version": version, "at": meta.get("schema_updated_at") or meta.get("promoted_at"),
                 "summary": (meta.get("schema_last_summary") or "승격 초안"), "spec": old})
    meta["schema_history"] = hist[-HISTORY_MAX:]

    new = _strip(spec)
    ind["classes"], ind["properties"] = new["classes"], new["properties"]
    meta["induction"] = ind
    meta["schema_version"] = version + 1
    meta["schema_updated_at"] = datetime.utcnow().isoformat()
    meta["schema_last_summary"] = summary + (f" — {note}" if note else "")
    info = (meta.get("schema_info") or {})
    old_counts = {v.get("label"): v.get("count", 0) for v in (info.get("classes") or {}).values()}
    meta["schema_info"] = {
        "classes": {f"{CLASS_NS}{c['name']}": {"label": c["name"], "description": c.get("description", ""),
                                               "count": old_counts.get(c["name"], old_counts.get(
                                                   next((o for o, n in diff["classes_renamed"].items() if n == c["name"]), ""), 0))}
                    for c in new["classes"]},
        "properties": [f"{REL_NS}{p['name']}" for p in new["properties"]],
    }
    kb.promotion_metadata = meta

    rules_changed = await _apply_renames(kb_id, diff)
    if rules_changed:
        kb.schema_rules_version = (kb.schema_rules_version or 0) + 1
    await kb.save()

    tbox_ok = await upload_tbox(kb_id, new["classes"], new["properties"])
    FusekiBackend.invalidate_class_catalog(kb_id)

    result = {"version": version + 1, "diff": diff, "summary": summary, "warnings": warnings, "saved": True,
              "tbox_uploaded": tbox_ok, "rules_changed": rules_changed}
    if replay and rules_changed:
        text_ids = [str(d.id) for d in await Document.find(Document.kb_id == kb_id).to_list()
                    if not _is_structured_name(d.filename)]
        rp = await replay_documents(kb_id, text_ids)
        result["replayed"] = len(rp["replayed"])
        result["replay_errors"] = [r for r in rp["replayed"] if r.get("error")]
    # 의미(정의·방향·별칭) 변경은 재추출해야 데이터에 반영된다
    result["reextract_recommended"] = bool(diff["properties_changed"] or diff["properties_added"])
    return result


async def revert_to(kb_id: str, version: int) -> Dict[str, Any]:
    """이력의 특정 버전으로 되돌린다 (되돌리기도 새 버전으로 저장 — 이력이 지워지지 않음).
    이름 변경 규칙은 되돌리지 않는다: 이후 리플레이가 옛 이름으로 다시 묶이도록 대상 이름만 맞춘다."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise SchemaEditError(["KB 없음"], 404)
    meta = kb.promotion_metadata or {}
    h = next((x for x in meta.get("schema_history") or [] if int(x["version"]) == int(version)), None)
    if not h:
        raise SchemaEditError([f"이력에 버전 {version} 이 없습니다"], 404)
    if kb.schema_source == STRUCTURED:
        return await _revert_structured(kb, h)
    cur = meta.get("induction") or {}
    spec = copy.deepcopy(h["spec"])
    # 현재 이름 → 옛 이름 되돌리기를 renamed_from 으로 표시해 규칙이 따라가게 한다
    cur_names = {p["name"] for p in cur.get("properties") or []}
    old_names = {p["name"] for p in spec["properties"]}
    from app.models.schema_mapping import SchemaMappingRule
    for p in spec["properties"]:
        if p["name"] in cur_names:
            continue
        r = await SchemaMappingRule.find_one(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "key",
                                             SchemaMappingRule.source_path == p["name"],
                                             SchemaMappingRule.origin == "schema_editor")
        if r and r.target_path in cur_names and r.target_path not in old_names:
            p["renamed_from"] = r.target_path
    for p in spec["properties"]:
        p.setdefault("aliases", [a for a in p.get("members") or [] if a != p["name"]])
    return await save_spec(kb_id, spec, base_version=int(meta.get("schema_version") or 1),
                           note=f"버전 {version} 으로 되돌림")


# ---------------------------------------------------------------------------
# 구조화(YAML/JSON) KB — 덧씌우기 + 매핑 규칙 (§7)
# ---------------------------------------------------------------------------

async def _structured_catalog(kb_id: str):
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    return await FusekiBackend()._class_catalog(kb_id, lambda _m: None, {})


def _path_count(p: Dict[str, Any]) -> int:
    if p.get("member_ids"):
        return len(p["member_ids"])
    return sum(int(v.get("members") or 0) for v in p.get("values") or [])


async def _get_structured_spec(kb) -> Dict[str, Any]:
    from app.services.retrieval.relation_targeting import local_name
    kb_id = str(kb.id)
    meta = kb.promotion_metadata or {}
    kinds, catalogs = await _structured_catalog(kb_id)
    classes, props = [], []
    for k in kinds:
        classes.append({"name": k["name"], "orig": k.get("orig_name") or k["name"],
                        "description": k.get("description", ""), "member_count": len(k["members"]),
                        "examples": [local_name(m) for m in k["members"][:8]]})
        for p in catalogs.get(k["name"]) or []:
            if p.get("equiv_rep") and p["equiv_rep"] != p["key"]:
                continue
            props.append({"name": p["key"], "kind": k["name"], "type": p.get("type"),
                          "values": [str(v["label"])[:40] for v in (p.get("values") or [])[:10]],
                          "value_count": p.get("dv", 0), "description": p.get("description", ""),
                          "aliases": p.get("aliases") or [], "triple_count": _path_count(p),
                          **({"ref_kind": p["ref_kind"]} if p.get("ref_kind") else {})})
    hist = meta.get("schema_history") or []
    return {
        "kb_id": kb_id, "editable": True, "mode": "structured", "schema_source": kb.schema_source,
        "reason": None,
        "notes": ["구조화(YAML/JSON) KB: 스키마는 필드 구조에서 만들어집니다. 고친 내용은 KB 에 따로 저장돼 "
                  "다시 올리거나 새 문서를 넣어도 유지됩니다.",
                  "유형 이름·설명, 속성 정의·별칭은 바로 반영됩니다. 속성 이름(경로) 변경은 매핑 규칙으로 저장되고 "
                  "해당 문서를 재정규화합니다. 속성 추가·방향 변경은 YAML 원본에서 해야 합니다."],
        "version": int(meta.get("schema_version") or 1),
        "updated_at": meta.get("schema_updated_at") or meta.get("promoted_at"),
        "classes": classes, "properties": props, "out_of_schema": [],
        "history": [{"version": h["version"], "at": h.get("at"), "summary": h.get("summary")} for h in reversed(hist)],
    }


def _valid_path(x: str) -> bool:
    segs = [t for t in str(x or "").split(".")]
    return bool(segs) and all(re.fullmatch(r"[0-9A-Za-z가-힣_\-]+", t or "") for t in segs)


async def _save_structured_spec(kb, spec_in: Dict[str, Any], base_version: Optional[int], note: str,
                                dry_run: bool = False) -> Dict[str, Any]:
    from app.models.schema_mapping import SchemaMappingRule
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    from app.services.retrieval.relation_targeting import local_name
    from app.services.schema_alignment.service import (
        _docs_with_path, mark_structured_ontology, renormalize_documents)

    kb_id = str(kb.id)
    meta = dict(kb.promotion_metadata or {})
    version = int(meta.get("schema_version") or 1)
    if base_version is not None and int(base_version) != version:
        raise SchemaEditError([f"다른 곳에서 먼저 저장했습니다 (현재 버전 {version}, 편집 기준 {base_version}) — 새로 불러온 뒤 다시 편집하세요"], 409)
    kinds, catalogs = await _structured_catalog(kb_id)
    by_name = {k["name"]: k for k in kinds}
    cur_paths = {p["key"]: p for k in kinds for p in catalogs.get(k["name"]) or []}

    errors, warnings = [], []
    new_classes = []
    for c in spec_in.get("classes") or []:
        cur = by_name.get(c.get("renamed_from") or c.get("name")) or by_name.get(c.get("orig") or "")
        name = clean_class_name(c.get("name"))
        if not cur:
            errors.append(f"구조화 KB 에서는 유형을 새로 만들 수 없습니다: '{c.get('name')}'")
            continue
        if not name:
            errors.append("이름 없는 유형이 있습니다")
            continue
        new_classes.append({"orig": cur.get("orig_name") or cur["name"], "name": name,
                            "description": str(c.get("description") or "").strip()[:500],
                            "members": [local_name(m) for m in cur["members"][:200]]})
    names = [c["name"] for c in new_classes]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        errors.append(f"유형 이름 중복: {', '.join(sorted(dup))}")

    renames, prop_notes = {}, {}
    seen = set()
    for p in spec_in.get("properties") or []:
        name = str(p.get("name") or "").strip()
        old = str(p.get("renamed_from") or name).strip()
        if old not in cur_paths:
            errors.append(f"구조화 KB 에서는 속성을 새로 만들 수 없습니다: '{name}' (YAML 원본에 필드를 추가하세요)")
            continue
        if not _valid_path(name):
            errors.append(f"속성 경로 '{name}' 형식이 잘못됐습니다 (점으로 구분한 이름)")
            continue
        if name != old:
            if name in cur_paths:
                warnings.append(f"'{old}' → '{name}': 이미 있는 경로라 두 필드가 합쳐집니다")
            if old.split(".")[:-1] != name.split(".")[:-1]:
                warnings.append(f"'{old}' → '{name}': 상위 경로가 바뀌어 필드가 다른 위치로 옮겨집니다")
            renames[old] = name
        if name in seen:
            errors.append(f"속성 경로 중복: {name}")
        seen.add(name)
        aliases = p.get("aliases") or []
        if isinstance(aliases, str):
            aliases = re.split(r"[,\n]", aliases)
        aliases = [a.strip() for a in aliases if a and a.strip() and a.strip() != name]
        desc = str(p.get("description") or "").strip()[:500]
        if desc or aliases:
            prop_notes[name] = {"description": desc, "aliases": aliases}
    if errors:
        raise SchemaEditError(errors)

    old_overlay = meta.get("schema_overlay") or {}
    new_overlay = {"classes": [c for c in new_classes if c["name"] != c["orig"] or c["description"]],
                   "properties": prop_notes}
    summary = _structured_summary(old_overlay, new_overlay, renames)
    if dry_run:
        return {"errors": [], "warnings": warnings, "summary": summary}
    if summary == "변경 없음":
        return {"version": version, "summary": summary, "warnings": warnings, "saved": False}

    hist = list(meta.get("schema_history") or [])
    hist.append({"version": version, "at": meta.get("schema_updated_at") or meta.get("promoted_at"),
                 "summary": meta.get("schema_last_summary") or "구조화 스키마 (YAML 필드 구조)",
                 "overlay": old_overlay, "structured": True})
    meta["schema_history"] = hist[-HISTORY_MAX:]
    meta["schema_overlay"] = new_overlay
    meta["schema_version"] = version + 1
    meta["schema_updated_at"] = datetime.utcnow().isoformat()
    meta["schema_last_summary"] = summary + (f" — {note}" if note else "")
    kb.promotion_metadata = meta

    affected = set()
    for old, new in renames.items():
        exists = await SchemaMappingRule.find_one(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "key",
                                                  SchemaMappingRule.source_path == old)
        if exists:
            exists.target_path, exists.status = new, "active"
            await exists.save()
        else:
            await SchemaMappingRule(kb_id=kb_id, rule_type="key", source_path=old, target_path=new,
                                    origin="schema_editor").insert()
        affected.update(_docs_with_path(kb_id, cur_paths[old]["uris"]))
    if renames:
        kb.schema_rules_version = (kb.schema_rules_version or 0) + 1
    await kb.save()

    FusekiBackend.invalidate_class_catalog(kb_id)
    tbox = await mark_structured_ontology(kb_id)
    result = {"version": version + 1, "summary": summary, "warnings": warnings, "saved": True,
              "tbox_uploaded": bool(tbox.get("tbox")), "rules_changed": len(renames)}
    if affected:
        rn = await renormalize_documents(kb_id, sorted(affected))
        result["renormalize"] = {"queued": len(rn["queued"]), "needs_source": rn["needs_source"]}
    return result


def _structured_summary(old: Dict[str, Any], new: Dict[str, Any], renames: Dict[str, str]) -> str:
    parts = []
    oc = {c["orig"]: c for c in old.get("classes") or []}
    for c in new.get("classes") or []:
        o = oc.get(c["orig"])
        if not o or o.get("name") != c["name"]:
            parts.append(f"유형 이름 {(o or {}).get('name') or c['orig']}→{c['name']}")
        elif (o.get("description") or "") != (c.get("description") or ""):
            parts.append(f"유형 설명 {c['name']}")
    for c in old.get("classes") or []:
        if c["orig"] not in {x["orig"] for x in new.get("classes") or []}:
            parts.append(f"유형 이름 {c['name']}→{c['orig']}")
    op, np_ = old.get("properties") or {}, new.get("properties") or {}
    changed = [k for k in set(op) | set(np_) if op.get(k) != np_.get(k) and k not in renames.values()]
    if changed:
        parts.append(f"속성 정의·별칭 {', '.join(sorted(changed)[:5])}" + (" …" if len(changed) > 5 else ""))
    if renames:
        parts.append("속성 이름 " + ", ".join(f"{a}→{b}" for a, b in list(renames.items())[:5]))
    return " / ".join(parts) or "변경 없음"


async def _revert_structured(kb, h: Dict[str, Any]) -> Dict[str, Any]:
    """덧씌우기를 이력 버전으로 되돌리고, 그 뒤 편집기가 만든 경로 이름 변경 규칙은 끈 뒤 재정규화."""
    from app.models.schema_mapping import SchemaMappingRule
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    from app.services.schema_alignment.service import mark_structured_ontology, renormalize_documents
    from app.models.document import Document

    kb_id = str(kb.id)
    meta = dict(kb.promotion_metadata or {})
    version = int(meta.get("schema_version") or 1)
    since = h.get("at")
    disabled = 0
    for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "key",
                                          SchemaMappingRule.origin == "schema_editor",
                                          SchemaMappingRule.status == "active").to_list():
        if not since or r.created_at.isoformat() > str(since):
            r.status = "disabled"
            await r.save()
            disabled += 1
    hist = list(meta.get("schema_history") or [])
    hist.append({"version": version, "at": meta.get("schema_updated_at"), "summary": meta.get("schema_last_summary"),
                 "overlay": meta.get("schema_overlay") or {}, "structured": True})
    meta["schema_history"] = hist[-HISTORY_MAX:]
    meta["schema_overlay"] = copy.deepcopy(h.get("overlay") or {})
    meta["schema_version"] = version + 1
    meta["schema_updated_at"] = datetime.utcnow().isoformat()
    meta["schema_last_summary"] = f"버전 {h['version']} 으로 되돌림"
    kb.promotion_metadata = meta
    if disabled:
        kb.schema_rules_version = (kb.schema_rules_version or 0) + 1
    await kb.save()
    FusekiBackend.invalidate_class_catalog(kb_id)
    await mark_structured_ontology(kb_id)
    result = {"version": version + 1, "summary": meta["schema_last_summary"], "rules_changed": disabled, "saved": True}
    if disabled:
        docs = [str(d.id) for d in await Document.find(Document.kb_id == kb_id).to_list()]
        rn = await renormalize_documents(kb_id, docs)
        result["renormalize"] = {"queued": len(rn["queued"]), "needs_source": rn["needs_source"]}
    return result


async def preview(kb_id: str, spec_in: Dict[str, Any]) -> Dict[str, Any]:
    """저장 전 미리보기 — {errors, warnings, summary}."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise SchemaEditError(["KB 없음"], 404)
    if kb.schema_source == STRUCTURED:
        try:
            return await _save_structured_spec(kb, spec_in, None, "", dry_run=True)
        except SchemaEditError as e:
            return {"errors": e.errors, "warnings": [], "summary": ""}
    spec = _norm_spec(spec_in)
    errors, warnings = validate_spec(spec)
    ind = (kb.promotion_metadata or {}).get("induction") or {}
    diff = diff_spec({"classes": ind.get("classes") or [], "properties": ind.get("properties") or []}, spec)
    return {"errors": errors, "warnings": warnings, "diff": diff, "summary": _summary_text(diff)}



# ---------------------------------------------------------------------------
# §10 데이터 검증 후속: 멤버 지정·표기 병합 (사람 확인 후 규칙 + 리플레이)
# ---------------------------------------------------------------------------

async def _replay_text_docs(kb_id: str) -> Dict[str, Any]:
    from app.models.document import Document
    from app.services.schema_alignment.service import _is_structured_name, replay_documents
    ids = [str(d.id) for d in await Document.find(Document.kb_id == kb_id).to_list() if not _is_structured_name(d.filename)]
    rp = await replay_documents(kb_id, ids)
    return {"replayed": len(rp["replayed"]), "errors": [r for r in rp["replayed"] if r.get("error")][:5]}


async def assign_members(kb_id: str, class_name: str, entities: List[str]) -> Dict[str, Any]:
    """선택한 엔티티를 클래스 멤버로 (class 규칙, origin=schema_editor:member_gap) + 리플레이."""
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingRule
    from app.services.retrieval.entity_linking import _compact
    kb = await KnowledgeBase.get(kb_id)
    ind = ((kb.promotion_metadata or {}).get("induction") or {}) if kb else {}
    if class_name not in {c["name"] for c in ind.get("classes") or []}:
        raise SchemaEditError([f"클래스 '{class_name}' 이 스키마에 없습니다"])
    existing = {_compact(r.source_value): r for r in await SchemaMappingRule.find(
        SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "class").to_list() if r.source_value}
    added, moved = 0, 0
    for e in dict.fromkeys(x.strip() for x in entities if x and x.strip()):
        if not _compact(e):
            continue
        r = existing.get(_compact(e))
        if r:
            if r.target_value != class_name or r.status != "active":
                r.target_value, r.status = class_name, "active"
                await r.save()
                moved += 1
            continue
        await SchemaMappingRule(kb_id=kb_id, rule_type="class", source_value=e, target_value=class_name,
                                origin="schema_editor:member_gap").insert()
        added += 1
    if added or moved:
        kb.schema_rules_version = (kb.schema_rules_version or 0) + 1
        await kb.save()
    rp = await _replay_text_docs(kb_id) if (added or moved) else {"replayed": 0, "errors": []}
    return {"class": class_name, "added": added, "moved": moved, **rp}


async def merge_candidates(kb_id: str, class_name: str) -> Dict[str, Any]:
    """한 클래스의 멤버 + 그 클래스로 들어올 멤버 누락 후보 안에서 같은 개념 다른 표기(한·영 등)를 LLM 으로 묶는다.

    범위를 한 클래스로 좁혀(150개 이하) 비용·오병합을 줄이고, 결과는 제안일 뿐 — 사람이 체크해야 병합된다.
    """
    import json as _json
    from app.core.llm import achat, no_thinking_extra_body
    from app.core.models_resolver import resolve_model_config
    from app.models.knowledge_base import KnowledgeBase
    from app.services.retrieval.entity_linking import _compact
    from app.services.schema_alignment.service import _graph_llm_config, active_rules
    kb = await KnowledgeBase.get(kb_id)
    spec = await get_spec(kb_id)
    members = [r.source_value for r in await active_rules(kb_id)
               if r.rule_type == "class" and r.target_value == class_name and r.source_value]
    gaps = [g["name"] for g in (spec.get("member_gaps") or {}).get(class_name, [])]
    names = list(dict.fromkeys(members + gaps))[:150]
    if len(names) < 2:
        return {"class": class_name, "groups": []}
    cfg = await resolve_model_config(await _graph_llm_config(kb))
    msg = [{"role": "system", "content": "You group synonyms. Output JSON only."},
           {"role": "user", "content": f"""다음은 '{class_name}' 클래스의 엔티티 이름들이다. 같은 개념을 다르게 적은 것
(한국어/영어, 약어, 띄어쓰기·조사 차이)만 묶어라. 의미가 조금이라도 다르면 묶지 마라
(예: '확장성' 과 '확장성 요구' 는 다르다 — 하나는 품질, 하나는 요구). 목록에 있는 이름만 써라.
이름: {_json.dumps(names, ensure_ascii=False)}
JSON: {{"groups": [["대표로 쓸 이름", "같은 개념 이름", ...]]}}"""}]
    try:
        raw = await achat(cfg, msg, model=cfg.get("model"), temperature=0, response_format={"type": "json_object"},
                          extra_body=no_thinking_extra_body(cfg.get("model")), timeout=120)
        data = _json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except Exception as e:
        raise SchemaEditError([f"병합 후보 계산 실패: {str(e)[:150]}"], 502)
    by = {_compact(n): n for n in names}
    usage = {g["name"]: g["count"] for g in (spec.get("member_gaps") or {}).get(class_name, [])}
    groups = []
    for g in data.get("groups") or []:
        real = list(dict.fromkeys(by[_compact(x)] for x in g if _compact(str(x)) in by))
        if len(real) >= 2:
            # 대표: 이미 멤버인 이름 우선, 그다음 등장 수
            real.sort(key=lambda x: (x not in members, -usage.get(x, 0)))
            groups.append({"canonical": real[0], "aliases": real[1:]})
    return {"class": class_name, "groups": groups}


async def merge_entities(kb_id: str, canonical: str, aliases: List[str], replay: bool = True,
                         origin: str = "schema_editor:merge") -> Dict[str, Any]:
    """표기 병합 (entity 규칙) + 리플레이. replay=False 면 규칙만 (여러 병합을 묶어 리플레이 한 번 — merge_entities_batch)."""
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingRule
    from app.services.retrieval.entity_linking import _compact
    kb = await KnowledgeBase.get(kb_id)
    n = 0
    # 대표 이름을 다른 이름으로 바꾸는 기존 규칙(entity·value)이 있으면 병합을 되돌린다 (entity → value 순으로 적용되므로
    # '운영 복잡도 → operational complexity' 값 규칙이 남아 있으면 병합 결과가 다시 영어로 바뀜) → 끈다
    conflicts = 0
    for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.status == "active").to_list():
        if r.rule_type in ("entity", "value") and r.source_value and _compact(r.source_value) == _compact(canonical) \
                and _compact(r.target_value or "") != _compact(canonical):
            r.status = "disabled"
            r.origin = (r.origin or "") + "|병합 충돌"
            await r.save()
            conflicts += 1
    for a in dict.fromkeys(x.strip() for x in aliases if x and x.strip() and x.strip() != canonical):
        r = await SchemaMappingRule.find_one(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "entity",
                                             SchemaMappingRule.source_value == a)
        if r:
            r.target_value, r.status = canonical, "active"
            await r.save()
        else:
            await SchemaMappingRule(kb_id=kb_id, rule_type="entity", source_value=a, target_value=canonical,
                                    origin=origin).insert()
        n += 1
    if n or conflicts:
        kb.schema_rules_version = (kb.schema_rules_version or 0) + 1
        await kb.save()
    try:   # 용어 사전: 병합된 이름을 대표 항목의 별칭으로 (병합 뒤에도 옛 이름·성만으로 찾을 수 있게)
        from app.services.agent_query.lexicon import absorb_merged
        await absorb_merged(kb_id, canonical, [x for x in aliases if x and x.strip() and x.strip() != canonical])
    except Exception:
        pass
    rp = await _replay_text_docs(kb_id) if (replay and (n or conflicts)) else {"replayed": 0, "errors": []}
    return {"canonical": canonical, "merged": n, "conflicts_disabled": conflicts, **rp}


async def merge_entities_batch(kb_id: str, merges: List[Dict[str, Any]], origin: str = "schema_editor:merge") -> Dict[str, Any]:
    """여러 병합 [{canonical, aliases}] 을 규칙으로 넣고 리플레이는 한 번 (데이터 품질 D2: 중복 30여 묶음)."""
    done = []
    for m in merges:
        c = (m.get("canonical") or "").strip()
        al = [a for a in (m.get("aliases") or []) if a and a.strip() and a.strip() != c]
        if not c or not al:
            continue
        r = await merge_entities(kb_id, c, al, replay=False, origin=origin)
        done.append({"canonical": c, "merged": r["merged"], "conflicts_disabled": r["conflicts_disabled"]})
    rp = await _replay_text_docs(kb_id) if done else {"replayed": 0, "errors": []}
    return {"groups": len(done), "rules": sum(d["merged"] for d in done), "details": done, **rp}


# ---------------------------------------------------------------------------
# 속성별 트리플 목록 (편집기: 트리플 수 클릭) — 실제 데이터를 보며 스키마를 고치기 위함
# ---------------------------------------------------------------------------

async def property_triples(kb_id: str, prop: str, limit: int = 200) -> Dict[str, Any]:
    """속성(텍스트: 관계 이름, 구조화: 필드 경로)의 트리플 + 상태.

    상태: ok(목적어가 range 멤버) / gap(멤버 누락) / violation(다른 클래스) / value(서술·수치 등 값) / -(range 없음)
    domain 과 다른 주어 클래스면 subject_mismatch 표시. 근거 청크 id(source node)·문서 이름 포함.
    """
    from app.core.fuseki import fuseki_client
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase
    from app.services.retrieval.entity_linking import _compact
    from app.services.schema_alignment.induction import REL_NS
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise SchemaEditError(["KB 없음"], 404)
    limit = max(1, min(int(limit or 200), 1000))
    LBL = "<http://www.w3.org/2000/01/rdf-schema#label>"
    RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

    def label_of(b, k, uk):
        v = b.get(k, {}).get("value")
        if v:
            return v
        u = b.get(uk, {}).get("value", "")
        return u.rstrip("/").rsplit("/", 1)[-1] if u.startswith("http") else u

    rows: List[Dict[str, Any]] = []
    domain = rng = ""
    if kb.schema_source == STRUCTURED:
        kinds, catalogs = await _structured_catalog(kb_id)
        path = next((p for k in kinds for p in catalogs.get(k["name"]) or [] if p["key"] == prop), None)
        if not path:
            raise SchemaEditError([f"경로 '{prop}' 없음"], 404)
        kind = next(k for k in kinds if any(p is path for p in catalogs.get(k["name"]) or []))
        domain, rng = kind["name"], path.get("ref_kind") or ""
        uris = path["uris"]
        chain = " . ".join(f"?n{i} <{u}> ?n{i + 1}" for i, u in enumerate(uris)).replace("?n0", "?s").replace(f"?n{len(uris)}", "?o")
        # 값을 직접 가진 노드(레코드 또는 마지막 중첩 노드) — 구조화 청크 id 는 '{doc}::struct::{노드 로컬명}'
        holder = "?s" if len(uris) == 1 else f"?n{len(uris) - 1}"
        q = f"""SELECT ?g ?s ?o (SAMPLE({holder}) AS ?h) (SAMPLE(?sl0) AS ?sl) (SAMPLE(?ol0) AS ?ol) WHERE {{ GRAPH ?g {{ {chain}
                 OPTIONAL {{ ?s {LBL} ?sl0 }} OPTIONAL {{ ?o {LBL} ?ol0 }} }}
                 FILTER(STRSTARTS(STR(?g), "urn:doc:")) }} GROUP BY ?g ?s ?o LIMIT {limit}"""
        members = set(kind["members"])
        owner = {m: k["name"] for k in kinds for m in k["members"]}
        for b in fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", []):
            s_uri = b["s"]["value"]
            if s_uri not in members:
                continue
            o_uri = b["o"]["value"]
            ocls = owner.get(o_uri, "")
            st = ("ok" if ocls == rng else "violation" if ocls else "gap") if rng else ("value" if b["o"]["type"] != "uri" or not ocls else "-")
            h = b.get("h", {}).get("value") or s_uri
            doc_id = b["g"]["value"][8:]
            rows.append({"subject": label_of(b, "sl", "s"), "object": label_of(b, "ol", "o"), "object_class": ocls,
                         "subject_class": domain, "status": st, "doc_id": doc_id,
                         "source": f"{doc_id}::struct::{h.rstrip('/').rsplit('/', 1)[-1]}"})
    else:
        ind = (kb.promotion_metadata or {}).get("induction") or {}
        p = next((x for x in ind.get("properties") or [] if x["name"] == prop), None)
        if not p:
            raise SchemaEditError([f"속성 '{prop}' 없음"], 404)
        domain, rng = p.get("domain") or "", p.get("range") or ""
        cls = await _class_index(kb_id)
        names = [prop] + [m for m in p.get("members") or [] if m != prop]
        vals = " ".join(f"<{REL_NS}{re.sub(r'[^0-9A-Za-z가-힣_]', '_', n)}>" for n in names)
        q = f"""SELECT ?g ?s ?o ?p (SAMPLE(?sl0) AS ?sl) (SAMPLE(?ol0) AS ?ol) (SAMPLE(?src0) AS ?src) WHERE {{
                 VALUES ?p {{ {vals} }}
                 GRAPH ?g {{ ?s ?p ?o OPTIONAL {{ ?s {LBL} ?sl0 }} OPTIONAL {{ ?o {LBL} ?ol0 }}
                   OPTIONAL {{ ?st <{RDF}subject> ?s ; <{RDF}predicate> ?p ; <{RDF}object> ?o ;
                                   <http://rag.local/meta/sourceNodeId> ?src0 }} }}
                 FILTER(STRSTARTS(STR(?g), "urn:doc:")) }} GROUP BY ?g ?s ?o ?p LIMIT {limit}"""
        for b in fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", []):
            sl, ol = label_of(b, "sl", "s"), label_of(b, "ol", "o")
            scls, ocls = cls.get(_compact(sl), ""), cls.get(_compact(ol), "")
            if not _usable_object(ol):
                st = "value"
            elif not rng:
                st = "-"
            else:
                st = "ok" if ocls == rng else ("violation" if ocls else "gap")
            rows.append({"subject": sl, "object": ol, "subject_class": scls, "object_class": ocls, "status": st,
                         "subject_mismatch": bool(domain and scls and scls != domain),
                         "predicate": b["p"]["value"][len(REL_NS):], "doc_id": b["g"]["value"][8:],
                         "source": b.get("src", {}).get("value")})
    names_by_doc = {}
    for did in {r["doc_id"] for r in rows}:
        try:
            d = await Document.get(did)
            names_by_doc[did] = d.filename if d else did[:8]
        except Exception:
            names_by_doc[did] = did[:8]
    for r in rows:
        r["doc"] = names_by_doc.get(r["doc_id"], "")
    order = {"violation": 0, "gap": 1, "ok": 2, "-": 3, "value": 4}
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["subject"], r["object"]))
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"property": prop, "domain": domain, "range": rng, "mode": "structured" if kb.schema_source == STRUCTURED else "induced",
            "total": len(rows), "truncated": len(rows) >= limit, "counts": counts, "triples": rows}


# ---------------------------------------------------------------------------
# 트리플 단위 편집 (트리플 목록) — 그래프를 직접 고치지 않고 triple 규칙으로 남겨 리플레이·재추출 후에도 유지
# ---------------------------------------------------------------------------

def _spec_from_induction(ind: Dict[str, Any]) -> Dict[str, Any]:
    return {"classes": [{"name": c["name"], "description": c.get("description", "")} for c in ind.get("classes") or []],
            "properties": [{"name": p["name"], "description": p.get("description", ""), "domain": p.get("domain", ""),
                            "range": p.get("range", ""), "seed": p.get("seed", False),
                            "aliases": [a for a in p.get("members") or [] if a != p["name"]]}
                           for p in ind.get("properties") or []]}


async def _add_to_schema(kb_id: str, new_class: Optional[Dict[str, Any]] = None,
                         new_property: Optional[Dict[str, Any]] = None, note: str = "") -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    meta = kb.promotion_metadata or {}
    spec = _spec_from_induction(meta.get("induction") or {})
    if new_class:
        spec["classes"].append({"name": new_class["name"], "description": new_class.get("description", "")})
    if new_property:
        spec["properties"].append({"name": new_property["name"], "description": new_property.get("description", ""),
                                   "domain": new_property.get("domain", ""), "range": new_property.get("range", ""),
                                   "aliases": []})
    return await save_spec(kb_id, spec, base_version=int(meta.get("schema_version") or 1), replay=False, note=note)


async def edit_triples(kb_id: str, action: str, triples: List[Dict[str, str]],
                       target_property: Optional[str] = None,
                       new_property: Optional[Dict[str, Any]] = None,
                       origin: Optional[str] = None) -> Dict[str, Any]:
    """선택한 트리플을 다른 관계로 이동(move), 삭제(delete), 방향 뒤집기(flip), 추가(add). new_property 를 주면 그 관계를 스키마에 만들고 이동.

    add: 원문에 있는데 추출이 놓친 사실을 고정한다 — 트리플마다 source(근거 청크 ID)·doc_id 필수, year 선택.
    규칙으로 남아 리플레이·재추출 뒤에도 유지된다 (target_path="@add").

    triple 규칙: pair=[주어, 관계, 목적어](그래프 표기), target_path=이동할 관계 (삭제면 None). 같은 트리플의 기존 규칙은 덮는다.
    """
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingRule
    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.schema_source not in EDITABLE_SOURCES:
        raise SchemaEditError(["텍스트(승격) KB 에서만 트리플을 편집할 수 있습니다 — 구조화 KB 는 YAML 원본에서"])
    if action not in ("move", "delete", "flip", "add"):
        raise SchemaEditError([f"알 수 없는 동작: {action}"])
    ind = (kb.promotion_metadata or {}).get("induction") or {}
    names = {p["name"] for p in ind.get("properties") or []}
    created = None
    if action == "move":
        if new_property:
            nm = clean_prop_name(new_property.get("name"))
            if not nm:
                raise SchemaEditError(["새 관계 이름이 비었습니다"])
            if nm in names:
                raise SchemaEditError([f"관계 '{nm}' 은 이미 있습니다 — 기존 관계로 이동을 고르세요"])
            r = await _add_to_schema(kb_id, new_property={**new_property, "name": nm},
                                     note=f"트리플 이동용 관계 추가: {nm}")
            created = {"property": nm, "version": r.get("version")}
            target_property = nm
        target_property = clean_prop_name(target_property)
        if not target_property or (target_property not in names and not created):
            raise SchemaEditError([f"이동할 관계 '{target_property}' 이 스키마에 없습니다"])
    rows = [t for t in triples if t.get("subject") and t.get("predicate") and t.get("object")]
    if not rows:
        raise SchemaEditError(["선택한 트리플이 없습니다"])
    if action == "add":
        errs = [f"'{t['predicate']}' 은 스키마 관계가 아닙니다" for t in rows if t["predicate"] not in names]
        errs += [f"근거 청크(source)·문서(doc_id)가 필요합니다: {t['subject']} {t['predicate']} {t['object']}"
                 for t in rows if not (t.get("source") and t.get("doc_id"))]
        if errs:
            raise SchemaEditError(errs[:5])
    n = 0
    for t in rows:
        pair = [t["subject"], t["predicate"], t["object"]]
        if action == "move" and t["predicate"] == target_property:
            continue
        r = await SchemaMappingRule.find_one(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "triple",
                                             SchemaMappingRule.pair == pair)
        tgt = {"move": target_property, "flip": "@flip", "add": "@add"}.get(action)
        extra = {}
        if action == "add":
            extra = {"source_value": t["source"], "scope_paths": [t["doc_id"]],
                     "target_value": str(int(t["year"])) if str(t.get("year") or "").isdigit() else None}
        if r:
            r.target_path, r.status = tgt, "active"
            for k, v in extra.items():
                setattr(r, k, v)
            await r.save()
        else:
            await SchemaMappingRule(kb_id=kb_id, rule_type="triple", pair=pair, target_path=tgt,
                                    origin=origin or f"schema_editor:triple_{action}", **extra).insert()
        n += 1
    kb = await KnowledgeBase.get(kb_id)
    kb.schema_rules_version = (kb.schema_rules_version or 0) + 1
    await kb.save()
    rp = await _replay_text_docs(kb_id)
    if action in ("flip", "delete"):
        try:   # 방향 검증 결과에 반영 표시 (다음 증분 검증이 다시 판정하지 않게)
            from app.services.schema_alignment.direction_audit import mark_applied
            await mark_applied(kb_id, rows, action, "auto" if origin == "auto_direction" else "user")
        except Exception:
            pass
    return {"action": action, "edited": n, "target_property": target_property if action == "move" else None,
            "created": created, **rp}


async def create_class_with_members(kb_id: str, name: str, description: str, members: List[str]) -> Dict[str, Any]:
    """새 클래스를 스키마에 추가하고 선택한 엔티티를 멤버로 지정 (멤버 누락 → 새 클래스)."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.schema_source not in EDITABLE_SOURCES:
        raise SchemaEditError(["텍스트(승격) KB 에서만 클래스를 만들 수 있습니다"])
    nm = clean_class_name(name)
    if not nm:
        raise SchemaEditError(["클래스 이름이 비었습니다 (영어 PascalCase 권장)"])
    ind = (kb.promotion_metadata or {}).get("induction") or {}
    if nm in {c["name"] for c in ind.get("classes") or []}:
        raise SchemaEditError([f"클래스 '{nm}' 은 이미 있습니다 — 기존 클래스 멤버로 지정하세요"])
    r = await _add_to_schema(kb_id, new_class={"name": nm, "description": description}, note=f"클래스 추가: {nm}")
    out = await assign_members(kb_id, nm, members) if members else {"added": 0, "moved": 0}
    return {"class": nm, "version": r.get("version"), **out}



# ---------------------------------------------------------------------------
# 재추출 테스트 — 편집 중인 스키마로 선택 트리플의 근거 청크만 다시 추출해 비교 (저장 없음)
# ---------------------------------------------------------------------------

PREVIEW_MAX_CHUNKS = 10


async def reextract_preview(kb_id: str, spec_in: Dict[str, Any], triples: List[Dict[str, Any]],
                            model_key: str = "ingest") -> Dict[str, Any]:
    """선택 트리플마다: 사라짐 / 남음 / 관계 바뀜(같은 주어·목적어, 다른 관계). 청크별 새 결과도 함께.

    spec_in: 편집기의 현재(저장 전) 스키마 {classes, properties}. 청크당 LLM 1회, 최대 10청크.
    """
    from app.models.knowledge_base import KnowledgeBase
    from app.services.ingestion.ingest_client import ingest_client
    from app.services.retrieval.entity_linking import _compact
    from app.services.schema_alignment import reextract as rx
    from app.services.schema_alignment.service import rules_for_ingest
    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.schema_source not in EDITABLE_SOURCES:
        raise SchemaEditError(["텍스트(승격) KB 에서만 재추출 테스트를 할 수 있습니다"])
    spec = _norm_spec(spec_in)
    errors, _w = validate_spec(spec)
    if errors:
        raise SchemaEditError(["편집 중인 스키마에 오류가 있습니다: " + "; ".join(errors[:3])])
    sel = [t for t in triples if t.get("source") and t.get("doc_id")]
    if not sel:
        raise SchemaEditError(["근거 청크가 있는 트리플을 선택하세요"])
    by_doc: Dict[str, List[str]] = {}
    for t in sel:
        ids = by_doc.setdefault(t["doc_id"], [])
        if t["source"] not in ids:
            ids.append(t["source"])
    n_chunks = sum(len(v) for v in by_doc.values())
    if n_chunks > PREVIEW_MAX_CHUNKS:
        raise SchemaEditError([f"근거 청크가 {n_chunks}개입니다 — 한 번에 {PREVIEW_MAX_CHUNKS}개까지 (선택을 줄이세요)"])
    opts = await rx._model_options(kb)
    llm = opts.get(model_key) or opts.get("ingest")
    if not llm:
        raise SchemaEditError(["재추출 모델을 확인할 수 없습니다"])
    full = await rx.build_schema_spec(kb, override={"classes": spec["classes"], "properties": [
        {**p, "aliases": [a for a in p["members"] if a != p["name"]]} for p in spec["properties"]]})
    rules = await rules_for_ingest(kb_id, include_graph_rules=True)
    out_by_chunk: Dict[str, List[Dict[str, Any]]] = {}
    failures = []
    for doc_id, node_ids in by_doc.items():
        try:
            r = await ingest_client.reextract_preview(kb_id, doc_id, node_ids, full, llm, rules or None)
        except Exception as e:
            failures.append({"doc_id": doc_id, "error": str(e)[:200]})
            continue
        for t in r.get("triples") or []:
            out_by_chunk.setdefault(t.get("source_node_id"), []).append(
                {"subject": t["subject"], "predicate": t["predicate"], "object": t["object"],
                 "out_of_schema": bool(t.get("out_of_schema"))})
        failures += r.get("stats", {}).get("chunk_failures") or []

    def k3(t):
        return (_compact(t["subject"]), _compact(t["predicate"]), _compact(t["object"]))

    results, summary = [], {"gone": 0, "kept": 0, "moved": 0}
    for t in sel:
        outs = out_by_chunk.get(t["source"]) or []
        same = [o for o in outs if k3(o) == k3(t)]
        so = [o for o in outs if (_compact(o["subject"]), _compact(o["object"])) == (_compact(t["subject"]), _compact(t["object"]))]
        if same:
            res = {"result": "kept"}
        elif so:
            res = {"result": "moved", "new_predicate": so[0]["predicate"]}
        else:
            res = {"result": "gone"}
        summary[res["result"]] += 1
        results.append({**{k: t.get(k) for k in ("subject", "predicate", "object", "source", "doc")}, **res})
    return {"model": llm.get("model"), "chunks": n_chunks, "summary": summary, "results": results,
            "chunk_triples": out_by_chunk, "failures": failures[:5]}


async def mismatch_triples(kb_id: str, status: str = "violation", class_name: Optional[str] = None,
                           per_property: int = 300) -> Dict[str, Any]:
    """range 를 가진 모든 관계에서 일치하지 않는 트리플 모음 (데이터 검증 카드에서 클릭).

    status: violation(목적어가 다른 클래스) / gap(목적어에 클래스 없음) / all(둘 다).
    class_name: range 가 그 클래스인 관계만 (멤버 누락을 클래스별로 볼 때).
    """
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.schema_source not in EDITABLE_SOURCES:
        raise SchemaEditError(["텍스트(승격) KB 에서만 볼 수 있습니다"])
    ind = (kb.promotion_metadata or {}).get("induction") or {}
    want = {"violation"} if status == "violation" else {"gap"} if status == "gap" else {"violation", "gap"}
    rows, by_prop = [], {}
    for p in ind.get("properties") or []:
        if not p.get("range") or (class_name and p["range"] != class_name):
            continue
        try:
            r = await property_triples(kb_id, p["name"], per_property)
        except SchemaEditError:
            continue
        hit = [{**t, "property": p["name"], "range": p["range"], "domain": p.get("domain") or ""}
               for t in r["triples"] if t["status"] in want]
        if hit:
            by_prop[p["name"]] = len(hit)
            rows.extend(hit)
    counts: Dict[str, int] = {}
    for t in rows:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return {"mode": "mismatch", "status": status, "class": class_name, "total": len(rows), "counts": counts,
            "by_property": by_prop, "triples": rows, "truncated": False, "domain": "", "range": class_name or ""}
