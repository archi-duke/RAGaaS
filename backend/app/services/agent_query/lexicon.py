"""KB 용어 사전 — 적재 후 LLM 으로 별칭을 한 번 만들고, 검색할 때는 사전만 찾는다 (docs/design-kb-lexicon.md).

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
    idx = await get_index(kb_id)
    groups: Dict[Tuple[str, ...], Set[str]] = {}
    for norm, labs in idx["terms"].items():
        strong = sorted(l for l, (s, _v) in labs.items() if s >= SCORE_ALIAS)
        if len(strong) >= 2:
            groups.setdefault(tuple(strong), set()).add(norm)
    return [{"labels": list(k), "shared": sorted(v)[:5]} for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))]
