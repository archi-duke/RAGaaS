"""P1: describe_kb / lookup_values / resolve_entities / get_chunks — LLM 호출 없음.

출처는 질의 계획이 쓰는 유형·경로 카탈로그(FusekiBackend._class_catalog, 지문+TTL 캐시)다.
docs/design-mcp-agent-query.md §4.2 ~ §4.6
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException

# 관계 이름의 부호·강도 토큰 (has_moderate_negative_effect_on → polarity=negative, strength=moderate)
_POLARITY = {"positive": "positive", "negative": "negative", "긍정": "positive", "부정": "negative"}
_STRENGTH = {"strong": "strong", "moderate": "moderate", "weak": "weak", "강한": "strong", "중간": "moderate", "약한": "weak"}

MAX_VALUES_DEFAULT = 15
MAX_VALUES_LIMIT = 200
MAX_CHUNKS = 50
MAX_MEMBER_NAMES = 150


def _local_label(uri: str) -> str:
    from urllib.parse import unquote
    return unquote(str(uri).rstrip("/").rsplit("/", 1)[-1]).replace("_", " ")


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

async def _kb(kb_id: str):
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"KB {kb_id} 없음")
    return kb


def _backend_of(kb) -> str:
    return (getattr(kb, "graph_backend", None) or "none").lower()


async def load_catalog(kb_id: str) -> Tuple[Any, List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], str]:
    """(kb, kinds, catalogs, schema_version). ontology(Fuseki) KB 만 — Neo4j 는 P7."""
    kb = await _kb(kb_id)
    backend = _backend_of(kb)
    if backend != "ontology":
        raise HTTPException(status_code=400, detail=f"질의 가능한 그래프 KB 가 아님 (graph_backend={backend}). "
                                                    "현재 ontology(Fuseki) KB 만 지원 — Neo4j 는 예정")
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    fb = FusekiBackend()
    kinds, catalogs = await fb._class_catalog(kb_id, lambda _m: None, {})
    cached = FusekiBackend._CLASS_CATALOG_CACHE.get(kb_id)
    fingerprint = cached[0] if cached else "0"
    return kb, kinds, catalogs, schema_version(kb, fingerprint, catalogs)


def schema_version(kb, fingerprint: str, catalogs: Dict[str, List[Dict[str, Any]]]) -> str:
    """스키마·데이터가 바뀌면 달라지는 버전 문자열 — 에이전트 캐시가 낡았는지 판단용."""
    keys = sorted(f"{k}:{p['key']}:{p.get('type')}:{p.get('description', '')}" for k, ps in catalogs.items() for p in ps)
    meta = getattr(kb, "promotion_metadata", None) or {}
    induced = str((meta.get("induction") or {}).get("updated_at") or (meta.get("induction") or {}).get("version") or "")
    h = hashlib.sha1(("|".join(keys) + "#" + fingerprint + "#" + induced).encode("utf-8")).hexdigest()[:12]
    return h


def relation_traits(key: str) -> Dict[str, str]:
    """경로 키에서 계열·부호·강도를 뽑는다 (있을 때만)."""
    from app.services.schema_alignment.schema_editor import family_key
    leaf = key.split(".")[-1]
    toks = re.split(r"[_\s]+", leaf.lower())
    out: Dict[str, str] = {}
    pol = next((_POLARITY[t] for t in toks if t in _POLARITY), None)
    strength = next((_STRENGTH[t] for t in toks if t in _STRENGTH), None)
    if pol:
        out["polarity"] = pol
        out["strength"] = strength or "strong"   # 강도 표기가 없으면 기본(강한) — test-ontology2 규약
        out["family"] = family_key(leaf)
    return out


# ---------------------------------------------------------------------------
# describe_kb (§4.2)
# ---------------------------------------------------------------------------

def _path_view(p: Dict[str, Any], max_values: int) -> Dict[str, Any]:
    v: Dict[str, Any] = {"key": p["key"], "type": p.get("type")}
    if p.get("description"):
        v["description"] = p["description"]
    if p.get("aliases"):
        v["aliases"] = list(p["aliases"])
    if p.get("equiv"):
        v["equiv"] = list(p["equiv"])
    if p.get("equiv_rep") and p["equiv_rep"] != p["key"]:
        v["same_as"] = p["equiv_rep"]          # 이 경로 대신 same_as 를 쓰면 함께 조회됨
    if p.get("coverage") is not None:
        v["coverage"] = round(float(p["coverage"]), 2)
    if p.get("ref_kind"):
        v["ref_kind"] = p["ref_kind"]
    v.update(relation_traits(p["key"]))
    t = p.get("type")
    if t == "enum" or (t == "text" and p.get("values")):
        vals = p.get("values") or []
        # text 경로도 값이 짧은 라벨이면 어휘로 준다 (예: has_positive_effect_on 값 20여 종) — 문장형 값은 예시만
        short = [x for x in vals if len(x.get("label") or "") <= 40]
        if t == "enum" or len(short) >= max(1, len(vals) // 2):
            # 설명형 긴 값은 어휘에서 뺀다 (토큰 절약 — contains 로 찾으면 된다)
            v["values"] = [{"label": x["label"], "members": x.get("members", 0)} for x in short[:max_values]]
            v["values_truncated"] = len(short) > max_values
            if len(short) < len(vals):
                v["long_values_omitted"] = len(vals) - len(short)
        else:
            v["examples"] = [x["label"] for x in vals[: min(max_values, 10)]]
        v["distinct"] = p.get("dv", len(vals))
    elif t == "number":
        lo, hi = (p.get("range") or [0, 0])[:2]
        v["range"] = [lo, hi]
    else:
        v["examples"] = list(p.get("examples") or [])[:10]
        v["distinct"] = p.get("dv")
    return v


def _path_members(p: Dict[str, Any]) -> int:
    ids = p.get("member_ids")
    if ids:
        return len(set(ids))
    return max([v.get("members", 0) for v in p.get("values") or []] or [0])


def _path_line(v: Dict[str, Any]) -> str:
    """경로 한 줄 — compact 형식 (JSON 보다 토큰 약 절반)."""
    tags = [v["type"]]
    if v.get("polarity"):
        tags.append(f"{v['family']}:{v['polarity']}/{v['strength']}")
    if v.get("same_as"):
        tags.append(f"same_as={v['same_as']}")
    if v.get("ref_kind"):
        tags.append(f"ref={v['ref_kind']}")
    head = f"{v['key']} [{', '.join(tags)}]"
    if v.get("description"):
        head += f" — {v['description'][:80]}"
    if v.get("values"):
        vals = ", ".join(f"{x['label']}({x['members']})" for x in v["values"])
        more = "…" if v.get("values_truncated") else ""
        return f"{head}: {vals}{more}"
    if v.get("range"):
        return f"{head}: {v['range'][0]}~{v['range'][1]}"
    if v.get("examples"):
        return f"{head}: 예) {' / '.join(str(x)[:40] for x in v['examples'][:4])}"
    return head


async def describe_kb(kb_id: str, kinds_filter: Optional[Sequence[str]] = None,
                      max_values: int = MAX_VALUES_DEFAULT, fmt: str = "json",
                      min_members: int = 2) -> Dict[str, Any]:
    """fmt=compact: 경로를 한 줄 문자열로 (MCP 기본). min_members: 이 수보다 적은 엔티티만 가진 경로는 숨김
    (단일 엔티티 사실은 describe_entity 로 — 평가 13 에서 물리학사 경로 111개 중 다수가 1명짜리 잡음)."""
    max_values = max(1, min(int(max_values or MAX_VALUES_DEFAULT), MAX_VALUES_LIMIT))
    kb, kinds, catalogs, version = await load_catalog(kb_id)
    wanted = set(kinds_filter or [])
    meta = getattr(kb, "promotion_metadata", None) or {}
    structured = bool(meta.get("structured") or meta.get("schema_overlay"))
    out_kinds, out_paths = [], {}
    hidden: Dict[str, int] = {}
    for k in kinds:
        if wanted and k["name"] not in wanted:
            continue
        names = [_local_label(u) for u in k["members"]]
        out_kinds.append({"name": k["name"], "description": k.get("description", ""),
                          "members": len(k["members"]),
                          # 멤버 이름 — 에이전트가 질문 속 표기('마이크로서비스')를 그래프 표기('Microservices')로 직접 맞출 수 있게
                          "member_names": names[:MAX_MEMBER_NAMES], "member_names_truncated": len(names) > MAX_MEMBER_NAMES})
        ps = catalogs.get(k["name"], [])
        shown = [p for p in ps if _path_members(p) >= max(1, int(min_members or 1))]
        views = [_path_view(p, max_values) for p in shown]
        out_paths[k["name"]] = [_path_line(v) for v in views] if fmt == "compact" else views
        if len(shown) < len(ps):
            hidden[k["name"]] = len(ps) - len(shown)
    notes = [
        "질의는 query_plan 으로 보낸다 — path 는 이 목록의 key, value 는 values 의 label 표기 그대로.",
        "text 경로는 op=contains, enum 경로는 eq/in. 목록에 없는 값은 lookup_values 로 먼저 맞춘다.",
        "같은 family 의 관계(부호·강도만 다름)를 '긍정 전체' 로 찾으려면 any(OR) 로 묶는다. AND 로 묶지 않는다.",
        "same_as 가 있는 경로는 대표 경로(same_as)를 쓰면 함께 조회된다.",
    ]
    return {
        "schema_version": version,
        "kb": {"id": kb_id, "name": kb.name, "backend": "fuseki", "kind": "structured" if structured else "text"},
        "kinds": out_kinds,
        "paths": out_paths,
        **({"rare_paths_hidden": hidden} if hidden else {}),
        "notes": notes + (["엔티티 1개만 가진 경로는 숨겼다 (min_members=1 이면 모두) — 특정 엔티티의 사실은 describe_entity 로."]
                          if hidden else [])
                 + (["compact 형식: key [type, 계열:부호/강도] — 정의: 값(엔티티 수), …"] if fmt == "compact" else []),
    }


# ---------------------------------------------------------------------------
# lookup_values (§4.3) — 말 → 경로별 값 후보
# ---------------------------------------------------------------------------

def _score(term: str, label: str) -> float:
    from app.services.retrieval.entity_linking import score_candidate, _compact
    s = score_candidate(term, label)
    if s:
        return s
    # 짧은 말(2자 이하)·문장형 값은 score_candidate 가 거르므로 정규화 일치만 따로
    tc, lc = _compact(term), _compact(label)
    if tc and tc == lc:
        return 100.0
    return 0.0


def _contains(term: str, label: str) -> bool:
    from app.services.retrieval.entity_linking import _compact
    tc, lc = _compact(term), _compact(label)
    return bool(tc) and len(tc) >= 2 and tc in lc


async def lookup_values(kb_id: str, terms: Sequence[str], kind: Optional[str] = None,
                        limit: int = 8, terms_en: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """terms_en: 클라이언트가 보낸 영어 표기 (오탈자 교정 포함). 사전에 없을 때만 쓴다 (§5.1)."""
    from app.services.agent_query import lexicon as lx
    _kb_, kinds, catalogs, version = await load_catalog(kb_id)
    idx = await lx.get_index(kb_id)
    # 값 라벨 → 등장 위치 (유형·경로)
    where: Dict[str, List[Dict[str, Any]]] = {}
    for k in kinds:
        if kind and k["name"] != kind:
            continue
        for p in catalogs.get(k["name"], []):
            # 동치 경로의 값도 포함 — 보고는 대표 경로로 (대표 경로로 조회하면 동치 경로가 함께 조회됨)
            rep = p.get("equiv_rep") or p["key"]
            for v in p.get("values") or []:
                where.setdefault(v.get("label") or "", []).append(
                    {"kind": k["name"], "path": rep, "value": v.get("label"), "members": v.get("members", 0)})
    for lab, ws in where.items():
        where[lab] = _dedupe(ws)
    terms = [t.strip() for t in (terms or []) if t and t.strip()][:20]
    matches: Dict[str, List[Dict[str, Any]]] = {}
    related: Dict[str, List[Dict[str, Any]]] = {}
    narrower: Dict[str, List[Dict[str, Any]]] = {}
    suggestions: Dict[str, List[Dict[str, Any]]] = {}
    await _prefetch_fallback(kb_id, idx, terms, terms_en)
    for term in terms:
        hits, rel = [], []
        # 용어 사전 (한영·음역·동의어) — docs/design-kb-lexicon.md §5
        for m in lx.match_term(idx, term):
            for w in where.get(m["label"], []):
                hits.append({**w, "score": m["score"], "via": f"lexicon:{m['via']}"})
        nar = []
        for n in lx.narrower_of(idx, term):
            for w in where.get(n["label"], []):
                nar.append({**w, "reviewed": n["reviewed"]})
        narrower[term] = nar[: limit * 3]
        for k in kinds:
            if kind and k["name"] != kind:
                continue
            for p in catalogs.get(k["name"], []):
                if p.get("equiv_rep") and p["equiv_rep"] != p["key"]:
                    continue
                for v in p.get("values") or []:
                    label = v.get("label") or ""
                    s = _score(term, label)
                    base = {"kind": k["name"], "path": p["key"], "value": label, "members": v.get("members", 0)}
                    if s >= 60:
                        hits.append({**base, "score": round(s, 1),
                                     "via": "exact" if s >= 100 else "linking"})
                    elif _contains(term, label):
                        rel.append({**base, "via": "contains"})
                    # 값 동치(스키마 정렬의 value 규칙·동치 묶음)도 일치로 본다
                    for e in ((p.get("value_equiv") or {}).get(v.get("uri")) or []):
                        if _score(term, e.get("label", "")) >= 100:
                            hits.append({**base, "score": 95.0, "via": f"equiv:{e['label']}"})
        # 사전·링킹으로 못 찾았고 영어 표기가 오면 → 번역 대체 단계
        en = (terms_en or {}).get(term)
        if en and not any(h["score"] >= lx.SCORE_STRIPPED for h in hits):
            tr = await lx.match_translated(kb_id, idx, en)
            for m in tr["matches"]:
                for w in where.get(m["label"], []):
                    hits.append({**w, "score": m["score"], "via": m["via"], "similarity": m.get("similarity")})
            sug = []
            for c in tr["candidates"]:
                for w in where.get(c["label"], []):
                    sug.append({**w, "similarity": c["similarity"], "via": c["via"]})
            if sug:
                suggestions[term] = _dedupe(sug)[:limit]
        hits.sort(key=lambda h: (-h["score"], -h["members"]))
        rel.sort(key=lambda h: -h["members"])
        matches[term] = _dedupe(hits)[:limit]
        related[term] = _dedupe(rel)[:limit]
    return {"schema_version": version, "matches": matches, "related": related, "narrower": narrower,
            "suggestions": suggestions,
            "lexicon_entries": idx["entries"],
            "note": "matches 가 비면 그래프에 그 값이 없다는 뜻. narrower 는 상위 개념을 하위 값으로 푼 후보 "
                    "(reviewed=false 는 사람 검토 전) — 푼 방식을 답변에 밝힐 것. via=translated:* 는 영어 표기 유사도로 찾은 것 "
                    "(오탈자·처음 보는 표기). suggestions 는 확정 못 한 후보 — 질문 맥락으로 골라 쓸 것."}


async def _prefetch_fallback(kb_id: str, idx: Dict[str, Any], terms: Sequence[str],
                             terms_en: Optional[Dict[str, str]]) -> None:
    """사전에 없을 것 같은 말의 영어 표기를 한 번에 임베딩 (용어별 호출 대신 1회)."""
    from app.services.agent_query import lexicon as lx
    if not terms_en:
        return
    need = [terms_en[t] for t in terms if terms_en.get(t)
            and not any(m["score"] >= lx.SCORE_STRIPPED for m in lx.match_term(idx, t))
            and not any(m["score"] >= lx.SCORE_STRIPPED for m in lx.match_term(idx, terms_en[t]))]
    if need:
        await lx.prefetch_query_vectors(kb_id, need)


def _compact_name(t: str) -> str:
    from app.services.agent_query.lexicon import _compact
    return _compact(t)


def _dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for r in rows:
        key = (r["kind"], r["path"], r["value"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# resolve_entities (§4.3) — 이름 → 유형 멤버
# ---------------------------------------------------------------------------

def _labels_query(uris: Sequence[str]) -> str:
    vals = " ".join(f"<{u}>" for u in uris)
    return f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?e ?l ?alt FROM <urn:x-arq:UnionGraph> WHERE {{
  VALUES ?e {{ {vals} }}
  OPTIONAL {{ ?e rdfs:label ?l }}
  OPTIONAL {{ ?e skos:altLabel ?alt }}
}}"""


async def resolve_entities(kb_id: str, names: Sequence[str], kind: Optional[str] = None,
                           limit: int = 5, names_en: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    _kb_, kinds, _cat, version = await load_catalog(kb_id)
    fb = FusekiBackend()
    # 유형 멤버의 라벨·별칭
    members: List[Tuple[str, str, str]] = []   # (kind, uri)
    by_uri: Dict[str, Dict[str, Any]] = {}
    for k in kinds:
        if kind and k["name"] != kind:
            continue
        uris = list(k["members"])
        for i in range(0, len(uris), 200):
            rows = await asyncio.to_thread(fb._bindings, kb_id, _labels_query(uris[i:i + 200]))
            for r in rows:
                u = r["e"]["value"]
                ent = by_uri.setdefault(u, {"kind": k["name"], "labels": set(), "aliases": set()})
                if r.get("l"):
                    ent["labels"].add(r["l"]["value"])
                if r.get("alt"):
                    ent["aliases"].add(r["alt"]["value"])
    from app.services.agent_query import lexicon as lx
    idx = await lx.get_index(kb_id)
    label_to_uri: Dict[str, str] = {}
    for u, ent in by_uri.items():
        for l in ent["labels"]:
            label_to_uri[l] = u
    out: Dict[str, List[Dict[str, Any]]] = {}
    suggestions: Dict[str, List[Dict[str, Any]]] = {}
    await _prefetch_fallback(kb_id, idx, names, names_en)
    for name in [n.strip() for n in (names or []) if n and n.strip()][:20]:
        cands = []
        for m in lx.match_term(idx, name):
            u = label_to_uri.get(m["label"])
            if u:
                ent = by_uri[u]
                cands.append({"label": m["label"], "kind": ent["kind"], "score": m["score"], "uri": u,
                              "via": f"lexicon:{m['via']}", "aliases": sorted(ent["aliases"])[:5]})
        for u, ent in by_uri.items():
            label = sorted(ent["labels"])[0] if ent["labels"] else u.rsplit("/", 1)[-1].replace("_", " ")
            best, via = 0.0, ""
            for l in ent["labels"] or {label}:
                s = _score(name, l)
                if s > best:
                    best, via = s, "label"
            for a in ent["aliases"]:
                s = _score(name, a)
                if s > best:
                    best, via = s, "alias"
            if best >= 60:
                cands.append({"label": label, "kind": ent["kind"], "score": round(best, 1), "via": via, "uri": u,
                              "aliases": sorted(ent["aliases"])[:5]})
        en = (names_en or {}).get(name)
        if en and not any(c["score"] >= lx.SCORE_STRIPPED for c in cands):
            tr = await lx.match_translated(kb_id, idx, en)
            for m in tr["matches"]:
                u = label_to_uri.get(m["label"])
                if u:
                    cands.append({"label": m["label"], "kind": by_uri[u]["kind"], "score": m["score"], "uri": u,
                                  "via": m["via"], "similarity": m.get("similarity"),
                                  "aliases": sorted(by_uri[u]["aliases"])[:5]})
            sug = [{"label": c["label"], "kind": by_uri[label_to_uri[c["label"]]]["kind"],
                    "similarity": c["similarity"], "via": c["via"]}
                   for c in tr["candidates"] if c["label"] in label_to_uri]
            if sug:
                suggestions[name] = sug
        if not any(c["score"] >= 60 for c in cands):
            # 부분 이름: 그래프 라벨이 질문 이름 안에 들어 있음 ('아델하이트 피르나우' ⊃ '피르나우', 'Enrico Fermi' ⊃ 'Fermi')
            # 질문 이름의 어절(토큰) 단위로만 — '보어' 가 '하랄 보어스' 같은 부분 문자열에 걸리지 않게
            name_tokens = {_compact_name(t) for t in re.split(r"[\s·.\-_]+", name) if t}
            name_tokens.discard("")
            for u, ent in by_uri.items():
                forms = set(ent["labels"]) | set(ent["aliases"])
                for f in forms:
                    ft = [_compact_name(t) for t in re.split(r"[\s·.\-_]+", f) if t]
                    ft = [t for t in ft if t]
                    if ft and len("".join(ft)) >= 2 and set(ft) <= name_tokens and len(ft) < len(name_tokens):
                        label = sorted(ent["labels"])[0] if ent["labels"] else f
                        cands.append({"label": label, "kind": ent["kind"], "score": 75.0, "uri": u,
                                      "via": f"partial:{f}", "aliases": sorted(ent["aliases"])[:5]})
                        break
        best: Dict[str, Dict[str, Any]] = {}
        for c in cands:
            if c["label"] not in best or c["score"] > best[c["label"]]["score"]:
                best[c["label"]] = c
        out[name] = sorted(best.values(), key=lambda c: -c["score"])[:limit]
    return {"schema_version": version, "entities": out, "suggestions": suggestions,
            "note": "비어 있으면 그 이름의 엔티티가 그래프에 없다. 영문·한글 표기를 바꿔 다시 시도하거나 search 를 쓴다."}


# ---------------------------------------------------------------------------
# get_chunks (§4.6)
# ---------------------------------------------------------------------------

_CHUNK_ID_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,200}$")


MAX_DOC_CHUNKS = 12


async def get_chunks(kb_id: str, chunk_ids: Sequence[str], max_chars: int = 1500,
                     expand_doc: bool = False) -> Dict[str, Any]:
    """expand_doc=True: 요청한 청크와 같은 문서의 다른 청크도 함께 (문서당 최대 12개).
    평가 14: 연도('1887년 7월', '1868년')가 근거 청크가 아닌 같은 문서의 다른 청크에 있어 놓친 문제."""
    await _kb(kb_id)
    ids = [c for c in dict.fromkeys(chunk_ids or []) if isinstance(c, str) and _CHUNK_ID_RE.match(c)][:MAX_CHUNKS]
    if not ids:
        return {"chunks": [], "missing": list(chunk_ids or [])}
    max_chars = max(100, min(int(max_chars or 1500), 8000))

    def _query():
        from app.core.milvus import create_collection
        col = create_collection(kb_id)
        col.load()
        expr = "chunk_id in [" + ", ".join(f'"{c}"' for c in ids) + "]"
        # pymilvus 결과는 지연 객체라 일반 리스트로 바꾼다 (반복 후 append 하면 IndexError)
        return [dict(r) for r in col.query(expr=expr, output_fields=["chunk_id", "content", "metadata", "doc_id"],
                                           limit=len(ids))]

    try:
        rows = await asyncio.wait_for(asyncio.to_thread(_query), timeout=15)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="청크 조회 시간 초과 (Milvus)")
    extra_ids: List[str] = []
    if expand_doc and rows:
        docs = list({r.get("doc_id") for r in rows if r.get("doc_id")})

        def _same_doc():
            from app.core.milvus import create_collection
            col = create_collection(kb_id)
            expr = "doc_id in [" + ", ".join(f'"{d}"' for d in docs) + "]"
            return [dict(r) for r in col.query(expr=expr, output_fields=["chunk_id", "content", "metadata", "doc_id"],
                                               limit=MAX_DOC_CHUNKS * len(docs))]
        try:
            more = await asyncio.wait_for(asyncio.to_thread(_same_doc), timeout=15)
        except asyncio.TimeoutError:
            more = []
        have = {r["chunk_id"] for r in rows}
        per_doc: Dict[str, int] = {}
        for r in more:
            if r["chunk_id"] in have:
                continue
            d = r.get("doc_id")
            if per_doc.get(d, 0) >= MAX_DOC_CHUNKS:
                continue
            per_doc[d] = per_doc.get(d, 0) + 1
            rows.append(r)
            extra_ids.append(r["chunk_id"])
    # 문서명: Milvus 메타데이터가 비어 있는 경우가 많아 doc_id → Document.filename
    doc_names: Dict[str, str] = {}
    doc_ids = list({r.get("doc_id") for r in rows if r.get("doc_id")})
    if doc_ids:
        from app.models.document import Document
        try:
            for d in await Document.find({"_id": {"$in": doc_ids}}).to_list():
                doc_names[str(d.id)] = d.filename
        except Exception:
            pass
    found = {}
    for r in rows:
        meta = r.get("metadata") or {}
        text = r.get("content") or ""
        found[r["chunk_id"]] = {
            "id": r["chunk_id"],
            "doc": doc_names.get(str(r.get("doc_id"))) or meta.get("filename") or meta.get("source") or r.get("doc_id"),
            "section": meta.get("section") or meta.get("header") or meta.get("heading"),
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        }
    out = {"chunks": [found[c] for c in ids if c in found], "missing": [c for c in ids if c not in found]}
    if extra_ids:
        out["same_doc_chunks"] = [found[c] for c in extra_ids if c in found]
    return out


# ---------------------------------------------------------------------------
# describe_entity — 엔티티 하나의 모든 관계 (나가는·들어오는, 구조 노드 한 단계 펼침)
# 평가 13(2026-11-16)에서 "엔티티 하나를 지정해 조회할 수단이 없다"는 보고로 추가.
# ---------------------------------------------------------------------------

MAX_ENTITY_ROWS = 400


def _entity_queries(uri: str) -> Dict[str, str]:
    from app.services.retrieval import class_query as cq
    from app.services.retrieval.relation_targeting import STMT_PREFIX, STRUCT_NODE_REGEX
    pre = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX meta: <http://rag.local/meta/>"""
    chunk = "OPTIONAL { ?st rdf:subject ?s0 ; rdf:predicate ?p ; rdf:object ?o0 ; meta:sourceNodeId ?chunk . }"
    return {
        "out": f"""{pre}
SELECT ?p ?o ?oLabel ?chunk FROM <urn:x-arq:UnionGraph> WHERE {{
  BIND(<{uri}> AS ?s0) <{uri}> ?p ?o . BIND(?o AS ?o0)
  FILTER(?p NOT IN ({cq._EXCL})) FILTER(!STRSTARTS(STR(?o), "{STMT_PREFIX}"))
  OPTIONAL {{ ?o rdfs:label ?oLabel }} {chunk}
}} LIMIT {MAX_ENTITY_ROWS}""",
        "struct": f"""{pre}
SELECT ?p1 ?p ?o ?oLabel ?chunk FROM <urn:x-arq:UnionGraph> WHERE {{
  <{uri}> ?p1 ?s0 . FILTER(REGEX(STR(?s0), "{STRUCT_NODE_REGEX}"))
  ?s0 ?p ?o . BIND(?o AS ?o0) FILTER(?p NOT IN ({cq._EXCL})) FILTER(!STRSTARTS(STR(?o), "{STMT_PREFIX}"))
  OPTIONAL {{ ?o rdfs:label ?oLabel }} {chunk}
}} LIMIT {MAX_ENTITY_ROWS}""",
        "in": f"""{pre}
SELECT ?s ?p ?sLabel ?chunk FROM <urn:x-arq:UnionGraph> WHERE {{
  ?s ?p <{uri}> . BIND(?s AS ?s0) BIND(<{uri}> AS ?o0)
  FILTER(?p NOT IN ({cq._EXCL})) FILTER(!STRSTARTS(STR(?s), "{STMT_PREFIX}"))
  FILTER(!REGEX(STR(?s), "{STRUCT_NODE_REGEX}"))
  OPTIONAL {{ ?s rdfs:label ?sLabel }} {chunk}
}} LIMIT {MAX_ENTITY_ROWS}""",
    }


async def describe_entity(kb_id: str, name: str, name_en: Optional[str] = None,
                          kind: Optional[str] = None) -> Dict[str, Any]:
    """이름 → 엔티티 확정(resolve_entities 와 같은 규칙) → 그 엔티티의 관계 전부 + 근거 청크 ID."""
    from app.services.retrieval import class_query as cq
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    res = await resolve_entities(kb_id, [name], kind, 5, {name: name_en} if name_en else None)
    cands = (res["entities"].get(name.strip()) or [])
    if not cands:
        return {"status": "zero", "schema_version": res["schema_version"], "message": f"'{name}' 엔티티를 찾지 못함",
                "suggestions": res.get("suggestions", {}).get(name.strip(), [])}
    top = cands[0]
    uri = top["uri"]
    fb = FusekiBackend()
    qs = _entity_queries(uri)
    rows = {k: await asyncio.to_thread(fb._bindings, kb_id, q) for k, q in qs.items()}
    lab = lambda b, v, l: cq._val(b, l) or (cq.local_name(cq._val(b, v)).replace("_", " ")
                                            if (cq._val(b, v) or "").startswith("http") else cq._val(b, v))

    def group(items):
        out: Dict[Tuple[str, str], List[str]] = {}
        for k, c in items:
            lst = out.setdefault(k, [])
            if c and c not in lst:
                lst.append(c)
        return out

    out_g = group(((cq.local_name(cq._val(b, "p")), lab(b, "o", "oLabel")), cq._val(b, "chunk")) for b in rows["out"]
                  if not re.search(r"/inst/root_[0-9]+_", cq._val(b, "o") or ""))
    st_g = group(((f"{cq.local_name(cq._val(b, 'p1'))}.{cq.local_name(cq._val(b, 'p'))}", lab(b, "o", "oLabel")),
                  cq._val(b, "chunk")) for b in rows["struct"])
    in_g = group(((cq.local_name(cq._val(b, "p")), lab(b, "s", "sLabel")), cq._val(b, "chunk")) for b in rows["in"])
    return {
        "status": "ok",
        "schema_version": res["schema_version"],
        "entity": {"label": top["label"], "kind": top["kind"], "via": top["via"], "aliases": top.get("aliases", [])},
        "other_candidates": [{"label": c["label"], "kind": c["kind"]} for c in cands[1:]],
        "out": [{"p": p, "o": o, "chunk_ids": cs} for (p, o), cs in sorted({**out_g, **st_g}.items())],
        "in": [{"s": s, "p": p, "chunk_ids": cs} for (p, s), cs in sorted(in_g.items())],
        "note": "out = (엔티티, p, o), in = (s, p, 엔티티). 추출 오류로 방향이 뒤집힌 관계가 있을 수 있다 — "
                "방향이 답을 좌우하면 chunk_ids 원문으로 확인할 것.",
    }
