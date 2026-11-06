"""
Subject Restoration Preprocessing Module

Resolves omitted subjects in Korean text using LLM.
Example: "이며 Duke의 제자이다" → "오일남은 Duke의 제자이다"

문서 전체를 한 번에 보내면 출력 토큰 한도(gpt-4o-mini 16,384 등)를 넘으므로,
문단 경계로 나눈 조각을 병렬로 복원해 이어 붙인다.
"""
import asyncio
from typing import Optional, Dict, Any, List

from app.core.llm import achat, LLMError


SYSTEM_PROMPT = """당신은 한국어 텍스트 전처리 전문가입니다.
주어진 텍스트에서 **생략된 주어를 복원**하는 작업을 수행합니다.

규칙:
1. "이며", "그리고", "또한" 등으로 연결된 문장에서 생략된 주어를 앞 문장에서 찾아 명시적으로 추가합니다.
2. 인물 설명 문단에서 주어(인물 이름)가 생략된 경우, 해당 인물 이름을 주어로 추가합니다.
3. 원문의 의미는 절대 변경하지 마세요.
4. **절대 대화하듯이작성하지 마세요.** (예: "수정된 텍스트입니다" 등의 말 금지)
5. 변경할 내용이 없다면 **입력된 텍스트를 그대로 출력**하세요.
6. 오직 결과 텍스트만 출력하세요.

예시:
입력: "오영수 - 001번 오일남 역: 뇌종양을 앓고 있는 노인. '장풍'의 고수 이며 Duke의 제자 이다."
출력: "오영수 - 001번 오일남 역: 오일남은 뇌종양을 앓고 있는 노인이다. 오일남은 '장풍'의 고수 이며 오일남은 Duke의 제자 이다."
"""

# 조각 크기(문자). 한국어는 대략 1자 ≈ 1토큰 이상이라 출력 한도 안에 넉넉히 들어오도록 잡는다.
CHUNK_CHARS = 3000
# 출력 토큰 상한 — 대부분의 챗 모델 완성 토큰 한도(16,384) 이하.
MAX_COMPLETION_TOKENS = 16000
# 동시 호출 수 — 게이트웨이/요율 제한 보호.
CONCURRENCY = 4

_REFUSAL_MARKERS = ["죄송", "sorry", "i cannot", "unable to", "제공된 텍스트", "cannot fulfill"]


def split_for_restoration(text: str, limit: int = CHUNK_CHARS) -> List[str]:
    """문단(빈 줄) → 줄 → 문자 순으로 경계를 지켜 limit 이하 조각으로 나눈다.
    조각을 순서대로 이어 붙이면 원문과 같다(구분자 보존)."""
    if len(text) <= limit:
        return [text]

    def pieces(s: str, seps: List[str]) -> List[str]:
        if len(s) <= limit:
            return [s]
        if not seps:
            return [s[i:i + limit] for i in range(0, len(s), limit)]
        sep, rest = seps[0], seps[1:]
        parts = s.split(sep)
        out: List[str] = []
        for i, p in enumerate(parts):
            unit = p + (sep if i < len(parts) - 1 else "")
            out.extend(pieces(unit, rest) if len(unit) > limit else [unit])
        return out

    chunks: List[str] = []
    buf = ""
    for unit in pieces(text, ["\n\n", "\n"]):
        if buf and len(buf) + len(unit) > limit:
            chunks.append(buf)
            buf = ""
        buf += unit
    if buf:
        chunks.append(buf)
    return chunks


async def _restore_chunk(cfg: Dict[str, Any], model: str, chunk: str) -> str:
    if not chunk.strip():
        return chunk
    restored = (await achat(
        cfg,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": chunk},
        ],
        model=model, temperature=0.1,
        max_tokens=min(max(len(chunk) * 2, 256), MAX_COMPLETION_TOKENS),
    )).strip()
    if not restored or any(x in restored[:20].lower() for x in _REFUSAL_MARKERS):
        print("[SubjectRestoration] ⚠️ refusal/chat pattern in a chunk. Keeping original chunk.")
        return chunk
    # 조각 사이 구분(빈 줄/줄바꿈)은 원문 것을 유지한다.
    tail = chunk[len(chunk.rstrip()):]
    return restored + tail


async def restore_subjects(
    text: str,
    model: str = "gpt-4o-mini",
    llm_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Restore omitted subjects in Korean text using LLM.

    Args:
        text: Input text with potentially omitted subjects.
        model: Fallback model when llm_config has none.
        llm_config: resolved LLM config (base_url, api_key, extra_headers, model).

    Returns:
        Text with restored subjects. LLM 호출 실패(LLMError)는 그대로 올린다.
    """
    try:
        cfg = llm_config or {}
        active_model = cfg.get("model") or model
        chunks = split_for_restoration(text)
        print(f"[SubjectRestoration] Processing {len(text)} chars in {len(chunks)} chunk(s)...")

        sem = asyncio.Semaphore(CONCURRENCY)

        async def run(c: str) -> str:
            async with sem:
                return await _restore_chunk(cfg, active_model, c)

        restored = "".join(await asyncio.gather(*(run(c) for c in chunks)))
        print(f"[SubjectRestoration] Restored to {len(restored)} chars")
        return restored

    except LLMError:
        raise
    except Exception as e:
        print(f"[SubjectRestoration] ⚠️ Error: {e}. Returning original text.")
        return text
