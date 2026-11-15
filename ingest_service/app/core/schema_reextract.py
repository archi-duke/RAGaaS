"""스키마 기준 재추출 (승격 L2) — docs/design-graph-promotion.md §3(c) L2

확정된 스키마(클래스·속성·값 어휘·대표 엔티티 이름)를 프롬프트에 넣어 **저장된 청크**에서
트리플을 다시 추출한다. 재청킹·재임베딩이 없으므로 source_node_id(근거 청크)가 그대로다.
- 사실 하나 = 트리플 하나 (조건 묶음 문장을 쪼갠다), 개수 상한 없음
- 스키마 속성이 있으면 그 이름만 쓰고, 값은 어휘에 있으면 그 표기로
- 스키마에 없는 사실은 out_of_schema 로 따로 받아 버리지 않는다 (이후 새 속성 제안으로)
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

MAX_CHUNK_CHARS = 6000
CONCURRENCY = 4


def build_schema_text(spec: Dict[str, Any]) -> str:
    lines = ["[클래스]"]
    for c in spec.get("classes") or []:
        mem = ", ".join((c.get("members") or [])[:40])
        lines.append(f"- {c['name']}: {c.get('description') or ''}" + (f" (알려진 멤버: {mem})" if mem else ""))
    lines.append("\n[속성] 이름 (domain → range): 정의 — 같은 뜻의 다른 표기 / 허용 값")
    for p in spec.get("properties") or []:
        aliases = ", ".join(a for a in (p.get("aliases") or []) if a != p["name"])
        vals = ", ".join((p.get("values") or [])[:15])
        dom, rng = p.get("domain") or "", p.get("range") or ""
        line = f"- {p['name']}" + (f" ({dom or '?'} → {rng or '?'})" if (dom or rng) else "")
        if p.get("description"):
            line += f": {p['description']}"
        if aliases:
            line += f" — 별칭: {aliases}"
        if vals:
            line += f" / 값: {vals}"
        lines.append(line)
    return "\n".join(lines)


def build_messages(schema_text: str, text: str) -> List[Dict[str, str]]:
    user = f"""다음 스키마에 맞춰 텍스트의 사실을 빠짐없이 트리플로 추출하라.

{schema_text}

규칙:
1. 사실 하나 = 트리플 하나. "A이거나 B이거나 C일 때" 같은 묶음은 조건마다 따로 트리플을 만든다.
2. predicate 는 위 [속성] 이름만 쓴다 (별칭이 보이면 대표 이름으로). 개수 제한 없음.
   정의가 있는 속성은 정의의 의미와 방향(subject=domain, object=range)을 지킨다. 예: 정의가 '스승 → 제자' 이면
   "B는 A의 지도로 학위를 받았다" 는 subject=A, object=B. 일반 동사(소속·발표 등)로 뭉뚱그리지 말고 가장 구체적인 속성을 고른다.
3. subject 는 알려진 멤버 이름 그대로 (같은 대상의 다른 표기도 대표 이름으로).
4. object 는 허용 값이 있으면 그 표기로 (예: 높다 → 목록에 '높다'가 있으면 '높다'). 없으면 짧은 명사구로.
5. 위 속성으로 표현할 수 없는 사실은 out_of_schema 에 넣는다 (predicate 는 짧은 명사구로 지어도 된다). 버리지 마라.
6. 텍스트에 없는 사실을 만들지 마라. 속성에 억지로 맞추지 마라 — 예: "1931년 세상을 떠났다" 는 수상이 아니다.
   텍스트가 그 속성의 의미를 직접 말할 때만 그 속성을 쓰고, 아니면 out_of_schema 로.

텍스트:
{text[:MAX_CHUNK_CHARS]}

JSON 만 출력: {{"triples": [{{"subject": "...", "predicate": "...", "object": "..."}}], "out_of_schema": [{{"subject": "...", "predicate": "...", "object": "..."}}]}}"""
    return [
        {"role": "system", "content": "You extract knowledge-graph triples that conform to a given schema. Output JSON only."},
        {"role": "user", "content": user},
    ]


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except ValueError:
        s, e = t.find("{"), t.rfind("}")
        if s != -1 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except ValueError:
                return None
    return None


def parse_response(data: Optional[Dict[str, Any]], node_id: str, allowed: set) -> List[Dict[str, Any]]:
    out = []
    if not data:
        return out
    for key, oos in (("triples", False), ("out_of_schema", True)):
        for t in data.get(key) or []:
            if not isinstance(t, dict):
                continue
            s, p, o = (str(t.get(k) or "").strip() for k in ("subject", "predicate", "object"))
            if not (s and p and o) or len(s) > 80 or len(p) > 60:
                continue
            # 스키마 속성이라고 했는데 목록에 없으면 스키마 밖으로 분류
            is_oos = oos or p not in allowed
            out.append({"subject": s, "predicate": p, "object": o, "source_node_id": node_id,
                        "confidence": 0.9 if not is_oos else 0.7, "out_of_schema": is_oos,
                        "extraction": "schema_reextract"})
    return out


async def reextract_chunks(
    chunks: List[Dict[str, Any]], spec: Dict[str, Any], llm_cfg: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from app.core.llm import achat

    schema_text = build_schema_text(spec)
    allowed = {p["name"] for p in spec.get("properties") or []}
    sem = asyncio.Semaphore(CONCURRENCY)
    failures = []

    async def one(ch):
        text = ch.get("content") or ""
        if len(text.strip()) < 10:
            return []
        async with sem:
            try:
                extra = {"thinking": {"type": "disabled"}} if "glm" in str(llm_cfg.get("model", "")).lower() else None
                content = await achat(llm_cfg, build_messages(schema_text, text), model=llm_cfg.get("model"),
                                      temperature=0, response_format={"type": "json_object"}, extra_body=extra)
                return parse_response(_parse_json(content), ch.get("node_id"), allowed)
            except Exception as e:
                failures.append({"node_id": ch.get("node_id"), "reason": str(e)[:200]})
                return []

    results = await asyncio.gather(*(one(c) for c in chunks))
    triples = [t for r in results for t in r]
    stats = {"chunks": len(chunks), "triples": len(triples),
             "out_of_schema": sum(1 for t in triples if t["out_of_schema"]),
             "chunk_failures": failures}
    return triples, stats
