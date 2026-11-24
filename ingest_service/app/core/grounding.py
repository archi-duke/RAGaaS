"""트리플 근거 검사 — 목적어가 근거 청크(source_node_id)에 실제로 나오는가 (데이터 품질, 2026-11-24).

추출 LLM 은 프롬프트에 넣은 스키마 값 어휘·사전에서 원문에 없는 값을 골라 넣는 일이 있다.
예) cqrs.md 의 점수 규칙 청크에는 가용성 얘기가 없는데 'CQRS —has_moderate_positive_effect_on→ Availability'
가 들어갔다 (값 어휘 'Availability' 는 다른 문서에서 온 것). 이전에는 값 어휘에 있는 표기를
'정규화 결과' 로 보고 검사를 건너뛰어 이런 트리플이 그대로 저장됐다.

검사 규칙 (LLM 비용 없음, 문자열 비교):
- 목적어 핵심 토큰의 절반 이상이 원문(공백·_·- 무시)에 있으면 근거 있음 (is_grounded).
- 목적어가 정규화된 표기면 그 원래 표기(value·entity 규칙의 source, 사전 별칭)로도 찾는다
  ('Availability' ← 원문 '가용성').
- 평가형 값('높다', '높음', '중간' 처럼 어미를 맞춘 짧은 한글 값)은 원문 표기가 '높으면'·'높고' 처럼
  바뀌므로 검사하지 않는다.
주어는 검사하지 않는다 — 문서 제목·앞 청크에서 주어를 복원하는 일이 정상적으로 있다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _ck(x: str) -> str:
    return re.sub(r"[\s_\-]", "", str(x or "")).lower()


_YEAR_RE = re.compile(r"^\d{2,4}(?:년|년도|년대)?$")
_HANGUL_ONLY = re.compile(r"^[가-힣]+$")
# 평가형 값: 짧은 한글 서술형(…다) 또는 정도 표현 — 원문에서는 활용형으로 나온다
_GRADE_VALUES = {"중간", "중간이상", "중간이하", "보통", "매우높다", "매우낮다"}


def is_grade_value(obj: str) -> bool:
    c = _ck(obj)
    if c in _GRADE_VALUES:
        return True
    return bool(_HANGUL_ONLY.match(c)) and len(c) <= 4 and c[-1] in "다음함"


def is_grounded(obj: str, text: str) -> bool:
    """목적어의 핵심 토큰이 원문에 있는가.

    예) 원문 "1931년 세상을 떠났다" → '1931년도_노벨_물리학상' 은 '노벨'·'물리학상' 이 원문에 없어 거부.
    - 연도 토큰은 숫자만 원문에 있으면 된다.
    - 핵심 토큰의 절반 이상이 원문(공백 무시)에 있어야 한다.
    """
    compact_text = _ck(text)
    toks = [x for x in re.split(r"[\s_\-·,()『』「」]+", str(obj or "")) if x]
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


def build_alias_index(rules: Optional[Iterable[Dict[str, Any]]] = None,
                      entity_dictionary: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Set[str]]:
    """정규화된 표기 → 원래 표기들. value·entity 규칙(source → target)과 엔티티 사전 별칭에서 모은다."""
    idx: Dict[str, Set[str]] = {}
    for r in rules or []:
        if r.get("rule_type") in ("value", "entity") and r.get("source_value") and r.get("target_value"):
            idx.setdefault(_ck(r["target_value"]), set()).add(str(r["source_value"]))
    for canon, info in (entity_dictionary or {}).items():
        for v in (info or {}).get("variants") or []:
            idx.setdefault(_ck(canon), set()).add(str(v))
    return idx


def object_grounded(obj: str, text: str, aliases: Optional[Dict[str, Set[str]]] = None) -> bool:
    if is_grade_value(obj) or is_grounded(obj, text):
        return True
    return any(is_grounded(a, text) for a in (aliases or {}).get(_ck(obj), ()))


def filter_ungrounded(triples: List[Dict[str, Any]], text_by_node: Dict[str, str],
                      aliases: Optional[Dict[str, Set[str]]] = None
                      ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(통과, 제외). 근거 청크 원문을 모르는 트리플은 검사하지 않고 통과시킨다."""
    kept, dropped = [], []
    for t in triples:
        text = text_by_node.get(t.get("source_node_id") or "")
        if text is None or object_grounded(str(t.get("object") or ""), text, aliases):
            kept.append(t)
        else:
            dropped.append(t)
    return kept, dropped


def save_ungrounded(kb_id: str, doc_id: str, dropped: List[Dict[str, Any]]) -> None:
    """제외한 트리플을 <doc>_triples.ungrounded.json 으로 남긴다 (검토용, 그래프에는 넣지 않는다)."""
    import json
    from app.utils.temp_storage import temp_storage
    path = temp_storage._get_file_path(kb_id, doc_id, "_triples.ungrounded.json")
    rows = [{k: t.get(k) for k in ("subject", "predicate", "object", "source_node_id")} for t in dropped]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[Grounding] 제외 목록 저장 실패 {doc_id}: {e}")
