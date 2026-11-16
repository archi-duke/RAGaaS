"""스키마 편집기 (사람 검수 1단계) — docs/design-schema-editor.md

승격(유도·시드)으로 확정된 텍스트 KB 스키마(promotion_metadata.induction)를 사람이 직접 고친다.
- 편집 대상: 클래스(이름·설명), 속성(이름·정의·domain·range·별칭)
- 저장하면: 검증 → 이전 버전을 이력에 보관 → TBox(urn:ontology) 재생성 → 클래스 카탈로그 무효화
- 이름 변경: 속성은 key 규칙(옛 이름 → 새 이름)을, 클래스는 class 규칙의 대상 이름을 바꾼 뒤
  텍스트 문서를 리플레이해 기존 그래프에 반영한다 (LLM 비용 0, 저장된 추출 트리플 기준·멱등).
- 정의·방향(domain/range)·별칭의 의미 변경은 '스키마 기준 재추출'을 돌려야 데이터에 반영된다 (선택).
구조화(YAML/JSON) KB 는 필드 구조가 곧 스키마라 이 편집기 대상이 아니다 — 매핑 규칙으로 고친다.
"""

import copy
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HISTORY_MAX = 20
EDITABLE_SOURCES = ("induced", "declared")


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


async def get_spec(kb_id: str) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    from app.services.schema_alignment.service import active_rules
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise SchemaEditError(["KB 없음"], 404)
    meta = kb.promotion_metadata or {}
    ind = meta.get("induction") or {}
    editable = kb.schema_source in EDITABLE_SOURCES and bool(ind.get("classes") or ind.get("properties"))
    members: Dict[str, int] = {}
    for r in await active_rules(kb_id):
        if r.rule_type == "class" and r.target_value:
            members[r.target_value] = members.get(r.target_value, 0) + 1
    usage = _usage_counts(kb_id) if editable else {}
    classes = [{"name": c["name"], "description": c.get("description", ""), "member_count": members.get(c["name"], 0)}
               for c in ind.get("classes") or []]
    props = []
    for p in ind.get("properties") or []:
        props.append({"name": p["name"], "description": p.get("description", ""), "domain": p.get("domain", ""),
                      "range": p.get("range", ""), "aliases": [a for a in p.get("members") or [] if a != p["name"]],
                      "seed": bool(p.get("seed")), "triple_count": usage.get(p["name"], 0)})
    known = {p["name"] for p in props}
    out_of_schema = sorted(((k, v) for k, v in usage.items() if k not in known), key=lambda x: -x[1])[:30]
    hist = meta.get("schema_history") or []
    return {
        "kb_id": kb_id, "editable": editable, "schema_source": kb.schema_source,
        "reason": None if editable else (
            "구조화(YAML/JSON) KB 는 필드 구조가 스키마입니다 — 스키마 정렬의 매핑 규칙으로 고치세요"
            if kb.schema_source == "structured" else "승격(스키마 유도)된 KB 만 편집할 수 있습니다"),
        "version": int(meta.get("schema_version") or 1),
        "updated_at": meta.get("schema_updated_at") or meta.get("promoted_at"),
        "classes": classes, "properties": props,
        "out_of_schema": [{"name": k, "triple_count": v} for k, v in out_of_schema],
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
