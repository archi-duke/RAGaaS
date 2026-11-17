"""오탈자·유사어 후보 — 그래프의 현재 라벨 전체에 대해 자모 편집거리 + 라벨 임베딩 근접도.

설계: docs/design/agent/design-typo-synonym-matching.md

- 용어 사전(lexicon)은 적재 때 만든 표기(한영·동의어)만 안다 → 오탈자('슈레딩거')·사전에 없는 값(멤버 1명 경로의 값)을 놓친다.
- 여기서는 사전 대신 **지금 그래프에 있는 라벨**을 대상으로 후보를 만든다 (재추출로 라벨이 바뀌어도 따라감).
- 자모 거리 0.2 이하(명백한 오타·띄어쓰기)만 자동 확정. 나머지는 후보 — 호출부(계획 LLM·MCP 클라이언트)가 질문 맥락으로 고른다.
  임베딩 유사도는 점수만으로 맞고 틀림이 갈리지 않는다 (2026-11-17 실험: 정답 0.44 < 오답 0.61) → 확정에 쓰지 않는다.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

AUTO_JAMO = 0.20        # 이하면 자동 확정 (명백한 오타·띄어쓰기)
CAND_JAMO = 0.45        # 이하면 후보
CAND_EMBED = 0.40       # 이상이면 후보 (임베딩)
TOP_EACH = 3            # 방식별 후보 수
_VEC_TTL = 24 * 3600.0   # 라벨 집합이 바뀌면 키(지문)가 바뀌므로 시간 만료는 안전망만 (30분 → 24시간, 2026-11-17)
_VEC: Dict[Tuple[str, str], Tuple[float, List[str], Any]] = {}   # (kb, 라벨 지문) → (시각, 라벨, 정규화 행렬)
_LOCK = asyncio.Lock()


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-·.,()\[\]'\"『』「」]", "", str(s or "")).lower()


def jamo(s: str) -> List[str]:
    """한글 음절 → 초·중·종성 자모 (오타 '틴/탄', '방/발' 이 1글자 차이로 잡히게)."""
    out: List[str] = []
    for ch in _norm(s):
        c = ord(ch)
        if 0xAC00 <= c <= 0xD7A3:
            c -= 0xAC00
            out += [chr(0x1100 + c // 588), chr(0x1161 + (c % 588) // 28)]
            if c % 28:
                out.append(chr(0x11A7 + c % 28))
        else:
            out.append(ch)
    return out


def _lev(a: Sequence[str], b: Sequence[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def jamo_distance(term: str, label: str) -> float:
    """정규화 자모 편집거리 (0 = 같음). 라벨이 더 길면 라벨 안의 가장 가까운 구간과 비교 + 길이 차 약간."""
    a, b = jamo(term), jamo(label)
    if not a or not b:
        return 1.0
    if len(b) > len(a):
        d = min(_lev(a, b[i:i + len(a)]) for i in range(len(b) - len(a) + 1)) + 0.02 * (len(b) - len(a))
    else:
        d = _lev(a, b)
    return d / len(a)


def fuzzy_candidates(term: str, labels: Sequence[str], top: int = TOP_EACH) -> List[Dict[str, Any]]:
    """자모 거리 후보 [{label, distance, via, auto}] — 2글자 미만·한글 없는 말은 건너뜀 (영어는 사전·임베딩 몫)."""
    if len(_norm(term)) < 2 or not re.search(r"[가-힣]", term or ""):
        return []
    if re.search(r"\d", term or ""):
        # 숫자가 든 말(연도·시기·수치)은 오타로 보지 않는다 — '1930년대' 가 '1950년대' 로 자동 확정돼
        # 질의 계획이 연도 조건 대신 값 경로를 찾다 포기했다 (Q31, 2026-11-17)
        return []
    # 빠른 걸러내기: 말의 자모 절반 이상이 라벨에 없으면 거리 계산을 하지 않는다 (라벨 수천 개에서도 수십 ms)
    tj = jamo(term)
    need = max(1, int(len(set(tj)) * 0.5))
    pool = [l for l in labels if l and len(set(tj) & set(jamo(l))) >= need]
    scored = sorted(((jamo_distance(term, l), l) for l in pool), key=lambda x: (x[0], len(x[1])))
    out = []
    for d, l in scored[:top]:
        if d <= CAND_JAMO:
            # 자동 확정은 라벨이 말과 비슷한 길이일 때만 — 긴 설명형 라벨('확률 해석·불확정성 원리·…')에
            # 부분 일치로 확정되지 않게 (후보로는 남긴다)
            short = len(jamo(l)) <= 2 * len(tj)
            out.append({"label": l, "distance": round(d, 3), "via": "fuzzy", "auto": d <= AUTO_JAMO and short})
    return out


async def _label_matrix(kb_id: str, labels: Sequence[str]):
    """라벨 임베딩 행렬 (정규화) — KB 임베딩 모델로 1회 계산, 라벨 집합이 바뀌면 다시."""
    import hashlib
    import numpy as np
    labs = sorted({l for l in labels if l})
    key = (kb_id, hashlib.sha1("\n".join(labs).encode()).hexdigest()[:16])
    hit = _VEC.get(key)
    if hit and time.time() - hit[0] < _VEC_TTL:
        return hit[1], hit[2]
    async with _LOCK:
        hit = _VEC.get(key)
        if hit and time.time() - hit[0] < _VEC_TTL:
            return hit[1], hit[2]
        emb = await _embedder(kb_id)
        vecs: List[List[float]] = []
        for i in range(0, len(labs), 256):
            vecs += await emb.get_embeddings(labs[i:i + 256])
        m = np.array(vecs, dtype="float32")
        m /= (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        for k in [k for k in _VEC if k[0] == kb_id]:
            _VEC.pop(k, None)
        _VEC[key] = (time.time(), labs, m)
        return labs, m


async def _embedder(kb_id: str):
    from app.models.knowledge_base import KnowledgeBase
    from app.services.embedding import get_embedding_service
    kb = await KnowledgeBase.get(kb_id)
    return await get_embedding_service(kb)


async def embed_candidates(kb_id: str, terms: Sequence[str], labels: Sequence[str],
                           top: int = TOP_EACH) -> Dict[str, List[Dict[str, Any]]]:
    """임베딩 근접 후보 {term: [{label, similarity, via}]} — 확정하지 않는다 (후보만)."""
    import numpy as np
    terms = [t for t in dict.fromkeys(terms) if t and len(_norm(t)) >= 2]
    if not terms or not labels:
        return {}
    try:
        labs, m = await _label_matrix(kb_id, labels)
        emb = await _embedder(kb_id)
        q = np.array(await emb.get_embeddings(list(terms)), dtype="float32")
        q /= (np.linalg.norm(q, axis=1, keepdims=True) + 1e-9)
    except Exception:
        return {}      # 임베딩 실패 시 후보 없이 (자모 후보·사전은 그대로)
    out: Dict[str, List[Dict[str, Any]]] = {}
    sims = q @ m.T
    for i, t in enumerate(terms):
        row = sims[i]
        rows = []
        for j in np.argsort(-row)[:top]:
            s = float(row[j])
            if s >= CAND_EMBED:
                rows.append({"label": labs[j], "similarity": round(s, 3), "via": "embedding"})
        out[t] = rows
    return out


async def candidates(kb_id: str, terms: Sequence[str], labels: Sequence[str],
                     use_embedding: bool = True) -> Dict[str, List[Dict[str, Any]]]:
    """말별 후보 (자모 + 임베딩, 라벨 기준 중복 제거). 자동 확정(auto=True)은 자모 거리 0.2 이하뿐."""
    # 숫자가 든 말(연도·시기·수치)은 오타·유사어 대상이 아니다 (자모·임베딩 모두) — Q31 '1930년대'
    terms = [t for t in dict.fromkeys(terms or []) if t and t.strip() and not re.search(r"\d", t)]
    labels = [l for l in dict.fromkeys(labels or []) if l]
    emb = await embed_candidates(kb_id, terms, labels) if use_embedding else {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for t in terms:
        rows: Dict[str, Dict[str, Any]] = {}
        for c in fuzzy_candidates(t, labels) + emb.get(t, []):
            cur = rows.get(c["label"])
            if cur is None:
                rows[c["label"]] = dict(c)
            else:      # 두 방식이 같은 라벨을 가리키면 근거를 합친다
                cur.update({k: v for k, v in c.items() if k not in ("via",)})
                cur["via"] = "fuzzy+embedding"
                cur["auto"] = cur.get("auto", False) or c.get("auto", False)
        ranked = sorted(rows.values(), key=lambda c: (not c.get("auto"), c.get("distance", 1.0), -c.get("similarity", 0.0)))
        out[t] = ranked
    return out
