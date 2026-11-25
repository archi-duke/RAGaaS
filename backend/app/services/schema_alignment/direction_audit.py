"""관계 방향 검증 (데이터 품질 D1, 2026-11-16).

같은 클래스끼리 잇는 관계(Person→Person, TheoryOrConcept→TheoryOrConcept)는 domain·range 검사로
방향 오류를 잡을 수 없다. 스키마 정의에 방향이 적혀 있어도 추출이 반대로 넣은 트리플이 있다
(물리학사: '아인슈타인 영향_줌 뉴턴', '특수 상대론 계승_발전 뉴턴 역학').

트리플마다 근거 청크에서 양끝이 나오는 문장을 뽑아, 관계 정의와 함께 LLM 에 판정시킨다.
  forward   — 정의 방향 그대로 맞음
  reverse   — 관계는 맞는데 주어·목적어가 반대
  unrelated — 이 관계가 아님 (다른 관계이거나 근거 없음)
  unsure    — 문장으로 판단 불가
결과는 KB 에 저장만 한다. 적용(뒤집기·삭제)은 사람이 검토 후 edit_triples(action=flip|delete) 로.

범위 확대 (근거 검증, 2026-11-25 — 추출 품질 후속 B):
  scope="all" 이면 같은 클래스끼리 잇는 관계뿐 아니라 모든 관계를 판정한다. 문자열 근거 검사(PR #73, 적재 단계)는
  '목적어 단어가 청크에 있는가' 만 보므로, 단어는 있는데 관계가 틀린 트리플은 여기서 잡는다.
  auto_apply 는 근거 없는 트리플을 자동으로 뺀다 (scope=all 에서는 reverse 자동 뒤집기를 하지 않는다 — 검토 목록만) — 조건(모두 만족):
    근거 청크와 같은 문서 어디에도 목적어(규칙의 원래 표기 포함)가 없음 + unrelated 판정 + 두 번째 판정도 none.
  빼는 것은 triple 삭제 규칙(origin=auto_grounding)이라 규칙 목록에서 되돌릴 수 있다. 나머지 unrelated 는 사람 검토.
  scope 는 결과에 저장되어 이후 자동 증분 검증도 같은 범위로 돈다.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

BATCH = 15
MAX_SENTENCES = 3

PROMPT = """너는 지식 그래프 트리플의 **방향**을 원문으로 검증한다.

관계 정의:
{definitions}

아래 각 항목은 (주어, 관계, 목적어)와 그 트리플을 뽑은 원문 문장이다.
원문을 근거로 판정하라:
- forward: 정의 방향 그대로 맞다 (예: 정의가 'A 영향_줌 B = A 가 B 에게 영향'이고 원문도 A 가 B 에게 영향을 줌)
- reverse: 이 관계는 맞는데 주어와 목적어가 반대다 (원문은 B 가 A 에게 영향)
- unrelated: 원문상 이 관계가 아니다 (다른 관계, 관계 아님, 목적어가 엉뚱한 값)
- unsure: 원문만으로 판단할 수 없다
추측하지 말고 원문 문장에 있는 것만 근거로 삼아라. reason 은 한 줄, 원문 표현을 인용.

항목:
{items}

JSON 만: {{"results": [{{"id": 번호, "verdict": "forward|reverse|unrelated|unsure", "reason": "..."}}]}}"""


def _name_tokens(name: str) -> List[str]:
    """이름의 핵심 토큰 — 2자 이상 토큰, 없으면(한 글자 이름 '줄') 그 토큰 그대로.
    한 글자 이름을 버리면 근거 문장을 못 찾아 판정이 틀린다 (평가: '크뢰벨 영향_줌 줄' 을 '관계 아님' 으로)."""
    from app.services.agent_query.lexicon import _compact
    raw = [t for t in re.split(r"[\s·\-_()]+", name or "") if _compact(t)]
    long_ = [t for t in raw if len(_compact(t)) >= 2]
    return long_ or raw


def _sentences(text: str, a: str, b: str, aliases: Optional[Dict[str, List[str]]] = None,
               limit: int = MAX_SENTENCES) -> List[str]:
    """양끝(또는 한쪽)이 나오는 문장. 이름은 공백·조사 차이를 견디게 핵심 토큰으로 찾는다.
    aliases: 정규화된 표기 → 원래 표기 ('Availability' → ['가용성']) — 원문은 원래 표기로 쓰여 있다.
    한쪽만 나오는 문장은 목적어(b) 쪽을 먼저 — 주어는 문서 제목에서 복원되는 일이 많아 목적어 문장이 근거다."""
    from app.services.agent_query.lexicon import _compact
    sents = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text or "") if s.strip()]
    al = aliases or {}

    def has(s: str, name: str) -> bool:
        cs = _compact(s)
        for nm in [name] + list(al.get(_compact(name), [])):
            toks = _name_tokens(nm)
            if toks and any(_compact(t) in cs for t in toks):
                return True
        return False

    both = [s for s in sents if has(s, a) and has(s, b)]
    obj = [s for s in sents if has(s, b) and s not in both]
    subj = [s for s in sents if has(s, a) and s not in both and s not in obj]
    return (both + obj + subj)[:limit]


async def _alias_index(kb_id: str) -> Dict[str, List[str]]:
    """value·entity 규칙(source → target)에서 정규화된 표기 → 원래 표기들."""
    from app.models.schema_mapping import SchemaMappingRule
    from app.services.agent_query.lexicon import _compact
    idx: Dict[str, List[str]] = {}
    rules = await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id, SchemaMappingRule.status == "active").to_list()
    for r in rules:
        if r.rule_type in ("value", "entity") and r.source_value and r.target_value:
            idx.setdefault(_compact(r.target_value), []).append(str(r.source_value))
    return idx


def _object_in_text(i: Dict[str, Any], text: str, aliases: Dict[str, List[str]]) -> bool:
    """목적어(또는 그 원래 표기)의 핵심 토큰이 근거 청크 원문에 하나라도 있는가."""
    from app.services.agent_query.lexicon import _compact
    ct = _compact(text or "")
    for nm in [i["object"]] + list(aliases.get(_compact(i["object"]), [])):
        if any(_compact(t) and _compact(t) in ct for t in _name_tokens(nm)):
            return True
    return False


def _key(i: Dict[str, Any]):
    from app.services.agent_query.lexicon import _compact
    return (_compact(i["subject"]), i["predicate"], _compact(i["object"]))


def _both_in_evidence(i: Dict[str, Any]) -> bool:
    """자동 뒤집기 조건: 근거 문장 하나에 양끝이 모두 나온다 (한쪽만 나오면 사람 검토)."""
    from app.services.agent_query.lexicon import _compact

    def has(sent: str, name: str) -> bool:
        toks = _name_tokens(name)
        return bool(toks) and any(_compact(t) in _compact(sent) for t in toks)
    return any(has(e, i["subject"]) and has(e, i["object"]) for e in i.get("evidence") or [])


async def run_audit(kb_id: str, properties: Optional[Sequence[str]] = None, limit_per_property: int = 200,
                    incremental: bool = False, auto_apply: bool = False,
                    scope: Optional[str] = None) -> Dict[str, Any]:
    """incremental: 이전 검증에 있던 트리플은 다시 판정하지 않는다 (새로 들어온 것만).
    auto_apply: 새로 판정한 것 중 reverse 이고 근거 문장 하나에 양끝이 모두 나오는 것만 자동으로 뒤집는다
    (triple 규칙 origin=auto_direction — 규칙 목록에서 되돌릴 수 있음). 나머지는 화면에서 사람이 검토."""
    from app.core.llm import achat, no_thinking_extra_body
    from app.models.knowledge_base import KnowledgeBase
    from app.services.agent_query import catalog
    from app.services.agent_query.lexicon import _llm_cfg
    from app.services.retrieval.relation_targeting import parse_json_loose
    from app.services.schema_alignment.schema_editor import get_spec, property_triples

    t0 = time.time()
    kb = await KnowledgeBase.get(kb_id)
    spec = await get_spec(kb_id)
    props = {p["name"]: p for p in spec.get("properties") or []}
    prev = ((kb.promotion_metadata or {}).get("direction_audit") or {})
    scope = scope or prev.get("scope") or "same_class"
    if properties:
        targets = [props[n] for n in properties if n in props]
    elif scope == "all":
        targets = list(props.values())
    else:
        # 같은 클래스끼리 잇는 관계 — domain·range 검사로 방향을 못 잡는 것
        targets = [p for p in props.values() if p.get("domain") and p.get("domain") == p.get("range")]
    if not targets:
        return {"status": "empty", "message": "검증할 관계가 없음 (domain == range 인 관계 없음)"}
    cfg = await _llm_cfg(kb)

    items: List[Dict[str, Any]] = []
    for p in targets:
        tr = await property_triples(kb_id, p["name"], limit_per_property)
        for t in tr.get("triples") or []:
            items.append({"subject": t["subject"], "predicate": p["name"], "object": t["object"],
                          "source": t.get("source"), "doc": t.get("doc")})
    prev_items = list(prev.get("items") or [])
    if incremental and prev_items:
        known = {_key(i) for i in prev_items}
        # 자동·수동으로 뒤집은 트리플은 뒤집힌 모양으로 다시 나타난다 — 그것도 판정 끝난 것으로
        known |= {(_key(i)[2], i["predicate"], _key(i)[0]) for i in prev_items if i.get("applied") == "flip"}
        items = [i for i in items if _key(i) not in known]
    if not items:
        return {"status": "done", "new": 0, "message": "새로 판정할 트리플 없음", "total": len(prev_items)}
    # 근거 문장
    srcs = list({i["source"] for i in items if i.get("source")})
    texts: Dict[str, str] = {}
    for k in range(0, len(srcs), 50):
        r = await catalog.get_chunks(kb_id, srcs[k:k + 50], 4000)
        texts.update({c["id"]: c["text"] for c in r["chunks"]})
    aliases = await _alias_index(kb_id)
    for i in items:
        i["evidence"] = _sentences(texts.get(i.get("source"), ""), i["subject"], i["object"], aliases,
                                   limit=MAX_SENTENCES + (2 if scope == "all" else 0))
        # 근거 청크 원문에 목적어(원래 표기 포함)가 아예 없는가 — 자동 제외의 필수 조건
        i["object_in_source"] = _object_in_text(i, texts.get(i.get("source"), ""), aliases) if i.get("source") in texts else True

    # 묶음마다 그 묶음에 나오는 관계의 정의만 넣는다 (11/25: 정의 ~50개를 한꺼번에 넣자 '기반함'·'계승_발전' 을
    # 정의와 반대로 읽어 정방향 17건을 reverse 로 판정·자동 뒤집기 → 되돌림). 같은 관계끼리 묶이게 정렬한다.
    def_of = {p["name"]: p.get("description") or "(정의 없음)" for p in targets}

    def defs_for(batch: List[Dict[str, Any]]) -> str:
        return "\n".join(f"- {n}: {def_of.get(n, '(정의 없음)')}" for n in dict.fromkeys(i["predicate"] for i in batch))

    items.sort(key=lambda i: i["predicate"])

    async def judge(batch: List[Dict[str, Any]], offset: int) -> None:
        lines = []
        for n, i in enumerate(batch):
            ev = " / ".join(i["evidence"]) or "(근거 문장 없음)"
            lines.append(f"{offset + n}. ({i['subject']}, {i['predicate']}, {i['object']}) — 원문: {ev}")
        msg = PROMPT.format(definitions=defs_for(batch), items="\n".join(lines))
        data = None
        for _ in range(2):
            raw = await achat(cfg, [{"role": "user", "content": msg}], model=cfg.get("model"), temperature=0,
                              max_tokens=4000, response_format={"type": "json_object"},
                              extra_body=no_thinking_extra_body(cfg.get("model")))
            data = parse_json_loose(raw)
            if isinstance(data, dict) and data.get("results"):
                break
        got = {int(r.get("id", -1)): r for r in (data or {}).get("results") or [] if isinstance(r, dict)}
        for n, i in enumerate(batch):
            r = got.get(offset + n) or {}
            v = str(r.get("verdict") or "unsure").lower()
            i["verdict"] = v if v in ("forward", "reverse", "unrelated", "unsure") else "unsure"
            i["reason"] = str(r.get("reason") or "")[:300]

    await asyncio.gather(*(judge(items[k:k + BATCH], k) for k in range(0, len(items), BATCH)))

    applied = removed = 0
    if auto_apply:
        # 모든 관계 범위(scope=all)에서는 방향 자동 뒤집기를 하지 않는다 — 11/25 물리학사: 관계 이름과 정의 방향이
        # 엇갈리는 '계승_발전'(정의: A 계승_발전 B = B 가 A 를 이어받음)을 두 판정 모두 반대로 읽어 정방향을 뒤집었다.
        # reverse 판정은 검토 목록으로만 남긴다. (같은 클래스 범위의 기존 동작은 그대로)
        cands = [] if scope == "all" else \
            [i for i in items if i["verdict"] == "reverse" and _both_in_evidence(i) and not i.get("previously")]
        conf = await confirm_orientation(cfg, defs_for, cands) if cands else {}
        flips = []
        for n, i in enumerate(cands):
            i["confirm"] = conf.get(n, "none")
            if i["confirm"] == "B":
                flips.append(i)
        if flips:
            from app.services.schema_alignment.schema_editor import edit_triples
            await edit_triples(kb_id, "flip", [{"subject": i["subject"], "predicate": i["predicate"], "object": i["object"]}
                                               for i in flips], origin="auto_direction")
            for i in flips:
                i["applied"] = "flip"
                i["applied_by"] = "auto"
            applied = len(flips)
        # 근거 없는 트리플 자동 제외 (두 판정이 모두 '근거 없음' 이고 양끝이 한 문장에 함께 나오지 않을 때만)
        # 자동 제외는 '원문에 목적어가 아예 없는' 트리플만 (11/24 CQRS→가용성 유형). 목적어가 원문에 있는데
        # 관계가 틀렸다는 판정은 근거 문장 선택에 따라 흔들려(11/25 첫 실행: 원문에 있는 '가용성 긍정 효과' 까지 뺌) 사람 검토로 남긴다.
        ung = [i for i in items if i["verdict"] == "unrelated" and not i.get("object_in_source", True)
               and not _both_in_evidence(i) and not i.get("previously")]
        if ung:
            # 같은 문서의 다른 청크에 목적어가 있으면 빼지 않는다 — 사실은 맞고 근거 청크만 잘못 붙은 경우가 많다
            # (11/25 두 번째 실행: 'Event-Driven 결합도 분리(decoupling) 강한 긍정' 이 다른 청크 근거로 붙어 빠질 뻔함)
            doc_text: Dict[str, str] = {}
            ids = list({i["source"] for i in ung if i.get("source")})
            for k in range(0, len(ids), 20):
                r = await catalog.get_chunks(kb_id, ids[k:k + 20], 8000, expand_doc=True)
                by_doc: Dict[str, List[str]] = {}
                for c in list(r["chunks"]) + list(r.get("same_doc_chunks") or []):
                    by_doc.setdefault(str(c.get("doc") or ""), []).append(c.get("text") or "")
                for c in r["chunks"]:
                    doc_text[c["id"]] = "\n".join(by_doc.get(str(c.get("doc") or ""), []))
            for i in ung:
                i["object_in_doc"] = _object_in_text(i, doc_text.get(i.get("source"), ""), aliases)
            ung = [i for i in ung if not i["object_in_doc"]]
            # 영어 목적어에 원래 표기(규칙 별칭)가 없으면 빼지 않는다 — 추출이 한글 원문을 영어로 옮긴 값은
            # 문자열로 찾을 수 없다 (11/25: 'Clean Architecture is_suitable_for high domain complexity' — 원문 '도메인 복잡도가 높고')
            from app.services.agent_query.lexicon import _compact
            for i in ung:
                i["translated_unaliased"] = bool(re.search(r"[A-Za-z]", i["object"])) \
                    and not re.search(r"[가-힣]", i["object"]) and _compact(i["object"]) not in aliases
            ung = [i for i in ung if not i["translated_unaliased"]]
        conf_u = await confirm_orientation(cfg, defs_for, ung) if ung else {}
        drops = []
        for n, i in enumerate(ung):
            i["confirm"] = conf_u.get(n, "none")
            if i["confirm"] == "NONE":
                drops.append(i)
        if drops:
            from app.services.schema_alignment.schema_editor import edit_triples
            await edit_triples(kb_id, "delete", [{"subject": i["subject"], "predicate": i["predicate"], "object": i["object"]}
                                                 for i in drops], origin="auto_grounding")
            for i in drops:
                i["applied"] = "delete"
                i["applied_by"] = "auto"
        removed = len(drops)
    for i in items:
        i["audited_at"] = datetime.utcnow().isoformat()
    if incremental:
        items = prev_items + items
    else:
        # 전체 재검증: 앞서 적용한 뒤집기·삭제 표시는 유지 (뒤집힌 트리플은 이제 정방향으로 다시 판정된다)
        done = {_key(i): i for i in prev_items if i.get("applied")}
        done |= {(_key(i)[2], i["predicate"], _key(i)[0]): i for i in prev_items if i.get("applied") == "flip"}
        for i in items:
            p_ = done.get(_key(i))
            if p_ is not None:
                i["previously"] = {"verdict": p_["verdict"], "applied": p_["applied"], "applied_by": p_.get("applied_by")}
    from collections import Counter
    summary = {p["name"]: dict(Counter(i["verdict"] for i in items if i["predicate"] == p["name"])) for p in targets}
    result = {
        "status": "done", "at": datetime.utcnow().isoformat(), "model": cfg.get("model"),
        "properties": [p["name"] for p in targets], "summary": summary,
        "items": items, "elapsed_s": round(time.time() - t0, 1),
        "auto_applied": applied, "auto_removed": removed, "scope": scope,
        "mode": "incremental" if incremental else "full",
    }
    meta = dict(kb.promotion_metadata or {})
    meta["direction_audit"] = result
    kb.promotion_metadata = meta
    await kb.save()
    return {k: v for k, v in result.items() if k != "items"} | {"total": len(items)}


CONFIRM_PROMPT = """관계 정의:
{definitions}

각 항목에 원문 문장과 두 가지 방향이 있다. 원문과 관계 정의에 맞는 방향을 고르라.
- A: (주어, 관계, 목적어) 그대로
- B: 주어와 목적어를 바꾼 것
- none: 어느 쪽도 원문으로 뒷받침되지 않음
정의의 방향(누가 누구에게)을 원문 문장의 실제 행위자와 대조하라.

{items}

JSON 만: {{"results": [{{"id": 번호, "choice": "A|B|none"}}]}}"""


async def confirm_orientation(cfg, defs, items: List[Dict[str, Any]]) -> Dict[int, str]:
    """두 번째 판정: 방향 A/B 를 직접 고르게 한다 (첫 판정과 다른 질문 형식). 자동 뒤집기는 두 판정이 일치할 때만.
    defs: 정의 문자열, 또는 묶음을 받아 그 묶음의 정의를 돌려주는 함수.
    평가: 첫 판정이 근거로는 '헬름홀츠가 헤르츠에게 영향'(정방향)이라 쓰고 verdict 는 reverse 로 낸 사례."""
    from app.core.llm import achat, no_thinking_extra_body
    from app.services.retrieval.relation_targeting import parse_json_loose
    out: Dict[int, str] = {}
    for k in range(0, len(items), BATCH):
        lines = []
        for n, i in enumerate(items[k:k + BATCH]):
            ev = " / ".join(i.get("evidence") or []) or "(근거 문장 없음)"
            lines.append(f"{k + n}. A=({i['subject']}, {i['predicate']}, {i['object']})  "
                         f"B=({i['object']}, {i['predicate']}, {i['subject']}) — 원문: {ev}")
        raw = await achat(cfg, [{"role": "user", "content": CONFIRM_PROMPT.format(
            definitions=defs(items[k:k + BATCH]) if callable(defs) else defs, items="\n".join(lines))}],
                          model=cfg.get("model"), temperature=0, max_tokens=2000, response_format={"type": "json_object"},
                          extra_body=no_thinking_extra_body(cfg.get("model")))
        for r in ((parse_json_loose(raw) or {}).get("results") or []):
            try:
                out[int(r.get("id"))] = str(r.get("choice") or "none").strip().upper()
            except (TypeError, ValueError):
                pass
    return out


async def get_audit(kb_id: str) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    return ((kb.promotion_metadata or {}).get("direction_audit")) or {"status": "none"}


async def mark_applied(kb_id: str, triples: Sequence[Dict[str, str]], action: str, by: str = "user") -> None:
    """화면에서 사람이 뒤집기·삭제한 트리플을 검증 결과에 표시 (다음 증분 검증이 다시 판정하지 않게)."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    meta = dict(kb.promotion_metadata or {})
    au = meta.get("direction_audit") or {}
    keys = {_key({"subject": t["subject"], "predicate": t["predicate"], "object": t["object"]}) for t in triples}
    n = 0
    for i in au.get("items") or []:
        if _key(i) in keys:
            i["applied"], i["applied_by"] = action, by
            n += 1
    if n:
        meta["direction_audit"] = au
        kb.promotion_metadata = meta
        await kb.save()


_AUTO_LAST: Dict[str, float] = {}


async def auto_audit_if_enabled(kb_id: str, reason: str) -> None:
    """그래프가 바뀌면(재추출 완료·카탈로그 지문 변경) 새 트리플만 방향 검증 + reverse 자동 뒤집기.
    방향 검증을 한 번이라도 실행한 KB 에만 (원치 않는 LLM 비용 방지). 10분에 한 번까지."""
    import logging
    log = logging.getLogger(__name__)
    try:
        from app.models.knowledge_base import KnowledgeBase
        kb = await KnowledgeBase.get(kb_id)
        if not kb or not ((kb.promotion_metadata or {}).get("direction_audit") or {}).get("items"):
            return
        if time.time() - _AUTO_LAST.get(kb_id, 0) < 600:
            return
        _AUTO_LAST[kb_id] = time.time()
        r = await run_audit(kb_id, incremental=True, auto_apply=True)
        log.info("[DirectionAudit] auto (%s) kb=%s new=%s auto_flipped=%s auto_removed=%s", reason, kb_id,
                 r.get("total"), r.get("auto_applied"), r.get("auto_removed"))
    except Exception as e:      # 검색·재추출을 막지 않는다
        log.warning("[DirectionAudit] auto skipped: %s", e)
