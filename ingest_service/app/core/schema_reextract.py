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
MAX_MEMBERS_PER_CLASS = 80   # 목적어 표기를 기존 멤버에 맞추도록 (range 클래스 어휘) — 재추출이 새 표기를 만들면 멤버 누락이 된다

# 부재·부정 표현: "충돌하는 스타일은 없다" → (X, 충돌, 없음) 같은 트리플은 사실이 아니다
_ABSENT_RE = re.compile(r"^\s*(없음|없다|없습니다|해당\s*(사항\s*)?없음|해당되지\s*않음|해당\s*없다|n/?a|none|null|-)\s*\.?$", re.I)


def build_schema_text(spec: Dict[str, Any]) -> str:
    lines = ["[클래스]"]
    for c in spec.get("classes") or []:
        mem = ", ".join((c.get("members") or [])[:MAX_MEMBERS_PER_CLASS])
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
   정의에 'A | 속성 | B' 형태가 있으면 그 자리 그대로 쓴다. 예: '계승_발전' 이 'A | 계승_발전 | B (A가 선행)' 이면
   "B는 A를 이어받아 발전시켰다" 는 subject=A, object=B — 문장의 주어(B)를 subject 로 쓰지 않는다.
3. subject 와 object 는 알려진 멤버 이름 그대로 (같은 대상의 다른 표기·번역도 대표 이름으로).
   예: 알려진 멤버에 '테스트 용이성' 이 있으면 'testability' 가 아니라 '테스트 용이성'. 텍스트가 영어여도 멤버 표기를 따른다.
4. object 는 허용 값이 있으면 그 표기로 (예: 높다 → 목록에 '높다'가 있으면 '높다'). 없으면 짧은 명사구로.
   "충돌하는 스타일은 없다", "해당 없음" 처럼 무언가가 **없다**는 문장은 트리플로 만들지 마라 ('없음' 을 object 로 쓰지 마라).
5. 위 속성으로 표현할 수 없는 사실은 out_of_schema 에 넣는다 (predicate 는 짧은 명사구로 지어도 된다). 버리지 마라.
6. 텍스트에 없는 사실을 만들지 마라. 속성에 억지로 맞추지 마라 — 예: "1931년 세상을 떠났다" 는 수상이 아니다.
   텍스트가 그 속성의 의미를 직접 말할 때만 그 속성을 쓰고, 아니면 out_of_schema 로.
7. 그 사실을 말하는 **같은 문장**에 연도가 숫자로 있으면 트리플에 "year": 정수 를 붙인다. 연도는 object 에 섞지 않는다.
   예: "1872년 크뢰벨은 『열과 일의 정밀측정』을 저술했다" → {{"subject": "크뢰벨", "predicate": "저술함", "object": "『열과 일의 정밀측정』", "year": 1872}}
   예: "1933년 노벨 물리학상을 받았다" → object 는 "노벨 물리학상", "year": 1933 ("노벨 물리학상 (1933년)" 이 아니다)
   연도를 object 로 쓰지 마라 ('저술함 → 1855년' 은 틀림) — 연도 자체가 사실인 속성(출생 연도 등)만 예외.
   문장에 연도가 없으면 year 를 넣지 마라. 앞 문장의 연도·'같은 해' 같은 표현으로 짐작하지 마라. 범위('1920년대')는 넣지 마라.

텍스트:
{text[:MAX_CHUNK_CHARS]}

JSON 만 출력: {{"triples": [{{"subject": "...", "predicate": "...", "object": "...", "year": 1900}}], "out_of_schema": [{{"subject": "...", "predicate": "...", "object": "..."}}]}}"""
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


def _ck(x: str) -> str:
    return re.sub(r"[\s_\-]", "", str(x or "")).lower()


def build_type_index(spec: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Tuple[str, str]]]:
    """(멤버 이름 → 클래스, 속성 → (domain, range)) — 도메인·방향 검사용."""
    cls: Dict[str, str] = {}
    for c in spec.get("classes") or []:
        for m in c.get("members") or []:
            cls.setdefault(_ck(m), c["name"])
    dr = {p["name"]: (p.get("domain") or "", p.get("range") or "") for p in spec.get("properties") or []}
    return cls, dr


def check_domain(t: Dict[str, Any], cls: Dict[str, str], dr: Dict[str, Tuple[str, str]]) -> Dict[str, Any]:
    """알려진 멤버의 클래스로 domain·range 를 검사한다.

    - 주어·목적어 클래스가 정확히 (range, domain) 이면 방향이 뒤집힌 것 → 바꾼다.
    - 주어 클래스가 domain 과 다르면 그 속성의 사실이 아니다 → out_of_schema
      (예: '드브로이(인물) —계승_발전→ 광양자_가설' — 계승_발전 은 이론 → 이론).
    클래스를 모르는 이름은 검사하지 않는다.
    """
    if t["out_of_schema"] or t["predicate"] not in dr:
        return t
    dom, rng = dr[t["predicate"]]
    sc, oc = cls.get(_ck(t["subject"])), cls.get(_ck(t["object"]))
    if dom and rng and dom != rng and sc == rng and oc == dom:
        return {**t, "subject": t["object"], "object": t["subject"], "direction_fixed": True}
    if dom and sc and sc != dom:
        # 저장 단계는 out_of_schema 도 같은 관계 이름으로 넣으므로, 표시만 하면 그래프가 오염된다 → 제외
        return {**t, "drop": "domain", "domain_violation": f"{sc} ≠ {dom}"}
    return t


_YEAR_RE = re.compile(r"^\d{2,4}(?:년|년도|년대)?$")


def is_grounded(obj: str, text: str, allowed_values: Optional[set] = None) -> bool:
    """목적어의 핵심 토큰이 원문에 있는가 — 스키마 맞춤 환각 차단.

    예) 원문 "1931년 세상을 떠났다" → '1931년도_노벨_물리학상' 은 '노벨'·'물리학상' 이 원문에 없어 거부.
    - 허용 값 어휘(스키마 값 목록)에 있는 표기는 정규화 결과이므로 검사하지 않는다.
    - 연도 토큰은 숫자만 원문에 있으면 된다.
    - 핵심 토큰의 절반 이상이 원문(공백 무시)에 있어야 한다.
    """
    if allowed_values and _ck(obj) in allowed_values:
        return True
    compact_text = _ck(text)
    toks = [x for x in re.split(r"[\s_\-·,()『』「」]+", obj) if x]
    if not toks:
        return True
    hit = 0
    for tok in toks:
        if _YEAR_RE.match(tok):
            hit += re.sub(r"\D", "", tok) in compact_text
        elif len(tok) < 2:
            hit += 1
        else:
            # 조사·어미 차이 허용: 앞 2글자 이상이 원문에 있으면 인정 ('측정한' ↔ '측정')
            hit += any(_ck(tok[:k]) in compact_text for k in range(len(tok), 1, -1))
    return hit * 2 >= len(toks)


_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)|\n+")


def grounded_year(year: Any, text: Optional[str], subj: str, obj: str) -> Optional[int]:
    """추출이 낸 연도를 받을지 (D4 Y2). 1000~2100 정수이고, 원문의 한 문장에 그 연도와 주어·목적어 중 하나가
    함께 있을 때만 받는다 (지어낸 연도·다른 문장 연도 차단). 원문이 없으면(미리보기 등) 범위만 본다."""
    try:
        y = int(str(year).strip().rstrip("년"))
    except (TypeError, ValueError):
        return None
    if not (1000 <= y <= 2100):
        return None
    if text is None:
        return y
    keys = [k for k in (_ck(subj)[:3], _ck(obj)[:3]) if len(k) >= 2]
    for sent in _SENT_SPLIT.split(text):
        if sent and str(y) in sent and any(k in _ck(sent) for k in keys):
            return y
    return None


def parse_response(data: Optional[Dict[str, Any]], node_id: str, allowed: set,
                   type_index: Optional[Tuple[Dict[str, str], Dict[str, Tuple[str, str]]]] = None,
                   text: Optional[str] = None, allowed_values: Optional[set] = None
                   ) -> List[Dict[str, Any]]:
    """drop 표시(domain 위반·원문 근거 없음)가 붙은 트리플도 반환한다 — 호출부가 걸러 내고 집계한다."""
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
            year_in = t.get("year")
            t = {"subject": s, "predicate": p, "object": o, "source_node_id": node_id,
                 "confidence": 0.9 if not is_oos else 0.7, "out_of_schema": is_oos,
                 "extraction": "schema_reextract"}
            y = grounded_year(year_in, text, s, o)
            if y is not None:
                t["year"] = y
            if _ABSENT_RE.match(o):
                t = {**t, "drop": "absent"}
                out.append(t)
                continue
            t = check_domain(t, *type_index) if type_index else t
            if text is not None and not t.get("drop") and not is_grounded(o, text, allowed_values):
                t = {**t, "drop": "ungrounded"}
            out.append(t)
    return out


async def reextract_chunks(
    chunks: List[Dict[str, Any]], spec: Dict[str, Any], llm_cfg: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from app.core.llm import achat

    schema_text = build_schema_text(spec)
    allowed = {p["name"] for p in spec.get("properties") or []}
    type_index = build_type_index(spec)
    allowed_values = {_ck(v) for p in spec.get("properties") or [] for v in (p.get("values") or [])}
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
                return parse_response(_parse_json(content), ch.get("node_id"), allowed, type_index,
                                      text[:MAX_CHUNK_CHARS], allowed_values)
            except Exception as e:
                failures.append({"node_id": ch.get("node_id"), "reason": str(e)[:200]})
                return []

    results = await asyncio.gather(*(one(c) for c in chunks))
    raw = [t for r in results for t in r]
    triples = [t for t in raw if not t.get("drop")]
    stats = {"chunks": len(chunks), "triples": len(triples),
             "dropped_domain": sum(1 for t in raw if t.get("drop") == "domain"),
             "dropped_ungrounded": sum(1 for t in raw if t.get("drop") == "ungrounded"),
             "dropped_absent": sum(1 for t in raw if t.get("drop") == "absent"),
             "out_of_schema": sum(1 for t in triples if t["out_of_schema"]),
             "direction_fixed": sum(1 for t in triples if t.get("direction_fixed")),
             "chunk_failures": failures}
    return triples, stats
