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


def _sentences(text: str, a: str, b: str) -> List[str]:
    """양끝(또는 한쪽)이 나오는 문장. 이름은 공백·조사 차이를 견디게 핵심 토큰으로 찾는다."""
    from app.services.agent_query.lexicon import _compact
    sents = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text or "") if s.strip()]

    def has(s: str, name: str) -> bool:
        toks = [t for t in re.split(r"[\s·\-_()]+", name or "") if len(_compact(t)) >= 2]
        cs = _compact(s)
        return bool(toks) and any(_compact(t) in cs for t in toks)

    both = [s for s in sents if has(s, a) and has(s, b)]
    one = [s for s in sents if (has(s, a) or has(s, b)) and s not in both]
    return (both + one)[:MAX_SENTENCES]


async def run_audit(kb_id: str, properties: Optional[Sequence[str]] = None, limit_per_property: int = 200) -> Dict[str, Any]:
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
    if properties:
        targets = [props[n] for n in properties if n in props]
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
    # 근거 문장
    srcs = list({i["source"] for i in items if i.get("source")})
    texts: Dict[str, str] = {}
    for k in range(0, len(srcs), 50):
        r = await catalog.get_chunks(kb_id, srcs[k:k + 50], 4000)
        texts.update({c["id"]: c["text"] for c in r["chunks"]})
    for i in items:
        i["evidence"] = _sentences(texts.get(i.get("source"), ""), i["subject"], i["object"])

    defs = "\n".join(f"- {p['name']}: {p.get('description') or '(정의 없음)'}" for p in targets)

    async def judge(batch: List[Dict[str, Any]], offset: int) -> None:
        lines = []
        for n, i in enumerate(batch):
            ev = " / ".join(i["evidence"]) or "(근거 문장 없음)"
            lines.append(f"{offset + n}. ({i['subject']}, {i['predicate']}, {i['object']}) — 원문: {ev}")
        msg = PROMPT.format(definitions=defs, items="\n".join(lines))
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

    from collections import Counter
    summary = {p["name"]: dict(Counter(i["verdict"] for i in items if i["predicate"] == p["name"])) for p in targets}
    result = {
        "status": "done", "at": datetime.utcnow().isoformat(), "model": cfg.get("model"),
        "properties": [p["name"] for p in targets], "summary": summary,
        "items": items, "elapsed_s": round(time.time() - t0, 1),
    }
    meta = dict(kb.promotion_metadata or {})
    meta["direction_audit"] = result
    kb.promotion_metadata = meta
    await kb.save()
    return {k: v for k, v in result.items() if k != "items"} | {"total": len(items)}


async def get_audit(kb_id: str) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    return ((kb.promotion_metadata or {}).get("direction_audit")) or {"status": "none"}
