"""KB 용어 사전 — 적재 후 LLM 으로 별칭을 한 번 만들고, 검색할 때는 사전만 찾는다 (docs/design/agent/design-kb-lexicon.md).

- build_lexicon: 사전에 없는 라벨만 40개씩 LLM 에 보내 ko/en/syn/broader 를 만든다 (상위 개념도 항목으로).
- get_index: 정규화 표기 → 라벨 (via, 점수) 색인. 메모리 캐시, 빌드·편집 시 무효화.
- match_term / narrower_of: 검색 시 LLM 없이 찾기.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

BATCH = 40
MAX_LABEL_LEN = 30
# 일반어 — 이것을 뺀 표기도 색인한다 ('헥사고날 아키텍처' → '헥사고날')
GENERIC_SUFFIX = re.compile(r"\s*(아키텍처|스타일|패턴|이론|실험|architecture|style|pattern|theory|experiment)$", re.I)

SCORE_LABEL, SCORE_ALIAS, SCORE_STRIPPED = 120.0, 100.0, 90.0

_INDEX_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_BUILD_STATUS: Dict[str, Dict[str, Any]] = {}

PROMPT = """아래는 지식 그래프의 라벨이다 (도메인: {domain}).
라벨마다 검색용 별칭을 만들어라. 사용자는 한국어·영어를 섞어 묻고, 음역(마이크로서비스, 헥사고날)도 쓴다.

- ko: 한국어 표기. 영문 라벨이면 번역과 음역을 모두 (Hexagonal → 헥사고날, 육각형).
  업계에서 흔히 쓰는 한국어 표기가 여럿이면 모두 넣어라 (observability → 관측성, 관측 가능성, 옵저버빌리티).
- en: 영어 표기. 한국어 라벨이면 영어 용어. snake_case 라벨은 띄어 쓴 영어와 한국어로.
- syn: **뜻이 같은** 다른 이름·약어만 (Ports and Adapters, EDA, QED, 수정 용이성↔변경 용이성).
  동의어도 한국어·영어 표기를 모두 넣어라 (Ports and Adapters → 포트와 어댑터, 포트 앤 어댑터).
  뜻이 더 넓거나 좁은 말, 관련어는 넣지 마라.
- broader: 이 개념을 **포함하는** 상위 개념 (변경 용이성 → 유지보수성). 확실할 때만, 없으면 [].
- 인명: 성, 전체 이름, 원어 표기를 모두 (아인슈타인 → Einstein, Albert Einstein, 알베르트 아인슈타인).
- 연도·숫자·문장형 라벨(설명문)은 {{"skip": true}}.
괄호 안 "쓰임"은 그 라벨이 그래프에서 어느 속성의 값인지다 — 뜻을 정하는 데 써라
(예: "eventual (쓰임: consistency_model)" → 결과적 일관성, eventual consistency). 키에는 쓰임을 빼고 라벨만 써라.

JSON 만 출력: {{"라벨": {{"ko": [...], "en": [...], "syn": [...], "broader": [...]}}, ...}}

라벨:
{labels}"""


_DASHES = re.compile(r"[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]")


def _compact(s: str) -> str:
    """정규화 키 — 유니코드 호환 정규화(NFKC) + 대시 통일 후 entity_linking._compact."""
    import unicodedata
    from app.services.retrieval.entity_linking import _compact as c
    t = unicodedata.normalize("NFKC", s or "")
    return c(_DASHES.sub("-", t))


def _skip_label(label: str) -> bool:
    from app.services.retrieval.entity_linking import is_sentence_like
    t = (label or "").strip()
    return (not t or len(t) > MAX_LABEL_LEN or is_sentence_like(t)
            or bool(re.fullmatch(r"[\d\s.,:년월일세기~\-()]+", t)) or not _compact(t))


def _variants(text: str) -> List[Tuple[str, float]]:
    """(표기, 점수 상한) — 일반어를 뺀 표기는 낮은 점수."""
    out = [(text, 1.0)]
    stripped = GENERIC_SUFFIX.sub("", (text or "").strip()).strip()
    if stripped and stripped != text.strip() and len(_compact(stripped)) >= 2:
        out.append((stripped, 0.0))
    return out


# ---------------------------------------------------------------------------
# 대상 라벨
# ---------------------------------------------------------------------------

async def collect_labels(kb_id: str) -> Dict[str, str]:
    """라벨 → 쓰임(유형 이름 또는 경로 키들). 유형 멤버의 rdfs:label + 카탈로그 값 라벨 (짧은 것)."""
    from app.services.agent_query.catalog import load_catalog, _labels_query
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    _kb, kinds, catalogs, _v = await load_catalog(kb_id)
    ctx: Dict[str, List[str]] = {}
    fb = FusekiBackend()
    for k in kinds:
        uris = list(k["members"])
        for i in range(0, len(uris), 200):
            rows = await asyncio.to_thread(fb._bindings, kb_id, _labels_query(uris[i:i + 200]))
            for r in rows:
                if r.get("l"):
                    ctx.setdefault(r["l"]["value"].strip(), []).append(k["name"])
    for ps in catalogs.values():
        for p in ps:
            for v in p.get("values") or []:
                if v.get("label"):
                    ctx.setdefault(v["label"].strip(), []).append(p["key"])
    return {l: ", ".join(dict.fromkeys(c))[:80] for l, c in sorted(ctx.items()) if not _skip_label(l)}


# ---------------------------------------------------------------------------
# 만들기
# ---------------------------------------------------------------------------

async def _llm_cfg(kb):
    from app.core.models_resolver import resolve_model_config
    stages = (getattr(kb, "pipeline_config", None) or {}).get("stages") or []
    g = next((s for s in stages if s.get("type") == "graph"), None)
    mc = ((g or {}).get("params") or {}).get("llm_model") or (getattr(kb, "chunking_config", None) or {}).get("llm_model")
    if not mc:
        raise RuntimeError("KB 에 LLM 모델 설정이 없음 (그래프 단계 llm_model)")
    return await resolve_model_config(mc)


async def _generate(cfg, domain: str, labels: Sequence[str], ctx: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    from app.core.llm import achat, no_thinking_extra_body
    from app.services.retrieval.relation_targeting import parse_json_loose
    ctx = ctx or {}
    lines = [f"{l} (쓰임: {ctx[l]})" if ctx.get(l) else l for l in labels]
    msg = PROMPT.format(domain=domain, labels="\n".join(lines))
    for attempt in range(2):
        raw = await achat(cfg, [{"role": "user", "content": msg}], model=cfg.get("model"), temperature=0,
                          max_tokens=8000, response_format={"type": "json_object"},
                          extra_body=no_thinking_extra_body(cfg.get("model")))
        data = parse_json_loose(raw)
        if isinstance(data, dict) and data:
            return data
    return {}


def _clean_list(xs: Any, label: str) -> List[str]:
    out, seen = [], {_compact(label)}
    for x in xs if isinstance(xs, list) else []:
        x = str(x).strip()
        k = _compact(x)
        if x and k and k not in seen and len(x) <= 60:
            seen.add(k)
            out.append(x)
    return out[:12]


async def _store(kb_id: str, label: str, data: Any, model: str, concept_only: bool = False):
    from app.models.lexicon import KbLexiconEntry
    norm = _compact(label)
    if not norm:
        return None
    existing = await KbLexiconEntry.find_one({"kb_id": kb_id, "norm": norm})
    if existing and existing.label != label and not existing.concept_only and not concept_only:
        # 정규화가 같은 다른 라벨 — 같은 항목의 변형으로 (별칭은 공유)
        if label not in existing.variants:
            existing.variants.append(label)
            await existing.save()
        return existing
    if existing and existing.source == "user":
        return existing
    d = data if isinstance(data, dict) else {}
    fields = dict(
        kb_id=kb_id, label=label, norm=norm,
        ko=_clean_list(d.get("ko"), label), en=_clean_list(d.get("en"), label), syn=_clean_list(d.get("syn"), label),
        broader=[{"label": b, "status": "proposed"} for b in _clean_list(d.get("broader"), label)[:5]],
        concept_only=concept_only, skip=bool(d.get("skip")), source="llm", model=model, updated_at=datetime.utcnow(),
    )
    if existing:
        if not concept_only and existing.concept_only:
            fields["concept_only"] = False
        for k, v in fields.items():
            setattr(existing, k, v)
        await existing.save()
        return existing
    e = KbLexiconEntry(**fields)
    await e.insert()
    return e


async def build_lexicon(kb_id: str, rebuild: bool = False) -> Dict[str, Any]:
    """사전에 없는 라벨만 생성 (rebuild=True 면 llm 항목 전부 다시). 상위 개념도 항목으로."""
    from app.models.lexicon import KbLexiconEntry
    from app.services.agent_query.catalog import _kb
    st = _BUILD_STATUS[kb_id] = {"state": "running", "started_at": time.time(), "done": 0, "total": 0, "error": None}
    try:
        kb = await _kb(kb_id)
        cfg = await _llm_cfg(kb)
        model = cfg.get("model")
        domain = f"{kb.name} — {(kb.description or '').strip()[:200]}"
        ctx = await collect_labels(kb_id)
        labels = list(ctx)
        have = {e.norm: e for e in await KbLexiconEntry.find({"kb_id": kb_id}).to_list()}
        # 정규화가 같은 라벨은 하나만 LLM 에 (나머지는 변형으로 붙인다)
        first: Dict[str, str] = {}
        for l in labels:
            first.setdefault(_compact(l), l)
        reps = list(first.values())
        def _empty(e) -> bool:
            return not e.skip and not (e.ko or e.en or e.syn)
        todo = [l for l in reps if rebuild and (have.get(_compact(l)) is None or have[_compact(l)].source != "user")
                or (not rebuild and (_compact(l) not in have or have[_compact(l)].concept_only
                                     or (have[_compact(l)].source != "user" and _empty(have[_compact(l)]))))]
        st["total"] = len(todo)

        async def run(batch: List[str], concept_only: bool):
            data = await _generate(cfg, domain, batch, None if concept_only else ctx)
            # 키 표기가 조금 달라도 맞추기
            by_norm = {_compact(k): v for k, v in data.items()}
            # 응답에서 빠진 라벨은 작은 묶음으로 한 번 더 (LLM 이 긴 목록의 일부를 건너뜀)
            missing = [l for l in batch if _compact(l) not in by_norm]
            if missing:
                st["retried"] = st.get("retried", 0) + len(missing)
                more = await _generate(cfg, domain, missing, None if concept_only else ctx)
                by_norm.update({_compact(k): v for k, v in more.items()})
            for l in batch:
                await _store(kb_id, l, by_norm.get(_compact(l), {}), model, concept_only)
            st["done"] += len(batch)

        batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
        await asyncio.gather(*(run(b, False) for b in batches))
        # 변형 라벨 등록 (LLM 없이)
        for l in labels:
            if first.get(_compact(l)) != l:
                await _store(kb_id, l, {}, model)

        # 상위 개념: 사전에 없는 말이면 항목으로 (예: 유지보수성 → maintainability)
        entries = await KbLexiconEntry.find({"kb_id": kb_id}).to_list()
        known = {e.norm for e in entries}
        alias_norms = {_compact(a) for e in entries for a in e.ko + e.en + e.syn}
        concepts = sorted({b["label"] for e in entries for b in e.broader
                           if _compact(b["label"]) not in known and _compact(b["label"]) not in alias_norms})
        st["total"] += len(concepts)
        cb = [concepts[i:i + BATCH] for i in range(0, len(concepts), BATCH)]
        await asyncio.gather(*(run(b, True) for b in cb))
        invalidate(kb_id)
        try:
            await _en_matrix(kb_id)         # 번역 대체 단계용 영어 표기 벡터를 미리 (첫 검색이 느리지 않게)
        except Exception as e:
            logger.warning("lexicon en vectors prewarm failed: %s", e)
        st.update(state="done", finished_at=time.time(), labels=len(labels), generated=len(todo), concepts=len(concepts))
        return dict(st)
    except Exception as e:
        logger.exception("lexicon build failed")
        st.update(state="error", error=str(e)[:500], finished_at=time.time())
        return dict(st)


def build_status(kb_id: str) -> Dict[str, Any]:
    return dict(_BUILD_STATUS.get(kb_id) or {"state": "idle"})


# ---------------------------------------------------------------------------
# 색인·찾기
# ---------------------------------------------------------------------------

def invalidate(kb_id: str) -> None:
    _INDEX_CACHE.pop(kb_id, None)
    _EN_CACHE.pop(kb_id, None)


async def get_index(kb_id: str) -> Dict[str, Any]:
    """{"terms": norm → {label: (score, via)}, "broader": norm → {label: status}, "entries": n}"""
    cached = _INDEX_CACHE.get(kb_id)
    if cached and time.time() - cached[0] < 300:
        return cached[1]
    from app.models.lexicon import KbLexiconEntry
    entries = await KbLexiconEntry.find({"kb_id": kb_id}).to_list()
    idx = build_index(entries)
    _INDEX_CACHE[kb_id] = (time.time(), idx)
    return idx


def build_index(entries: Sequence[Any]) -> Dict[str, Any]:
    """사전 항목 → 색인 (DB 없이 테스트 가능)."""
    terms: Dict[str, Dict[str, Tuple[float, str]]] = {}
    concept_alias: Dict[str, Set[str]] = {}   # 상위 개념 항목의 모든 표기 → 그 개념 norm

    def put(text: str, label: str, score: float, via: str):
        for v, full in _variants(text):
            k = _compact(v)
            if not k:
                continue
            s = score if full else min(score, SCORE_STRIPPED)
            cur = terms.setdefault(k, {}).get(label)
            if cur is None or s > cur[0]:
                terms[k][label] = (s, via if full else f"{via}·일반어제거")

    real = {e.norm: e for e in entries if not e.concept_only}
    lent: Dict[str, List[str]] = {}     # 실제 라벨 norm → 상위 개념 항목이 빌려주는 별칭
    for e in entries:
        if e.concept_only:
            forms = [e.label] + e.ko + e.en + e.syn
            for a in forms:
                concept_alias.setdefault(_compact(a), set()).add(e.norm)
            # 상위 개념 항목의 표기가 실제 라벨과 같으면 그 라벨의 별칭으로 (배포성 ≡ deployability → '배포 용이성')
            for a in forms:
                if _compact(a) in real:
                    lent.setdefault(_compact(a), []).extend(forms)
    for e in entries:
        if e.concept_only:
            continue
        # 설명형 라벨(4어절 이상)은 이름이 아니라 별칭을 색인하지 않는다 — 엉뚱한 일치 방지
        descriptive = len((e.label or "").split()) >= 4
        for lab in [e.label] + list(e.variants or []):
            put(lab, lab, SCORE_LABEL, "label")
            if e.skip or descriptive:
                continue
            for a in lent.get(e.norm, []):
                put(a, lab, SCORE_ALIAS, "concept")
            for kind, xs in (("ko", e.ko), ("en", e.en), ("syn", e.syn)):
                for a in xs:
                    put(a, lab, SCORE_ALIAS, kind)
    # 상위 개념 → 하위 라벨
    broader: Dict[str, Dict[str, str]] = {}
    for e in entries:
        if e.concept_only:
            continue
        for b in e.broader:
            if b.get("status") == "rejected":
                continue
            bn = _compact(b["label"])
            for k in {bn} | {a for a, ns in concept_alias.items() if bn in ns}:
                for lab in [e.label] + list(e.variants or []):
                    broader.setdefault(k, {})[lab] = b.get("status", "proposed")
    return {"terms": terms, "broader": broader, "entries": len(entries)}


def match_term(idx: Dict[str, Any], term: str) -> List[Dict[str, Any]]:
    """질문 표기 → [{"label", "score", "via"}] (점수 순). 일반어를 뺀 표기로도 한 번 더."""
    out: Dict[str, Tuple[float, str]] = {}
    for v, full in _variants(term):
        for label, (s, via) in (idx["terms"].get(_compact(v)) or {}).items():
            s = s if full else min(s, SCORE_STRIPPED)
            if label not in out or s > out[label][0]:
                out[label] = (s, via)
    return [{"label": l, "score": s, "via": v} for l, (s, v) in sorted(out.items(), key=lambda x: -x[1][0])]


def narrower_of(idx: Dict[str, Any], term: str) -> List[Dict[str, Any]]:
    """상위 개념 → 하위 라벨 [{"label", "reviewed"}]."""
    got: Dict[str, str] = {}
    for v, _full in _variants(term):
        got.update(idx["broader"].get(_compact(v)) or {})
    return [{"label": l, "reviewed": st == "approved"} for l, st in sorted(got.items())]


async def duplicates(kb_id: str) -> List[Dict[str, Any]]:
    """같은 표기(라벨·별칭)가 둘 이상의 라벨을 가리키는 경우 — 중복 엔티티 후보."""
    from app.models.lexicon import KbLexiconEntry
    idx = await get_index(kb_id)
    # 정규화 키 → 사람이 읽을 표기 (화면·별칭 삭제용)
    shown: Dict[str, str] = {}
    for e in await KbLexiconEntry.find({"kb_id": kb_id}).to_list():
        for f in [e.label] + list(e.variants or []) + e.ko + e.en + e.syn:
            shown.setdefault(_compact(f), f)
    groups: Dict[Tuple[str, ...], Set[str]] = {}
    for norm, labs in idx["terms"].items():
        strong = sorted(l for l, (s, _v) in labs.items() if s >= SCORE_ALIAS)
        if len(strong) >= 2:
            groups.setdefault(tuple(strong), set()).add(norm)
    return [{"labels": list(k), "shared": sorted({shown.get(n, n) for n in v})[:5]}
            for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))]


# ---------------------------------------------------------------------------
# 번역 대체 단계 — 사전에 없을 때, 클라이언트가 보낸 영어 표기(term_en)를 영어 표기 임베딩과 비교
# docs/design/agent/design-kb-lexicon.md §5.1
# ---------------------------------------------------------------------------

EN_SIM_THRESHOLD = 0.80     # 이 이상이면 후보 (홀드아웃·negative 로 정함)
EN_SIM_MARGIN = 0.03        # 1위 라벨이 2위 라벨보다 이만큼 높아야 확정 (아니면 후보만)
SCORE_TRANSLATED = 80.0

_EN_CACHE: Dict[str, Tuple[float, Any]] = {}


def _is_ascii_word(s: str) -> bool:
    t = (s or "").strip()
    return bool(t) and all(ord(c) < 0x250 for c in t) and any(c.isalpha() for c in t)


def english_forms(entries: Sequence[Any]) -> Dict[str, Set[str]]:
    """영어 표기 → 라벨 집합. 영문 라벨 자체 + en 별칭 + 영문 동의어 (+ 상위 개념 항목이 빌려준 영어 표기)."""
    real = {e.norm: e for e in entries if not e.concept_only}
    forms: Dict[str, Set[str]] = {}

    def add(f: str, lab: str):
        f = (f or "").strip().replace("_", " ")
        if _is_ascii_word(f) and len(f) <= 60:
            forms.setdefault(f, set()).add(lab)

    for e in entries:
        if e.concept_only:
            continue
        if len((e.label or "").split()) >= 4:      # 설명형 라벨은 제외 (색인 규칙과 같음)
            continue
        for lab in [e.label] + list(e.variants or []):
            add(lab, lab)
            if e.skip:
                continue
            for x in list(e.en) + [s for s in e.syn if _is_ascii_word(s)]:
                add(x, lab)
    for e in entries:
        if not e.concept_only:
            continue
        all_forms = [e.label] + e.ko + e.en + e.syn
        for a in all_forms:
            tgt = real.get(_compact(a))
            if tgt is not None:
                for x in all_forms:
                    add(x, tgt.label)
    return forms


async def _en_matrix(kb_id: str):
    """(forms, labels_per_form, 정규화된 임베딩 행렬) — 사전 빌드 후 첫 사용 때 계산해 캐시."""
    import numpy as np
    cached = _EN_CACHE.get(kb_id)
    if cached and time.time() - cached[0] < 24 * 3600:     # 사전 빌드·편집 때 invalidate 로 비움
        return cached[1]
    from app.models.lexicon import KbLexiconEntry
    from app.services.agent_query.catalog import _kb
    from app.services.embedding import get_embedding_service
    entries = await KbLexiconEntry.find({"kb_id": kb_id}).to_list()
    fm = english_forms(entries)
    forms = sorted(fm)
    if not forms:
        val = ([], [], None)
    else:
        emb = await get_embedding_service(await _kb(kb_id))
        vecs = []
        for i in range(0, len(forms), 500):
            vecs.extend(await emb.get_embeddings(forms[i:i + 500]))
        m = np.array(vecs, dtype="float32")
        m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
        val = (forms, [sorted(fm[f]) for f in forms], m)
    _EN_CACHE[kb_id] = (time.time(), val)
    return val


_QVEC: Dict[Tuple[str, str], Tuple[float, Any]] = {}


async def prefetch_query_vectors(kb_id: str, texts: Sequence[str]) -> None:
    """번역 대체 단계에 쓸 질의 벡터를 한 번에 계산해 둔다 (용어마다 따로 부르면 용어 수 × 0.2~0.3초)."""
    import numpy as np
    now = time.time()
    need = [t for t in dict.fromkeys(x.strip() for x in texts if x and x.strip())
            if not ((kb_id, t) in _QVEC and now - _QVEC[(kb_id, t)][0] < 600)]
    if not need:
        return
    from app.services.agent_query.catalog import _kb
    from app.services.embedding import get_embedding_service
    emb = await get_embedding_service(await _kb(kb_id))
    vecs = await emb.get_embeddings(need)
    for t, v in zip(need, vecs):
        q = np.array(v, dtype="float32")
        _QVEC[(kb_id, t)] = (now, q / (np.linalg.norm(q) + 1e-9))
    if len(_QVEC) > 5000:
        for k in sorted(_QVEC, key=lambda k: _QVEC[k][0])[:1000]:
            _QVEC.pop(k, None)


async def match_translated(kb_id: str, idx: Dict[str, Any], term_en: str, top: int = 3) -> Dict[str, Any]:
    """영어 표기로 찾기: ① 사전 정확 일치 → ② 영어 표기 임베딩 유사도.

    반환 {"matches": [...확정...], "candidates": [...후보...]} — 확정은 기준·차이를 모두 넘을 때만.
    """
    import numpy as np
    term_en = (term_en or "").strip()
    if not term_en:
        return {"matches": [], "candidates": []}
    exact = [m for m in match_term(idx, term_en) if m["score"] >= SCORE_STRIPPED]
    if exact:
        return {"matches": [{**m, "score": min(m["score"], 95.0), "via": f"en:{m['via']}"} for m in exact],
                "candidates": []}
    forms, labs, m = await _en_matrix(kb_id)
    if m is None:
        return {"matches": [], "candidates": []}
    await prefetch_query_vectors(kb_id, [term_en])
    q = _QVEC[(kb_id, term_en)][1]
    sims = m @ q
    # 라벨별 최고 유사도
    best: Dict[str, Tuple[float, str]] = {}
    for j in np.argsort(-sims)[:50]:
        for lab in labs[j]:
            if lab not in best:
                best[lab] = (float(sims[j]), forms[j])
    ranked = sorted(best.items(), key=lambda x: -x[1][0])
    cands = [{"label": l, "similarity": round(s, 3), "via": f"translated:{f}"} for l, (s, f) in ranked[:top]
             if s >= EN_SIM_THRESHOLD - 0.1]
    if ranked and ranked[0][1][0] >= EN_SIM_THRESHOLD:
        s1 = ranked[0][1][0]
        s2 = ranked[1][1][0] if len(ranked) > 1 else 0.0
        if s1 - s2 >= EN_SIM_MARGIN:
            l, (s, f) = ranked[0]
            return {"matches": [{"label": l, "score": SCORE_TRANSLATED, "similarity": round(s, 3),
                                 "via": f"translated:{f}"}], "candidates": cands}
    return {"matches": [], "candidates": cands}


# ---------------------------------------------------------------------------
# 사람 편집 (L3, 스키마 편집기 "용어 사전" 탭) — 고친 항목은 source=user 로 재생성 때 보존
# ---------------------------------------------------------------------------

class LexiconEditError(ValueError):
    pass


async def _entry(kb_id: str, label: str):
    from app.models.lexicon import KbLexiconEntry
    e = await KbLexiconEntry.find_one({"kb_id": kb_id, "norm": _compact(label)})
    if e is None:
        raise LexiconEditError(f"사전에 '{label}' 항목이 없음")
    return e


def _clean_user_list(xs: Sequence[str], label: str) -> List[str]:
    out, seen = [], {_compact(label)}
    for x in xs or []:
        x = str(x).strip()
        k = _compact(x)
        if x and k and k not in seen and len(x) <= 60:
            seen.add(k)
            out.append(x)
    return out[:30]


async def edit_entry(kb_id: str, label: str, ko=None, en=None, syn=None) -> Dict[str, Any]:
    e = await _entry(kb_id, label)
    if ko is not None:
        e.ko = _clean_user_list(ko, e.label)
    if en is not None:
        e.en = _clean_user_list(en, e.label)
    if syn is not None:
        e.syn = _clean_user_list(syn, e.label)
    e.skip = False
    e.source = "user"
    e.updated_at = datetime.utcnow()
    await e.save()
    invalidate(kb_id)
    return e.model_dump(exclude={"id", "revision_id"})


async def remove_alias(kb_id: str, alias: str, labels: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """별칭 삭제 — labels 를 주면 그 항목들에서만, 아니면 그 별칭을 가진 모든 항목에서 (중복 묶음의 잡음 별칭 정리)."""
    from app.models.lexicon import KbLexiconEntry
    k = _compact(alias)
    targets = [await _entry(kb_id, l) for l in labels] if labels else await KbLexiconEntry.find({"kb_id": kb_id}).to_list()
    changed = []
    for e in targets:
        before = len(e.ko) + len(e.en) + len(e.syn)
        e.ko = [x for x in e.ko if _compact(x) != k]
        e.en = [x for x in e.en if _compact(x) != k]
        e.syn = [x for x in e.syn if _compact(x) != k]
        if len(e.ko) + len(e.en) + len(e.syn) != before:
            e.source = "user"
            e.updated_at = datetime.utcnow()
            await e.save()
            changed.append(e.label)
    invalidate(kb_id)
    return {"removed_from": changed}


async def set_broader(kb_id: str, label: str, broader: str, status: str) -> Dict[str, Any]:
    """상위 개념 승인(approved)·거절(rejected)·추가(없던 상위 개념이면 approved 로 추가)."""
    if status not in ("approved", "rejected", "proposed"):
        raise LexiconEditError("status 는 approved | rejected | proposed")
    e = await _entry(kb_id, label)
    hit = next((b for b in e.broader if _compact(b["label"]) == _compact(broader)), None)
    if hit is None:
        if status == "rejected":
            raise LexiconEditError(f"'{label}' 에 상위 개념 '{broader}' 가 없음")
        e.broader.append({"label": broader.strip(), "status": status})
    else:
        hit["status"] = status
    e.source = "user"
    e.updated_at = datetime.utcnow()
    await e.save()
    invalidate(kb_id)
    return e.model_dump(exclude={"id", "revision_id"})


async def review_queue(kb_id: str, limit: int = 300) -> List[Dict[str, Any]]:
    """검토 전(proposed) 상위 개념 — 상위 개념별로 묶어서 (같은 상위 개념을 한 번에 승인·거절)."""
    from app.models.lexicon import KbLexiconEntry
    groups: Dict[str, List[str]] = {}
    for e in await KbLexiconEntry.find({"kb_id": kb_id, "concept_only": False}).to_list():
        for b in e.broader:
            if b.get("status", "proposed") == "proposed":
                groups.setdefault(b["label"], []).append(e.label)
    rows = [{"broader": k, "labels": sorted(v)} for k, v in groups.items()]
    rows.sort(key=lambda r: (-len(r["labels"]), r["broader"]))
    return rows[:limit]


# ---------------------------------------------------------------------------
# L4 — 자동 갱신 + 내부 검색 연결
# ---------------------------------------------------------------------------

AUTO_REFRESH_MIN_INTERVAL_S = 600
_LAST_FP: Dict[str, Tuple[str, float]] = {}


async def ensure_fresh(kb_id: str) -> None:
    """그래프가 바뀌었으면(카탈로그 지문 변경) 사전에 새 라벨을 증분 반영 — 백그라운드, 10분에 한 번까지.

    사전을 한 번이라도 만든 KB 에만 (원치 않는 LLM 비용 방지). 새 라벨이 없으면 LLM 호출 0.
    적재·재추출·리플레이 어느 경로로 그래프가 바뀌어도 잡히도록 지문 기준으로 한다.
    """
    try:
        from app.models.lexicon import KbLexiconEntry
        from app.services.retrieval.graph_backends.fuseki import FusekiBackend
        cached = FusekiBackend._CLASS_CATALOG_CACHE.get(kb_id)
        if not cached:
            return
        fp = cached[0]
        prev = _LAST_FP.get(kb_id)
        if prev is None:
            _LAST_FP[kb_id] = (fp, time.time())      # 서버 시작 후 첫 확인 — 기준만 잡는다
            return
        if prev[0] == fp or time.time() - prev[1] < AUTO_REFRESH_MIN_INTERVAL_S:
            return
        _LAST_FP[kb_id] = (fp, time.time())
        # 그래프가 바뀌었다 — 각 후속 작업은 그 기능을 켠 KB 에서만 돈다
        try:   # 새 트리플의 관계 방향 검증 + 확실한 반대 방향 자동 뒤집기 (D1, 방향 검증을 한 번 실행한 KB)
            from app.services.schema_alignment.direction_audit import auto_audit_if_enabled
            asyncio.create_task(auto_audit_if_enabled(kb_id, "graph_changed"))
        except Exception:
            pass
        if build_status(kb_id).get("state") == "running":
            return
        if await KbLexiconEntry.find_one({"kb_id": kb_id}) is None:
            return
        logger.info("lexicon auto-refresh %s (fingerprint %s → %s)", kb_id, prev[0], fp)
        asyncio.create_task(build_lexicon(kb_id))
    except Exception as e:     # 검색을 막지 않는다
        logger.warning("lexicon ensure_fresh failed: %s", e)


async def expand_query_entities(kb_id: str, entities: Sequence[str], translated: Sequence[str]) -> Dict[str, Any]:
    """내부 검색(/chat)용: 질문 분석이 뽑은 엔티티를 사전으로 그래프 표기에 맞춘다.

    ① 원문 엔티티 → 사전 일치 ② 질문 분석의 영어 번역(translated_entities) → 사전 일치 → 없으면 영어 표기 임베딩.
    반환: {"added": [그래프 라벨], "log": [사람이 읽을 근거]}. 사전이 없는 KB 면 빈 결과.
    """
    await ensure_fresh(kb_id)
    idx = await get_index(kb_id)
    if not idx["entries"]:
        return {"added": [], "log": []}
    added: List[str] = []
    log: List[str] = []

    def take(src: str, ms: List[Dict[str, Any]], how: str):
        top = [m for m in ms if m["score"] >= SCORE_STRIPPED][:2]
        for m in top:
            if m["label"] not in added and _compact(m["label"]) != _compact(src):
                added.append(m["label"])
                log.append(f"{src} → {m['label']} ({how}:{m['via']})")
        return bool(top)

    for e in entities or []:
        take(e, match_term(idx, e), "사전")
    for t in translated or []:
        if take(t, match_term(idx, t), "사전·영어"):
            continue
        tr = await match_translated(kb_id, idx, t)
        for m in tr["matches"]:
            if m["label"] not in added:
                added.append(m["label"])
                log.append(f"{t} → {m['label']} (영어 유사도 {m.get('similarity')})")
    return {"added": added, "log": log}


# ---------------------------------------------------------------------------
# 데이터 품질 D2 — 중복 후보 판정 제안 (같은 대상이면 병합, 다른 대상이면 공유 별칭만 삭제)
# 결과는 저장만 한다. 적용은 사람이 승인 후 (병합 = schema_editor.merge_entities, 별칭 삭제 = remove_alias)
# ---------------------------------------------------------------------------

DUP_PROMPT = """아래는 지식 그래프({domain})에서 같은 별칭을 공유하는 라벨 묶음이다.
묶음마다 판정하라:
- merge: 모두 같은 대상(같은 사람·같은 이론·같은 장소)의 다른 표기다. canonical 은 가장 완전한 이름
  (사람이면 전체 이름, 예: '조머펠트' 와 '아르놀드 조머펠트' → '아르놀드 조머펠트'). 묶음 일부만 같으면 same 에 그 라벨들만.
- distinct: 서로 다른 대상인데 일반적인 별칭(예: '대학', 'institution of higher education')이나 잘못 붙은 별칭을 공유한다.
  remove_aliases 에 지울 공유 별칭을 적는다.
- unsure: 주어진 정보로 판단 불가.
관계 정보(각 라벨이 그래프에서 무엇과 연결되는지)를 근거로 삼아라. reason 은 한 줄.

{groups}

JSON 만: {{"results": [{{"id": 번호, "decision": "merge|distinct|unsure", "canonical": "...", "same": ["..."], "remove_aliases": ["..."], "reason": "..."}}]}}"""


async def review_duplicates(kb_id: str) -> Dict[str, Any]:
    from app.core.llm import achat, no_thinking_extra_body
    from app.models.knowledge_base import KnowledgeBase
    from app.services.agent_query.catalog import _kb, describe_entity
    from app.services.retrieval.relation_targeting import parse_json_loose
    t0 = time.time()
    kb = await _kb(kb_id)
    cfg = await _llm_cfg(kb)
    groups = await duplicates(kb_id)
    ctx_lines = []
    for n, g in enumerate(groups):
        parts = []
        for lab in g["labels"]:
            try:
                d = await describe_entity(kb_id, lab)
                rels = [f"{x['p']}→{x['o']}" for x in (d.get("out") or [])[:5]] + [f"{x['s']}→{x['p']}" for x in (d.get("in") or [])[:3]]
                parts.append(f"  · {lab} ({(d.get('entity') or {}).get('kind', '?')}): {'; '.join(rels) or '관계 없음'}")
            except Exception:
                parts.append(f"  · {lab}: (조회 실패)")
        ctx_lines.append(f"{n}. 라벨 {g['labels']} / 공유 별칭 {g['shared']}\n" + "\n".join(parts))
    domain = f"{kb.name} — {(kb.description or '')[:120]}"
    out: Dict[int, Dict[str, Any]] = {}

    async def judge(k: int):
        chunk = ctx_lines[k:k + 15]
        for _ in range(2):
            raw = await achat(cfg, [{"role": "user", "content": DUP_PROMPT.format(domain=domain, groups="\n".join(chunk))}],
                              model=cfg.get("model"), temperature=0, max_tokens=6000,
                              response_format={"type": "json_object"}, extra_body=no_thinking_extra_body(cfg.get("model")))
            data = parse_json_loose(raw)
            if isinstance(data, dict) and data.get("results"):
                for r in data["results"]:
                    try:
                        out[int(r.get("id"))] = r
                    except (TypeError, ValueError):
                        pass
                return

    await asyncio.gather(*(judge(k) for k in range(0, len(ctx_lines), 15)))
    items = []
    for n, g in enumerate(groups):
        r = out.get(n) or {}
        dec = str(r.get("decision") or "unsure").lower()
        same = [x for x in (r.get("same") or g["labels"]) if x in g["labels"]] or g["labels"]
        canon = r.get("canonical") if r.get("canonical") in g["labels"] else (same[0] if same else g["labels"][0])
        items.append({"labels": g["labels"], "shared": g["shared"],
                      "decision": dec if dec in ("merge", "distinct", "unsure") else "unsure",
                      "canonical": canon, "same": same,
                      "remove_aliases": [a for a in (r.get("remove_aliases") or []) if isinstance(a, str)][:10],
                      "reason": str(r.get("reason") or "")[:300]})
    from collections import Counter
    result = {"at": datetime.utcnow().isoformat(), "model": cfg.get("model"), "items": items,
              "summary": dict(Counter(i["decision"] for i in items)), "elapsed_s": round(time.time() - t0, 1)}
    kb2 = await KnowledgeBase.get(kb_id)
    meta = dict(kb2.promotion_metadata or {})
    meta["duplicate_review"] = result
    kb2.promotion_metadata = meta
    await kb2.save()
    return {k: v for k, v in result.items() if k != "items"} | {"total": len(items)}


async def get_duplicate_review(kb_id: str) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    return ((kb.promotion_metadata or {}).get("duplicate_review")) or {"items": []}



async def absorb_merged(kb_id: str, canonical: str, aliases: Sequence[str]) -> int:
    """병합된 이름을 대표 항목의 별칭으로 옮긴다 (데이터 품질 D2).
    '조머펠트' → '아르놀드 조머펠트' 병합 뒤에도 '조머펠트' 로 찾을 수 있게. 옮긴 이름의 별칭도 함께 가져온다."""
    from app.models.lexicon import KbLexiconEntry
    canon = await KbLexiconEntry.find_one({"kb_id": kb_id, "norm": _compact(canonical)})
    if canon is None:
        canon = KbLexiconEntry(kb_id=kb_id, label=canonical, norm=_compact(canonical), source="user")
        await canon.insert()
    moved = 0
    for a in aliases:
        e = await KbLexiconEntry.find_one({"kb_id": kb_id, "norm": _compact(a)})
        extra = [a] + ((e.ko + e.syn) if e else [])
        en = list(e.en) if e else []
        canon.ko = _clean_user_list(list(canon.ko) + [x for x in extra if not _is_ascii_word(x)], canon.label)
        canon.en = _clean_user_list(list(canon.en) + en + [x for x in extra if _is_ascii_word(x)], canon.label)
        if e is not None and e.id != canon.id and _compact(a) != canon.norm:
            await e.delete()
        moved += 1
    canon.source = "user"
    canon.updated_at = datetime.utcnow()
    await canon.save()
    invalidate(kb_id)
    return moved
