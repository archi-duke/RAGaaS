"""답변 근거 검사 — 답변 문장이 검색 근거(청크·트리플)에 있는가 (추출 품질 후속 C, 2026-11-25).

그래프가 맞아도 답변 LLM 이 문맥에 없는 말(장단점·수치·조건)을 덧붙일 수 있다.
답변을 만든 뒤 문장마다 근거 문맥과 대조해 판정한다:
  supported   — 문맥에 있는 내용 (말을 바꿔도 뜻이 같으면 포함)
  unsupported — 문맥에 없는 사실 주장
  not_claim   — 사실 주장이 아님 (머리말·정리 문장·'가정:' 으로 밝힌 문장·인용 안내)

파이프라인의 'answer_check' 카드가 있을 때만 돈다 (맨 끝, 답변 뒤). 카드 옵션:
  llm_model — 검사 모델 (없으면 답변 모델)
  action    — mark(표시만, 기본) | remove(근거 없는 문장을 답변에서 뺀다)
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

STAGE = "answer_check"
MAX_CONTEXT = 12000
MAX_SENTENCES = 40

PROMPT = """너는 답변 검사기다. 아래 '근거 문맥' 만 보고, 답변의 각 문장이 근거에 있는 내용인지 판정하라.
- supported: 근거 문맥에 있는 내용이다 (표현이 달라도 뜻이 같으면 supported)
- unsupported: 근거 문맥에 없는 사실 주장이다 (근거에 없는 수치·조건·장단점·관계를 단정)
- not_claim: 사실 주장이 아니다 (머리말 '다음과 같습니다', 정리·안내 문장, '가정:' 으로 밝힌 문장, 인용 표기만 있는 문장,
  '문맥에 ~ 정보가 없다 / 알 수 없다' 처럼 근거가 없음을 밝히는 문장)
일반 상식이라도 근거 문맥에 없으면 unsupported 다. reason 은 한 줄로, unsupported 면 근거에 무엇이 없는지 적어라.

근거 문맥:
{context}

답변 문장:
{sentences}

JSON 만: {{"results": [{{"id": 번호, "verdict": "supported|unsupported|not_claim", "reason": "..."}}]}}"""


def stage_of(pipeline: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next((s for s in ((pipeline or {}).get("stages") or [])
                 if isinstance(s, dict) and s.get("type") == STAGE), None)


def split_sentences(answer: str) -> List[str]:
    """답변을 판정 단위로 나눈다 — 줄 단위, 긴 줄은 문장 끝(다.·요.·. )에서 다시 나눈다."""
    out: List[str] = []
    for line in (answer or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        # 목록 번호('1. ')는 자르지 않는다 — 마침표 앞이 숫자가 아닐 때만 문장 끝
        parts = re.split(r"(?<=[다요음함]\.)\s+|(?<=[^\d\s][.!?])\s+(?=[가-힣A-Z\[(*])", line)
        out.extend(p.strip() for p in parts if p.strip())
    return out


def _skip(sentence: str) -> bool:
    """판정할 필요가 없는 줄 — 짧은 머리말·구분선·인용 안내."""
    s = re.sub(r"[\s*#>\-|:]+", "", sentence)
    return len(s) < 6 or bool(re.fullmatch(r"(\[Chunk\d+\],?)+", s))


async def check_answer(answer: str, context: str, cfg: Dict[str, Any], action: str = "mark") -> Dict[str, Any]:
    from app.core.llm import achat, no_thinking_extra_body
    from app.services.retrieval.relation_targeting import parse_json_loose

    t0 = time.time()
    sents = split_sentences(answer)
    idx = [n for n, s in enumerate(sents) if not _skip(s)][:MAX_SENTENCES]
    if not idx:
        return {"checked": 0, "unsupported": [], "action": action, "sec": 0.0}
    lines = "\n".join(f"{n}. {sents[n]}" for n in idx)
    raw = await achat(cfg, [{"role": "user", "content": PROMPT.format(context=(context or "")[:MAX_CONTEXT],
                                                                      sentences=lines)}],
                      model=cfg.get("model"), temperature=0, max_tokens=3000,
                      response_format={"type": "json_object"}, extra_body=no_thinking_extra_body(cfg.get("model")))
    got = {}
    for r in ((parse_json_loose(raw) or {}).get("results") or []):
        try:
            got[int(r.get("id"))] = r
        except (TypeError, ValueError):
            pass
    unsupported = []
    for n in idx:
        r = got.get(n) or {}
        if str(r.get("verdict") or "").lower() == "unsupported":
            unsupported.append({"n": n, "sentence": sents[n], "reason": str(r.get("reason") or "")[:300]})
    out: Dict[str, Any] = {"checked": len(idx), "judged": len(got), "unsupported": unsupported,
                           "action": action, "model": cfg.get("model"), "sec": round(time.time() - t0, 1)}
    if action == "remove" and unsupported:
        drop = {u["n"] for u in unsupported}
        kept = [s for n, s in enumerate(sents) if n not in drop]
        out["answer"] = "\n".join(kept) + f"\n\n(근거 문맥에 없는 문장 {len(drop)}개를 답변에서 뺐습니다.)"
    return out


def log_lines(res: Dict[str, Any]) -> List[str]:
    if not res.get("checked"):
        return ["[AnswerCheck] 판정할 문장 없음"]
    head = (f"[AnswerCheck] 답변 {res['checked']}문장 중 근거 없음 {len(res['unsupported'])}개 "
            f"({res.get('model')}, {res.get('sec')}s, {'답변에서 뺌' if res.get('answer') else '표시만'})")
    return [head] + [f"[AnswerCheck] ✗ {u['sentence'][:120]} — {u['reason'][:120]}" for u in res["unsupported"]]
