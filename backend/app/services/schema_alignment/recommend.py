"""스키마 AI 추천 — 스키마·데이터 검증 결과·문제 트리플의 근거 청크를 보고 처리안을 제시 (docs/design-schema-editor.md §14).

흐름: recommend(처리안 목록) → 사용자가 체크 → preview(체크한 안을 가상으로 적용해 문제 청크 재추출 — 저장 없음)
      → 사용자 승인 → apply(스키마 저장 1회 + 규칙 생성 + 리플레이 1회).
처리안은 모두 기존 편집 동작에 대응한다 — AI 는 판단만 하고, 데이터 변경은 검증된 경로로만 한다.
"""

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from app.services.schema_alignment.schema_editor import (
    EDITABLE_SOURCES, SchemaEditError, _class_index, _norm_spec, _spec_from_induction, clean_class_name,
    clean_prop_name, get_spec, property_triples, validate_spec)

MAX_PROBLEM_TRIPLES = 14
MAX_PREVIEW_CHUNKS = 10
SCHEMA_ACTIONS = ("set_definition", "set_range", "set_domain", "add_property", "add_class")
DATA_ACTIONS = ("assign_members", "merge_entities", "move_triples", "delete_triples")
ACTION_LABEL = {
    "set_definition": "정의 수정", "set_range": "range 변경", "set_domain": "domain 변경", "add_property": "관계 추가",
    "add_class": "클래스 추가", "assign_members": "멤버 지정", "merge_entities": "표기 병합",
    "move_triples": "트리플 이동", "delete_triples": "트리플 삭제",
}


def _now() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat()


def _count_types(actions: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for a in actions:
        out[a["type"]] = out.get(a["type"], 0) + 1
    return out


async def _log(kb_id: str, entry: Dict[str, Any]) -> None:
    """추천 수용 기록 (promotion_metadata.ai_recommend_log, 최근 30건) — 추천을 얼마나 그대로 받아들였는지."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        return
    meta = dict(kb.promotion_metadata or {})
    log = list(meta.get("ai_recommend_log") or [])
    for e in log:
        if e.get("id") == entry.get("id"):
            e.update(entry)
            break
    else:
        log.append(entry)
    meta["ai_recommend_log"] = log[-30:]
    kb.promotion_metadata = meta
    await kb.save()


# ---------------------------------------------------------------------------
# 추천 기억: 사람이 거절한 안 / 확정한 결정 — 다음 추천에서 반복·번복하지 않게 (promotion_metadata.ai_recommend_memory)
# ---------------------------------------------------------------------------

MEMORY_MAX = 200


def _triple_sig(x: Dict[str, Any]) -> str:
    from app.services.retrieval.entity_linking import _compact
    return "|".join(_compact(x.get(k) or "") for k in ("subject", "predicate", "object"))


def rejection_sigs(a: Dict[str, Any], removed: Optional[List[str]] = None) -> List[str]:
    """처리안(또는 수정으로 뺀 엔티티)의 거절 서명. 같은 서명의 안은 다음 추천에서 결정적으로 뺀다."""
    from app.services.retrieval.entity_linking import _compact
    t = a.get("type")
    if t in ("set_range", "set_domain"):
        key = "range" if t == "set_range" else "domain"
        return [f"{t}:{a.get('property')}:{a.get(key) or ''}"]
    if t == "assign_members":
        ents = removed if removed is not None else a.get("entities") or []
        return [f"member:{a.get('class')}:{_compact(e)}" for e in ents]
    if t == "add_class":
        return [f"add_class:{_compact(a.get('name') or '')}"]
    if t == "add_property":
        return [f"add_property:{_compact(a.get('name') or '')}"]
    if t == "merge_entities":
        al = removed if removed is not None else a.get("aliases") or []
        return [f"merge:{_compact(a.get('canonical') or '')}:{_compact(x)}" for x in al]
    if t == "delete_triples":
        # 삭제를 거절 = "이 트리플은 맞다" → 그 트리플의 삭제·이동을 모두 막는다
        return [f"keep:{_triple_sig(x)}" for x in a.get("triples") or []]
    if t == "move_triples":
        # 이동을 거절 = 그 대상 관계가 틀렸다 (다른 관계로의 이동은 열어 둔다)
        return [f"move:{_triple_sig(x)}:{a.get('target_property')}" for x in a.get("triples") or []]
    return []    # 정의 수정은 문구가 매번 달라 서명으로 막지 않는다 (프롬프트로만)


def _describe(a: Dict[str, Any], removed: Optional[List[str]] = None) -> str:
    t = a.get("type")
    if t in ("set_range", "set_domain"):
        k = "range" if t == "set_range" else "domain"
        return f"{a.get('property')} 의 {k} 를 '{a.get(k) or '(값)'}' 로"
    if t == "assign_members":
        return f"{', '.join((removed if removed is not None else a.get('entities') or [])[:8])} 를 {a.get('class')} 멤버로"
    if t == "merge_entities":
        return f"{', '.join((removed if removed is not None else a.get('aliases') or [])[:5])} → {a.get('canonical')} 병합"
    if t in ("move_triples", "delete_triples"):
        tr = "; ".join(f"{x.get('subject')} —{x.get('predicate')}→ {x.get('object')}" for x in (a.get("triples") or [])[:3])
        if t == "move_triples":
            return f"{tr} 를 {a.get('target_property')} 로 이동"
        return f"{tr} 는 맞는 트리플 — 삭제·이동 안 함"
    if t == "set_definition":
        return f"{a.get('property')} 정의를 '{str(a.get('description') or '')[:80]}' 로"
    return f"{ACTION_LABEL.get(t, t)} {a.get('name') or ''}"


async def remember(kb_id: str, rejected: List[Dict[str, Any]], accepted: List[Dict[str, Any]]) -> Dict[str, int]:
    """거절(체크 해제 + 수정으로 뺀 엔티티)과 확정 결정(승인한 range·domain)을 기억에 쌓는다."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        return {"rejected": 0, "decided": 0}
    meta = dict(kb.promotion_metadata or {})
    mem = dict(meta.get("ai_recommend_memory") or {})
    rej = list(mem.get("rejected") or [])
    have = {r["sig"] for r in rej}
    n_rej = 0

    def add(a, removed=None):
        nonlocal n_rej
        # 멤버·병합은 이름마다 따로 기억 (설명도 그 이름만)
        if a.get("type") in ("assign_members", "merge_entities"):
            names = removed if removed is not None else (a.get("entities") if a["type"] == "assign_members" else a.get("aliases")) or []
            parts = [(rejection_sigs(a, [x])[0], _describe(a, [x])) for x in names]
        elif a.get("type") in ("move_triples", "delete_triples"):
            parts = [(rejection_sigs({**a, "triples": [x]})[0], _describe({**a, "triples": [x]})) for x in a.get("triples") or []]
        else:
            parts = [(sg, _describe(a)) for sg in rejection_sigs(a)]
        for sig, text in parts:
            if sig and sig not in have:
                have.add(sig)
                rej.append({"sig": sig, "text": text, "reason": a.get("reject_reason") or "", "at": _now()})
                n_rej += 1

    for a in rejected:
        add(a)
    for a in accepted:
        orig = a.get("orig") or {}
        if a.get("type") == "assign_members" and orig.get("entities"):
            gone = [e for e in orig["entities"] if e not in set(a.get("entities") or [])]
            if gone:
                add(a, gone)
        if a.get("type") == "merge_entities" and orig.get("aliases"):
            gone = [x for x in orig["aliases"] if x not in set(a.get("aliases") or [])]
            if gone:
                add(a, gone)
    decided = dict(mem.get("decided") or {})
    n_dec = 0
    for a in accepted:
        if a.get("type") in ("set_range", "set_domain"):
            k = "range" if a["type"] == "set_range" else "domain"
            decided[f"{k}:{a['property']}"] = {"value": a.get(k) or "", "at": _now()}
            n_dec += 1
    mem["rejected"] = rej[-MEMORY_MAX:]
    mem["decided"] = decided
    meta["ai_recommend_memory"] = mem
    kb.promotion_metadata = meta
    await kb.save()
    return {"rejected": n_rej, "decided": n_dec}


def _chunk_texts(kb_id: str, chunk_ids: List[str]) -> Dict[str, str]:
    from app.core.milvus import create_collection
    out: Dict[str, str] = {}
    if not chunk_ids:
        return out
    try:
        col = create_collection(kb_id)
        col.load()
        ids = ", ".join(json.dumps(c) for c in chunk_ids)
        for r in col.query(expr=f"chunk_id in [{ids}]", output_fields=["chunk_id", "content"], limit=len(chunk_ids)):
            out[r["chunk_id"]] = (r.get("content") or "")[:900]
    except Exception:
        pass
    return out


async def collect_context(kb_id: str, scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """추천 입력: 스키마 + 데이터 검증 + 문제 트리플(근거 청크 본문 포함).

    scope.triples 가 있으면 그 트리플만 문제 목록으로 (트리플 창에서 호출), 없으면 검증 결과에서 고른다.
    """
    spec = await get_spec(kb_id)
    if not spec.get("editable") or spec.get("mode") != "induced":
        raise SchemaEditError(["텍스트(승격) KB 에서만 AI 추천을 쓸 수 있습니다"])
    problems: List[Dict[str, Any]] = []
    if scope and scope.get("triples"):
        problems = [t for t in scope["triples"] if t.get("subject") and t.get("object")][:MAX_PROBLEM_TRIPLES]
    elif scope and scope.get("gaps") is not None:
        # 재추출 뒤 정리: 멤버 누락 목적어(특히 새로 생긴 표기)를 가진 트리플을 문제로 — 관계마다 고르게
        want = {n for names in (scope.get("gaps") or {}).values() for n in names}
        props_with_gaps = []
        for items in (spec.get("member_gaps") or {}).values():
            for g in items:
                if not want or g["name"] in want:
                    props_with_gaps.extend(g.get("via") or [])
        for name in list(dict.fromkeys(props_with_gaps))[:8]:
            try:
                rows = (await property_triples(kb_id, name, 150))["triples"]
            except SchemaEditError:
                continue
            for r in rows:
                if r["status"] == "gap" and (not want or r["object"] in want) and len(problems) < MAX_PROBLEM_TRIPLES:
                    problems.append({**r, "property": name, "predicate": r.get("predicate") or name})
    else:
        # 위반·누락이 많은 관계부터 문제 트리플을 고른다
        scored = []
        for p in spec["properties"]:
            c = p.get("range_check") or {}
            if p.get("range") and c.get("n", 0) >= 5:
                scored.append(((c.get("declared_ratio") or 0), p["name"]))
        scored.sort()
        for _ratio, name in scored[:4]:
            try:
                rows = (await property_triples(kb_id, name, 120))["triples"]
            except SchemaEditError:
                continue
            for r in rows:
                if r["status"] in ("violation", "gap") and len(problems) < MAX_PROBLEM_TRIPLES:
                    problems.append({**r, "property": name, "predicate": r.get("predicate") or name})
    texts = _chunk_texts(kb_id, list(dict.fromkeys(t["source"] for t in problems if t.get("source"))))
    # 그래프에 있는 엔티티 라벨 (처리안 엔티티 이름 검증용)
    from app.core.fuseki import fuseki_client
    from app.services.retrieval.entity_linking import _compact
    entity_keys = set((await _class_index(kb_id)).keys())
    try:
        q = """SELECT DISTINCT ?l WHERE { GRAPH ?g { ?e <http://www.w3.org/2000/01/rdf-schema#label> ?l
               FILTER(STRSTARTS(STR(?e), "http://rag.local/inst/")) } FILTER(STRSTARTS(STR(?g), "urn:doc:")) } LIMIT 20000"""
        for b in fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", []):
            entity_keys.add(_compact(b["l"]["value"]))
    except Exception:
        pass
    for t in problems:
        t["chunk_text"] = texts.get(t.get("source") or "", "")
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    memory = ((kb.promotion_metadata or {}).get("ai_recommend_memory") or {}) if kb else {}
    return {"spec": spec, "problems": problems, "entity_keys": entity_keys, "memory": memory}


def build_messages(ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    spec = ctx["spec"]
    cls_lines = [f"- {c['name']} (멤버 {c.get('member_count', 0)}): {c.get('description') or ''}" for c in spec["classes"]]
    prop_lines = []
    for p in spec["properties"]:
        c = p.get("range_check") or {}
        chk = (f" [일치 {round((c.get('declared_ratio') or 0) * 100)}%/{c.get('n')}]" if c.get("n", 0) >= 5 and p.get("range") else "")
        prop_lines.append(f"- {p['name']}: {p.get('domain') or '?'} → {p.get('range') or '(값)'}{chk} "
                          f"트리플 {p.get('triple_count', 0)} | 정의: {p.get('description') or '(없음)'}")
    gaps = []
    for cls, items in (spec.get("member_gaps") or {}).items():
        gaps.append(f"- {cls}: " + ", ".join(f"{g['name']}({g['count']})" for g in items[:15]))
    viol = [f"- {v['property']}: {v['name']} 은 {v['class']} (range {v['range']})" for v in (spec.get("range_violations") or [])[:20]]
    oos = ", ".join(f"{o['name']}({o['triple_count']})" for o in (spec.get("out_of_schema") or [])[:15])
    prob = []
    for i, t in enumerate(ctx["problems"]):
        prob.append(f"[T{i}] {t['subject']} —{t.get('predicate')}→ {t['object']}  (상태: {t.get('status')}, "
                    f"주어 클래스: {t.get('subject_class') or '-'}, 목적어 클래스: {t.get('object_class') or '-'})\n"
                    f"     근거 청크: {(t.get('chunk_text') or '(없음)')[:500]}")
    user = f"""지식 그래프 스키마를 검토하고, 문제를 고치는 처리안을 제시하라. 처리안은 사람이 하나씩 체크해 승인한다.

[클래스]
{chr(10).join(cls_lines)}

[관계/속성] 이름: domain → range [목적어 중 range 멤버 비율/서로 다른 목적어 수] | 정의
{chr(10).join(prop_lines)}

[멤버 누락 후보 — range 클래스로 이어지는데 클래스가 없는 목적어]
{chr(10).join(gaps) or '(없음)'}

[range 위반 — 목적어가 다른 클래스]
{chr(10).join(viol) or '(없음)'}

[스키마 밖 관계] {oos or '(없음)'}

[문제 트리플과 근거 청크]
{chr(10).join(prob) or '(없음)'}

{{memory_block}}처리안 종류 (이 중에서만):
- set_definition {{property, description}}: 정의 수정. 같은 유형 오류가 반복되면 개별 수정보다 이것을 먼저 — 정의는 재추출 프롬프트에 들어가 같은 오류를 막는다.
  description 은 "Domain | 관계 | Range — 무엇이 목적어이고 무엇은 아닌지" 형태.
- set_range {{property, range}} / set_domain {{property, domain}}: 클래스 이름 또는 "" (값 속성)
- add_property {{name, domain, range, description}}: 맞는 관계가 없을 때만
- add_class {{name, description, members}}: 멤버 누락 후보가 기존 클래스 어디에도 맞지 않을 때 (영어 PascalCase)
- assign_members {{class, entities}}: 멤버 누락 후보를 기존 클래스로. 문장 조각·등급 값('중간')·점수는 넣지 마라
- merge_entities {{canonical, aliases}}: 같은 개념의 다른 표기만 (반대·상하위 개념 금지 — '확장성' ≠ '확장성 요구', '용이성' ≠ '복잡도')
- move_triples {{triples: ["T0", …], target_property}}: 관계를 잘못 붙인 트리플을 다른 기존 관계로
- delete_triples {{triples: ["T0", …]}}: 근거 청크에 없는 사실이거나 의미 없는 조각

규칙: 이름은 위 목록에 있는 것만 (add_* 로 새로 만드는 이름 제외). 근거 청크를 읽고 판단하고, 근거 청크의 해당 구절을 evidence 로 짧게 인용.
확신이 없으면 내지 마라. 처리안은 최대 15개, 중요한 것부터.
JSON 만: {{"actions": [{{"type": "...", ...필드, "reason": "한 문장", "evidence": "인용 또는 ''", "confidence": 0.0~1.0}}]}}"""
    mem = ctx.get("memory") or {}
    lines = []
    if mem.get("decided"):
        lines.append("[사람이 확정한 결정 — 뒤집는 안을 내지 마라]")
        for k, v in list(mem["decided"].items())[-30:]:
            kind, prop = k.split(":", 1)
            lines.append(f"- {prop} 의 {kind} = {v.get('value') or '(값)'}")
    if mem.get("rejected"):
        lines.append("[이전에 사람이 거절한 안 — 같은 안을 다시 내지 마라]")
        for r in mem["rejected"][-40:]:
            lines.append(f"- {r['text']}" + (f" (이유: {r['reason']})" if r.get("reason") else ""))
    user = user.replace("{memory_block}", ("\n".join(lines) + "\n\n") if lines else "")
    return [{"role": "system", "content": "You are an ontology curator. Propose minimal, verifiable fixes. Output JSON only."},
            {"role": "user", "content": user}]


def known_entities(ctx: Dict[str, Any]) -> set:
    """처리안에 쓸 수 있는 엔티티 이름(정규화 키): 문제 트리플·멤버 누락·range 위반·클래스 멤버·그래프 라벨."""
    from app.services.retrieval.entity_linking import _compact
    names = set(ctx.get("entity_keys") or set())
    for t in ctx.get("problems") or []:
        names.update((_compact(t.get("subject") or ""), _compact(t.get("object") or "")))
    for items in (ctx["spec"].get("member_gaps") or {}).values():
        names.update(_compact(g["name"]) for g in items)
    names.update(_compact(v["name"]) for v in ctx["spec"].get("range_violations") or [])
    names.discard("")
    return names


def validate_actions(data: Optional[Dict[str, Any]], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """존재하는 이름만, 형식이 맞는 처리안만 채택. 트리플 참조 T0.. 는 실제 트리플로 바꾼다.
    엔티티(멤버 지정·병합·새 클래스 멤버)는 그래프에 실재하는 이름만 — 없는 이름은 빼고 dropped 에 남긴다."""
    from app.services.retrieval.entity_linking import _compact
    spec = ctx["spec"]
    ents = known_entities(ctx)
    dropped = ctx.setdefault("dropped", [])

    def real(xs):
        ok = [x for x in xs if _compact(x) in ents]
        miss = [x for x in xs if _compact(x) not in ents]
        if miss:
            dropped.append("없는 엔티티: " + ", ".join(miss[:5]))
        return ok
    classes = {c["name"] for c in spec["classes"]}
    props = {p["name"]: p for p in spec["properties"]}
    probs = ctx["problems"]
    new_classes, new_props = set(), set()
    out = []
    for a in (data or {}).get("actions") or []:
        if not isinstance(a, dict):
            continue
        t = a.get("type")
        conf = max(0.0, min(1.0, float(a.get("confidence") or 0.5)))
        base = {"id": uuid.uuid4().hex[:8], "type": t, "label": ACTION_LABEL.get(t, t),
                "reason": str(a.get("reason") or "")[:300], "evidence": str(a.get("evidence") or "")[:300],
                "confidence": round(conf, 2)}
        if t == "set_definition" and a.get("property") in props and a.get("description"):
            out.append({**base, "property": a["property"], "description": str(a["description"])[:500],
                        "before": props[a["property"]].get("description", "")})
        elif t in ("set_range", "set_domain") and a.get("property") in props:
            key = "range" if t == "set_range" else "domain"
            v = clean_class_name(a.get(key) or "")
            if v and v not in classes | new_classes:
                continue
            out.append({**base, "property": a["property"], key: v, "before": props[a["property"]].get(key, "")})
        elif t == "add_property":
            nm = clean_prop_name(a.get("name"))
            if not nm or nm in props or nm in new_props:
                continue
            d, r = clean_class_name(a.get("domain") or ""), clean_class_name(a.get("range") or "")
            if (d and d not in classes | new_classes) or (r and r not in classes | new_classes):
                continue
            new_props.add(nm)
            out.append({**base, "name": nm, "domain": d, "range": r, "description": str(a.get("description") or "")[:500]})
        elif t == "add_class":
            nm = clean_class_name(a.get("name"))
            if not nm or nm in classes or nm in new_classes:
                continue
            new_classes.add(nm)
            out.append({**base, "name": nm, "description": str(a.get("description") or "")[:300],
                        "members": real([str(x) for x in (a.get("members") or []) if str(x).strip()][:40])})
        elif t == "assign_members" and (a.get("class") in classes | new_classes):
            sel = real([str(x) for x in (a.get("entities") or []) if _compact(str(x))][:60])
            if sel:
                out.append({**base, "class": a["class"], "entities": sel})
        elif t == "merge_entities" and a.get("canonical") and a.get("aliases"):
            al = real([str(x) for x in a["aliases"] if _compact(str(x)) and _compact(str(x)) != _compact(str(a["canonical"]))])
            if al and _compact(str(a["canonical"])) not in ents:
                dropped.append(f"병합 대표 이름이 그래프에 없음: {a['canonical']}")
                al = []
            if al:
                # 한쪽 이름이 다른 쪽을 포함하면 상하위·수식 관계일 가능성 ('확장성' ⊂ '확장성 요구') → 경고·확신도 낮춤
                cc = _compact(str(a["canonical"]))
                nested = [x for x in al if cc in _compact(x) or _compact(x) in cc]
                if nested:
                    base = {**base, "confidence": min(base["confidence"], 0.4),
                            "warning": f"이름이 포함 관계({', '.join(nested)}) — 같은 개념이 아니라 상하위·수식일 수 있음"}
                out.append({**base, "canonical": str(a["canonical"]), "aliases": al[:10]})
        elif t in ("move_triples", "delete_triples"):
            refs = []
            for r in a.get("triples") or []:
                m = re.match(r"T?(\d+)$", str(r).strip())
                if m and int(m.group(1)) < len(probs):
                    refs.append(probs[int(m.group(1))])
            if not refs:
                continue
            tri = [{k: x.get(k) for k in ("subject", "predicate", "object", "source", "doc_id", "doc")} for x in refs]
            if t == "move_triples":
                tp = a.get("target_property")
                if tp not in props and tp not in new_props:
                    continue
                out.append({**base, "triples": tri, "target_property": tp})
            else:
                out.append({**base, "triples": tri})
    return filter_by_memory(out, ctx)[:15]


def filter_by_memory(actions: List[Dict[str, Any]], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """거절했던 안과 같은 안, 확정한 range·domain 을 뒤집는 안을 뺀다 (멤버·병합은 거절된 이름만 덜어 냄)."""
    mem = ctx.get("memory") or {}
    rej = {r["sig"] for r in mem.get("rejected") or []}
    decided = mem.get("decided") or {}
    dropped = ctx.setdefault("dropped", [])
    out = []
    for a in actions:
        t = a["type"]
        if t in ("set_range", "set_domain"):
            k = "range" if t == "set_range" else "domain"
            d = decided.get(f"{k}:{a['property']}")
            if d is not None and (d.get("value") or "") != (a.get(k) or ""):
                dropped.append(f"확정한 결정 번복: {a['property']} {k} {d.get('value') or '(값)'} → {a.get(k) or '(값)'}")
                continue
        if t == "assign_members":
            keep = [e for e in a["entities"] if rejection_sigs({**a, "entities": [e]})[0] not in rej]
            gone = [e for e in a["entities"] if e not in keep]
            if gone:
                dropped.append(f"거절했던 멤버 지정: {', '.join(gone)} → {a['class']}")
            if not keep:
                continue
            a = {**a, "entities": keep}
        elif t == "merge_entities":
            keep = [x for x in a["aliases"] if rejection_sigs({**a, "aliases": [x]})[0] not in rej]
            if len(keep) < len(a["aliases"]):
                dropped.append(f"거절했던 병합: {a['canonical']} ← {', '.join(x for x in a['aliases'] if x not in keep)}")
            if not keep:
                continue
            a = {**a, "aliases": keep}
        elif t in ("move_triples", "delete_triples"):
            def blocked(x):
                ts = _triple_sig(x)
                return f"keep:{ts}" in rej or (t == "move_triples" and f"move:{ts}:{a.get('target_property')}" in rej)
            keep = [x for x in a["triples"] if not blocked(x)]
            if len(keep) < len(a["triples"]):
                dropped.append(f"거절했던 트리플 {'이동' if t == 'move_triples' else '삭제'} {len(a['triples']) - len(keep)}건")
            if not keep:
                continue
            a = {**a, "triples": keep}
        else:
            sigs = rejection_sigs(a)
            if sigs and all(sg in rej for sg in sigs):
                dropped.append(f"거절했던 안: {_describe(a)}")
                continue
        out.append(a)
    return out


async def recommend(kb_id: str, scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.core.llm import achat, no_thinking_extra_body
    from app.core.models_resolver import resolve_model_config
    from app.models.knowledge_base import KnowledgeBase
    from app.services.retrieval.relation_targeting import parse_json_loose
    from app.services.schema_alignment.service import _graph_llm_config
    ctx = await collect_context(kb_id, scope)
    kb = await KnowledgeBase.get(kb_id)
    cfg = await resolve_model_config(await _graph_llm_config(kb) or (kb.llm_model_config or {}))
    if not cfg.get("model"):
        raise SchemaEditError(["추천 모델을 확인할 수 없습니다 (그래프 단계 모델 설정 필요)"])
    data = None
    for attempt in range(2):   # 응답이 비거나 해석이 안 되면 한 번 더 (가끔 빈 JSON 이 온다)
        try:
            raw = await achat(cfg, build_messages(ctx), model=cfg.get("model"), temperature=0,
                              response_format={"type": "json_object"}, extra_body=no_thinking_extra_body(cfg.get("model")),
                              timeout=300)
        except Exception as e:
            if attempt:
                raise SchemaEditError([f"추천 생성 실패: {str(e)[:200]}"], 502)
            continue
        data = parse_json_loose(raw)
        if (data or {}).get("actions"):
            break
    actions = validate_actions(data, ctx)
    rec_id = uuid.uuid4().hex[:10]
    await _log(kb_id, {"id": rec_id, "at": _now(), "model": cfg.get("model"), "scope": ("triples" if scope.get("triples") else "gaps") if scope else "schema",
                       "proposed": len(actions), "by_type": _count_types(actions), "dropped": ctx.get("dropped", [])[:10]})
    return {"id": rec_id, "model": cfg.get("model"), "version": ctx["spec"]["version"], "actions": actions,
            "dropped": ctx.get("dropped", [])[:10],
            "problems": [{k: t.get(k) for k in ("subject", "predicate", "object", "status", "source", "doc_id", "doc")}
                         for t in ctx["problems"]]}


# ---------------------------------------------------------------------------
# 가상 적용 → 재추출 미리보기 / 반영
# ---------------------------------------------------------------------------

def _apply_schema_actions(spec: Dict[str, Any], actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    spec = json.loads(json.dumps(spec))
    props = {p["name"]: p for p in spec["properties"]}
    for a in actions:
        t = a["type"]
        if t == "set_definition" and a["property"] in props:
            props[a["property"]]["description"] = a["description"]
        elif t == "set_range" and a["property"] in props:
            props[a["property"]]["range"] = a["range"]
        elif t == "set_domain" and a["property"] in props:
            props[a["property"]]["domain"] = a["domain"]
        elif t == "add_property":
            p = {"name": a["name"], "domain": a["domain"], "range": a["range"], "description": a["description"], "aliases": []}
            spec["properties"].append(p)
            props[a["name"]] = p
        elif t == "add_class":
            spec["classes"].append({"name": a["name"], "description": a["description"]})
    return spec


def _simulated_rules(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rules = []
    for a in actions:
        t = a["type"]
        if t == "assign_members":
            rules += [{"rule_type": "class", "source_value": e, "target_value": a["class"], "status": "active"} for e in a["entities"]]
        elif t == "add_class":
            rules += [{"rule_type": "class", "source_value": e, "target_value": a["name"], "status": "active"} for e in a["members"]]
        elif t == "merge_entities":
            rules += [{"rule_type": "entity", "source_value": x, "target_value": a["canonical"], "status": "active"} for x in a["aliases"]]
        elif t in ("move_triples", "delete_triples"):
            for x in a["triples"]:
                rules.append({"rule_type": "triple", "pair": [x["subject"], x["predicate"], x["object"]],
                              "target_path": a.get("target_property") if t == "move_triples" else None, "status": "active"})
    return rules


async def preview(kb_id: str, actions: List[Dict[str, Any]], problems: List[Dict[str, Any]]) -> Dict[str, Any]:
    """체크한 처리안을 가상으로 적용(스키마 덧씌우기 + 가상 규칙)해 문제 트리플의 근거 청크를 재추출 — 저장 없음."""
    from app.models.knowledge_base import KnowledgeBase
    from app.services.ingestion.ingest_client import ingest_client
    from app.services.retrieval.entity_linking import _compact
    from app.services.schema_alignment import reextract as rx
    from app.services.schema_alignment.service import rules_for_ingest
    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.schema_source not in EDITABLE_SOURCES:
        raise SchemaEditError(["텍스트(승격) KB 에서만 미리보기를 할 수 있습니다"])
    base = _spec_from_induction((kb.promotion_metadata or {}).get("induction") or {})
    spec = _norm_spec(_apply_schema_actions(base, actions))
    errors, _w = validate_spec(spec)
    if errors:
        raise SchemaEditError(["처리안을 적용한 스키마에 오류: " + "; ".join(errors[:3])])
    targets, seen_t = [], set()
    for x in list(problems) + [x for a in actions for x in (a.get("triples") or [])]:
        k = (x.get("subject"), x.get("predicate"), x.get("object"), x.get("source"))
        if x.get("source") and x.get("doc_id") and k not in seen_t:
            seen_t.add(k)
            targets.append(x)
    by_doc: Dict[str, List[str]] = {}
    for t in targets:
        ids = by_doc.setdefault(t["doc_id"], [])
        if t["source"] not in ids and sum(len(v) for v in by_doc.values()) < MAX_PREVIEW_CHUNKS:
            ids.append(t["source"])
    by_doc = {k: v for k, v in by_doc.items() if v}
    if not by_doc:
        raise SchemaEditError(["미리볼 근거 청크가 없습니다"])
    opts = await rx._model_options(kb)
    llm = opts.get("ingest") or opts.get("graph")
    full = await rx.build_schema_spec(kb, override={"classes": spec["classes"], "properties": [
        {**p, "aliases": [x for x in p["members"] if x != p["name"]]} for p in spec["properties"]]})
    rules = (await rules_for_ingest(kb_id, include_graph_rules=True)) + _simulated_rules(actions)
    out_by_chunk: Dict[str, List[Dict[str, Any]]] = {}
    failures = []
    for doc_id, node_ids in by_doc.items():
        try:
            r = await ingest_client.reextract_preview(kb_id, doc_id, node_ids, full, llm, rules)
        except Exception as e:
            failures.append({"doc_id": doc_id, "error": str(e)[:200]})
            continue
        for t in r.get("triples") or []:
            out_by_chunk.setdefault(t.get("source_node_id"), []).append(
                {k: t.get(k) for k in ("subject", "predicate", "object", "subject_type", "object_type")})

    # 문제 트리플 판정 + 재추출 결과의 range 일치 (가상 클래스 지정 포함)
    cls = await _class_index(kb_id)
    for r0 in _simulated_rules(actions):
        if r0["rule_type"] == "class":
            cls[_compact(r0["source_value"])] = r0["target_value"]
    rng = {p["name"]: p.get("range") for p in spec["properties"]}

    def k3(t):
        return (_compact(t["subject"]), _compact(t["predicate"]), _compact(t["object"]))

    results, summary = [], {"gone": 0, "kept": 0, "moved": 0}
    for t in targets:
        if t.get("source") not in sum(by_doc.values(), []):
            continue
        outs = out_by_chunk.get(t["source"]) or []
        same = [o for o in outs if k3(o) == k3(t)]
        so = [o for o in outs if (_compact(o["subject"]), _compact(o["object"])) == (_compact(t["subject"]), _compact(t["object"]))]
        res = "kept" if same else ("moved" if so else "gone")
        summary[res] += 1
        results.append({**{k: t.get(k) for k in ("subject", "predicate", "object", "doc")}, "result": res,
                        **({"new_predicate": so[0]["predicate"]} if res == "moved" else {})})
    fit = {"ok": 0, "bad": 0}
    for outs in out_by_chunk.values():
        for o in outs:
            r = rng.get(o["predicate"])
            if r:
                fit["ok" if cls.get(_compact(o["object"])) == r else "bad"] += 1
    return {"model": llm.get("model") if llm else None, "chunks": sum(len(v) for v in by_doc.values()),
            "summary": summary, "results": results, "range_fit": fit, "chunk_triples": out_by_chunk,
            "rules_simulated": len(_simulated_rules(actions)), "failures": failures[:5]}


async def apply(kb_id: str, actions: List[Dict[str, Any]], base_version: Optional[int] = None,
                rec_id: Optional[str] = None, outcome: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """승인한 처리안 반영: 스키마 변경을 한 번에 저장 → 규칙(class·entity·triple) 생성 → 리플레이 1회."""
    from app.models.knowledge_base import KnowledgeBase
    from app.models.schema_mapping import SchemaMappingRule
    from app.services.retrieval.entity_linking import _compact
    from app.services.schema_alignment.schema_editor import _replay_text_docs, save_spec
    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.schema_source not in EDITABLE_SOURCES:
        raise SchemaEditError(["텍스트(승격) KB 에서만 반영할 수 있습니다"])
    meta = kb.promotion_metadata or {}
    ver = int(meta.get("schema_version") or 1)
    if base_version is not None and int(base_version) != ver:
        raise SchemaEditError([f"추천 이후 스키마가 바뀌었습니다 (현재 버전 {ver}) — 다시 추천받으세요"], 409)
    schema_acts = [a for a in actions if a["type"] in SCHEMA_ACTIONS]
    saved = None
    if schema_acts:
        spec = _apply_schema_actions(_spec_from_induction(meta.get("induction") or {}), schema_acts)
        saved = await save_spec(kb_id, spec, base_version=ver, replay=False,
                                note=f"AI 추천 {len(schema_acts)}건 반영")
    created = 0
    existing_cls = {_compact(r.source_value): r for r in await SchemaMappingRule.find(
        SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "class").to_list() if r.source_value}
    for r0 in _simulated_rules(actions):
        origin = "schema_editor:ai"
        if r0["rule_type"] == "class":
            ex = existing_cls.get(_compact(r0["source_value"]))
            if ex:
                ex.target_value, ex.status = r0["target_value"], "active"
                await ex.save()
            else:
                await SchemaMappingRule(kb_id=kb_id, rule_type="class", source_value=r0["source_value"],
                                        target_value=r0["target_value"], origin=origin).insert()
        elif r0["rule_type"] == "entity":
            # 대표 이름을 되바꾸는 기존 규칙은 끈다 (merge_entities 와 같은 처리)
            for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.status == "active").to_list():
                if r.rule_type in ("entity", "value") and r.source_value and \
                        _compact(r.source_value) == _compact(r0["target_value"]) and _compact(r.target_value or "") != _compact(r0["target_value"]):
                    r.status = "disabled"
                    await r.save()
            await SchemaMappingRule(kb_id=kb_id, rule_type="entity", source_value=r0["source_value"],
                                    target_value=r0["target_value"], origin=origin).insert()
        else:
            ex = await SchemaMappingRule.find_one(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.rule_type == "triple",
                                                  SchemaMappingRule.pair == r0["pair"])
            if ex:
                ex.target_path, ex.status = r0["target_path"], "active"
                await ex.save()
            else:
                await SchemaMappingRule(kb_id=kb_id, rule_type="triple", pair=r0["pair"], target_path=r0["target_path"],
                                        origin=origin).insert()
        created += 1
    kb = await KnowledgeBase.get(kb_id)
    if created:
        kb.schema_rules_version = (kb.schema_rules_version or 0) + 1
        await kb.save()
    rp = await _replay_text_docs(kb_id) if (created or schema_acts) else {"replayed": 0, "errors": []}
    mem_n = await remember(kb_id, (outcome or {}).get("rejected_actions") or [], actions)
    if rec_id:
        o = outcome or {}
        await _log(kb_id, {"id": rec_id, "applied_at": _now(), "accepted": len(actions),
                           "accepted_by_type": _count_types(actions),
                           "edited": sum(1 for a in actions if a.get("edited")),
                           "rejected": o.get("rejected"), "proposed_seen": o.get("proposed"),
                           "preview": o.get("preview"), "version_after": (saved or {}).get("version", ver)})
    return {"schema_saved": bool(saved and saved.get("saved")), "version": (saved or {}).get("version", ver),
            "rules_created": created, "remembered": mem_n, **rp,
            "reextract_recommended": any(a["type"] in ("set_definition", "set_range", "set_domain", "add_property")
                                         for a in schema_acts)}



async def reject(kb_id: str, rec_id: Optional[str], rejected: List[Dict[str, Any]], proposed: Optional[int] = None) -> Dict[str, Any]:
    """반영 없이 거절만 기록 (패널에서 '거절 기록하고 닫기')."""
    n = await remember(kb_id, rejected, [])
    if rec_id:
        await _log(kb_id, {"id": rec_id, "closed_at": _now(), "accepted": 0, "rejected": len(rejected), "proposed_seen": proposed})
    return {"remembered": n}


async def get_memory(kb_id: str) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    mem = ((kb.promotion_metadata or {}).get("ai_recommend_memory") or {}) if kb else {}
    return {"rejected": list(reversed(mem.get("rejected") or [])), "decided": mem.get("decided") or {}}


async def forget(kb_id: str, sig: Optional[str] = None, decided_key: Optional[str] = None) -> Dict[str, Any]:
    """기억 항목 지우기 (거절을 취소하거나 확정 결정을 풀 때)."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    meta = dict(kb.promotion_metadata or {})
    mem = dict(meta.get("ai_recommend_memory") or {})
    if sig:
        mem["rejected"] = [r for r in mem.get("rejected") or [] if r["sig"] != sig]
    if decided_key:
        mem["decided"] = {k: v for k, v in (mem.get("decided") or {}).items() if k != decided_key}
    meta["ai_recommend_memory"] = mem
    kb.promotion_metadata = meta
    await kb.save()
    return {"ok": True}
