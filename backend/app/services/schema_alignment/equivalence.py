"""스키마 동치 감지기 — 검색 시 OR 확장(Part 1)과 인제스트 매핑 제안(Part 2) 공용.

설계: docs/design/schema/design-schema-mismatch.md §3

같은 의미의 필드를 다른 이름·표기·중첩으로 적은 경로를 묶는다.
  근거: normalized(표기·어간) / nesting(리프 일치, 접두 다름) / lexicon(내장 동의어표) / llm / rule
  게이트(모두 통과해야 동치):
    G1 값 종류 호환 (number 는 number 와만)
    G2 멤버 상보성 — 한 레코드가 두 경로를 모두 가지면 서로 다른 속성
    G3 접두 공존 금지 — 최상위 세그먼트가 다른 두 접두가 같은 멤버에 공존하면 다른 속성
       (avoid_signals.team_size vs fit_signals.team_size)
임베딩은 쓰지 않는다 (짧은 한↔영 단어 유사도는 신뢰 불가).
"""

import hashlib
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.services.retrieval.entity_linking import _compact, normalize_text

# 내장 키 동의어표 (같은 묶음 = 같은 필드로 볼 수 있음). 구조 게이트를 통과해야만 동치.
KEY_SYNONYMS: List[Set[str]] = [
    {"pros", "advantages", "advantage", "benefits", "benefit", "strengths", "장점", "이점"},
    {"cons", "disadvantages", "disadvantage", "drawbacks", "drawback", "weaknesses", "단점"},
    {"prerequisites", "prerequisite", "requirements", "preconditions", "전제조건", "사전조건"},
    {"references", "refs", "reference", "참고문헌", "참고"},
    {"summary", "overview", "요약"},
    {"description", "desc", "설명"},
    {"tradeoffs", "trade_offs", "트레이드오프"},
]

# 값 동의어 (양방향). 해당 묶음 어휘에 실제로 있는 값끼리만 동치.
VALUE_SYNONYMS: Dict[str, str] = {
    "높음": "high", "높은": "high", "높다": "high", "상": "high",
    "중간": "medium", "보통": "medium", "중": "medium",
    "낮음": "low", "낮은": "low", "낮다": "low", "하": "low",
    "작은": "small", "작음": "small", "소규모": "small", "작을": "small",
    "큰": "large", "큼": "large", "대규모": "large",
    "긍정": "positive", "긍정적": "positive", "부정": "negative", "부정적": "negative",
    "필수": "required", "있음": "yes", "없음": "no",
}

_KEY_GROUP_INDEX: Dict[str, int] = {}
for _i, _g in enumerate(KEY_SYNONYMS):
    for _w in _g:
        _KEY_GROUP_INDEX[_compact(_w)] = _i

BASIS_LABELS = {
    "rule": "KB 매핑 규칙", "normalized": "표기 정규화", "nesting": "중첩 차이",
    "lexicon": "동의어표", "llm": "LLM 판정", "plan": "계획 지정",
}


_NUM_LABEL = __import__("re").compile(r"^\s*-?\d+(\.\d+)?\s*$")


def value_canonical(label: str) -> str:
    """값 비교 키: 숫자는 수치 그대로, 그 외는 동의어표 적용 후 compact. 비교 불가면 ''."""
    raw = str(label)
    if _NUM_LABEL.match(raw):
        return "num:" + format(float(raw), "g")
    n = normalize_text(raw)
    c = _compact(VALUE_SYNONYMS.get(n, n))
    return c or ("raw:" + n if n else "")


# ---------------------------------------------------------------------------
# 이름 유사 판정
# ---------------------------------------------------------------------------

def _stem_aligned(a: str, b: str) -> bool:
    """토큰 수가 같고 토큰마다 같거나, 공통 접두가 4자 이상이면서 짧은 쪽의 60% 이상.
    (test complexity ≈ testing_complexity 는 허용, testability ≈ testingComplexity 는 거부)"""
    from app.services.retrieval.entity_linking import tokens
    ta, tb = tokens(a), tokens(b)
    if not ta or len(ta) != len(tb):
        return False
    for x, y in zip(ta, tb):
        if x == y:
            continue
        n = 0
        for c1, c2 in zip(x, y):
            if c1 != c2:
                break
            n += 1
        if n < 4 or n < 0.6 * min(len(x), len(y)):
            return False
    return True


def _seg_basis(a: str, b: str, allow_stem: bool = True) -> Optional[str]:
    ca, cb = _compact(a), _compact(b)
    if not ca or not cb:
        return None
    if ca == cb:
        return "normalized"
    if allow_stem and a.isascii() and b.isascii() and _stem_aligned(a, b):
        return "normalized"
    ga, gb = _KEY_GROUP_INDEX.get(ca), _KEY_GROUP_INDEX.get(cb)
    if ga is not None and ga == gb:
        return "lexicon"
    return None


def path_similarity(p: Sequence[str], q: Sequence[str]) -> Optional[str]:
    """두 경로(세그먼트 목록)의 이름 유사 근거. 없으면 None."""
    if list(p) == list(q):
        return None
    if len(p) == len(q):
        bases = []
        for a, b in zip(p, q):
            if a == b:
                continue
            basis = _seg_basis(a, b)
            if basis is None:
                return None
            bases.append(basis)
        if not bases:
            return None
        return "lexicon" if "lexicon" in bases else "normalized"
    # 깊이가 다르면 리프가 일치하고, 짧은 쪽 접두가 긴 쪽 접두에 포함될 때만 (pros ≈ tradeoffs.pros)
    # 중첩 차이는 리프가 표기 일치(또는 동의어표)일 때만 — 어간 유사로는 묶지 않는다
    leaf = _seg_basis(p[-1], q[-1], allow_stem=False) if p[-1] != q[-1] else "normalized"
    if leaf is None:
        return None
    short, long_ = (p, q) if len(p) < len(q) else (q, p)
    if list(short[:-1]) == list(long_[: len(short) - 1]):
        return "nesting"
    return None


# ---------------------------------------------------------------------------
# 구조 게이트
# ---------------------------------------------------------------------------

def _type_family(p: Dict[str, Any]) -> str:
    return "number" if p.get("type") == "number" else "nominal"


def gate(p: Dict[str, Any], q: Dict[str, Any], top_members: Dict[str, Set[str]]) -> Tuple[bool, str]:
    """구조 게이트. (통과 여부, 사유)"""
    if _type_family(p) != _type_family(q):
        return False, "값 종류 불일치"
    mp, mq = p.get("member_ids") or set(), q.get("member_ids") or set()
    if mp and mq:
        overlap = len(mp & mq) / max(1, min(len(mp), len(mq)))
        if overlap > 0.2:
            return False, f"같은 멤버에 공존({len(mp & mq)}개)"
    tp, tq = p["segments"][0], q["segments"][0]
    if tp != tq and len(p["segments"]) > 1 and len(q["segments"]) > 1:
        if top_members.get(tp, set()) & top_members.get(tq, set()):
            return False, f"접두 {tp}·{tq} 가 같은 멤버에 공존"
    return True, ""


def top_level_members(paths: Iterable[Dict[str, Any]]) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    for p in paths:
        out.setdefault(p["segments"][0], set()).update(p.get("member_ids") or set())
    return out


# ---------------------------------------------------------------------------
# 묶음 감지
# ---------------------------------------------------------------------------

def _pair_key(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def detect_path_groups(
    paths: List[Dict[str, Any]],
    llm_pairs: Iterable[Tuple[str, str]] = (),
    rule_pairs: Iterable[Tuple[str, str]] = (),
    ignore_pairs: Iterable[Tuple[str, str]] = (),
    use_llm: bool = True,
) -> List[Dict[str, Any]]:
    """경로 동치 묶음.

    반환: [{"keys": [경로키…], "rep": 대표키(커버리지 최대), "basis": {쌍키: 근거}}]
    rule 은 게이트 없이 인정(사용자 확정), 나머지는 게이트 통과 시만.
    """
    by_key = {p["key"]: p for p in paths}
    tops = top_level_members(paths)
    ignore = {_pair_key(*x) for x in ignore_pairs}
    edges: Dict[Tuple[str, str], str] = {}

    for a, b in rule_pairs:
        if a in by_key and b in by_key:
            edges[_pair_key(a, b)] = "rule"

    keys = list(by_key)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            k = _pair_key(a, b)
            if k in edges or k in ignore:
                continue
            basis = path_similarity(by_key[a]["segments"], by_key[b]["segments"])
            if basis and gate(by_key[a], by_key[b], tops)[0]:
                edges[k] = basis

    if use_llm:
        for a, b in llm_pairs:
            k = _pair_key(a, b)
            if a in by_key and b in by_key and k not in edges and k not in ignore:
                if gate(by_key[a], by_key[b], tops)[0]:
                    edges[k] = "llm"

    # 묶음 병합: 연쇄 확장 방지 — 합치려는 두 묶음의 모든 교차 쌍이 게이트를 통과해야 한다
    comp_of = {k: {k} for k in keys}
    order = sorted(edges.items(), key=lambda kv: {"rule": 0, "normalized": 1, "lexicon": 2, "nesting": 3, "llm": 4}.get(kv[1], 9))
    for (a, b), basis in order:
        ca, cb = comp_of[a], comp_of[b]
        if ca is cb:
            continue
        if basis != "rule" and not all(gate(by_key[x], by_key[y], tops)[0] for x in ca for y in cb):
            continue
        merged = ca | cb
        for k in merged:
            comp_of[k] = merged
    comps: Dict[int, List[str]] = {}
    for k in keys:
        comps.setdefault(id(comp_of[k]), []).append(k)

    groups = []
    for members in comps.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda k: (-len(by_key[k].get("member_ids") or ()), k))
        basis = {f"{a}≡{b}": v for (a, b), v in edges.items() if a in members and b in members}
        if not basis:
            continue
        groups.append({"keys": members, "rep": members[0], "basis": basis})
    return groups


def group_value_equivalents(group_paths: List[Dict[str, Any]], llm_value_groups: Iterable[Sequence[str]] = (),
                            rule_values: Dict[str, str] = None) -> List[List[Dict[str, Any]]]:
    """묶음의 합친 값 어휘에서 동치 값 묶음. 반환: [[값항목…], …] (2개 이상만)"""
    rule_values = rule_values or {}
    vocab: Dict[str, Dict[str, Any]] = {}
    for p in group_paths:
        for v in p.get("values") or []:
            vocab.setdefault(v["uri"], v)
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for v in vocab.values():
        canon = value_canonical(rule_values.get(_compact(v["label"]), v["label"]))
        if not canon:
            continue
        buckets.setdefault(canon, []).append(v)
    label_bucket = {_compact(v["label"]): c for c, vs in buckets.items() for v in vs}
    for grp in llm_value_groups:
        cs = [label_bucket.get(_compact(x)) for x in grp]
        cs = [c for c in cs if c]
        if len(set(cs)) > 1:
            first = cs[0]
            for c in set(cs[1:]):
                if c != first and c in buckets:
                    buckets[first].extend(buckets.pop(c))
                    for v in buckets[first]:
                        label_bucket[_compact(v["label"])] = first
    return [vs for vs in buckets.values() if len(vs) > 1]


def annotate_catalog(paths: List[Dict[str, Any]], groups: List[Dict[str, Any]]) -> None:
    """카탈로그 경로에 동치 정보를 붙인다 (p['equiv'], p['equiv_basis'], p['equiv_rep'])."""
    for p in paths:
        p.pop("equiv", None)
        p.pop("equiv_basis", None)
        p.pop("equiv_rep", None)
    by_key = {p["key"]: p for p in paths}
    for g in groups:
        for k in g["keys"]:
            p = by_key[k]
            p["equiv"] = [x for x in g["keys"] if x != k]
            p["equiv_rep"] = g["rep"]
            p["equiv_basis"] = sorted(set(g["basis"].values()))


def catalog_signature(paths: List[Dict[str, Any]]) -> str:
    """스키마 시그니처: 경로 키·종류·enum 라벨. 문서 수만 늘면 불변."""
    parts = []
    for p in sorted(paths, key=lambda x: x["key"]):
        vals = ",".join(sorted(v["label"] for v in p.get("values") or [])) if p.get("type") == "enum" else ""
        parts.append(f"{p['key']}|{p.get('type')}|{vals}")
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# LLM 동치 패스 (카탈로그당 1회, 캐시)
# ---------------------------------------------------------------------------

def build_equivalence_messages(paths: List[Dict[str, Any]], total_members: int) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    """커버리지 100% 미만 경로만 대상 (100% 경로는 G2 상 동치 불가)."""
    items = [p for p in paths if len(p.get("member_ids") or ()) < total_members][:200]
    lines = []
    for i, p in enumerate(items):
        cov = len(p.get("member_ids") or ())
        if p.get("type") == "enum":
            ex = ", ".join(v["label"] for v in p["values"][:8])
        else:
            ex = " / ".join(p.get("examples") or [])
        lines.append(f"{i}. {p['key']} (멤버 {cov}/{total_members}, {p.get('type')}: {ex})")
    user = f"""다음은 같은 종류 레코드들의 필드 경로 목록이다. 일부 레코드는 다른 스키마로 작성되어
같은 필드를 다른 이름·언어·표기·중첩으로 적었을 수 있다.

{chr(10).join(lines)}

같은 필드를 다르게 적은 것만 묶어라 (예: pros ↔ advantages ↔ 장점). 관련만 있는 다른 개념은 묶지 마라
(예: avoid_signals.team_size 와 fit_signals.team_size 는 다른 필드).
값도 같은 뜻을 다른 언어·표기로 적은 것만 묶어라 (예: high ↔ 높음).
JSON 만 출력: {{"path_groups": [[번호, 번호]], "value_groups": [["high", "높음"]]}} (없으면 빈 배열)"""
    return [
        {"role": "system", "content": "You detect schema field synonyms. Be conservative. Output JSON only."},
        {"role": "user", "content": user},
    ], items


def parse_llm_groups(data: Optional[Dict[str, Any]], items: List[Dict[str, Any]]) -> Tuple[List[Tuple[str, str]], List[List[str]]]:
    pairs: List[Tuple[str, str]] = []
    if not data:
        return pairs, []
    for grp in data.get("path_groups") or []:
        keys = []
        for idx in grp if isinstance(grp, list) else []:
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(items):
                keys.append(items[i]["key"])
        for a in keys[1:]:
            pairs.append((keys[0], a))
    vgroups = [[str(x) for x in g] for g in (data.get("value_groups") or []) if isinstance(g, list) and len(g) > 1]
    return pairs, vgroups


def mixed_language_values(values: List[Dict[str, Any]], grouped_uris: Set[str]) -> List[str]:
    """한글·영문 값이 섞인 enum 에서 동치 미확정 값 (경고용)."""
    has_ascii = any(str(v["label"]).isascii() for v in values)
    out = []
    for v in values:
        if has_ascii and not str(v["label"]).isascii() and v["uri"] not in grouped_uris:
            out.append(f"{v['label']}({v.get('members', 0)})")
    return out
