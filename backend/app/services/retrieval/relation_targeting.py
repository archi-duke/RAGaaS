"""관계 타게팅 그래프 검색 — 순수 함수 모음.

설계: docs/design-graph-relation-targeting.md

그래프 검색은 "엔티티 주변을 통째로 가져오기"가 아니라 다음 순서로 동작해야 한다.
  1. 앵커 엔티티의 관계 경로 카탈로그를 만든다 (구조 노드 root_N_… 를 따라 깊이 3).
  2. 질문의 관계어(별칭)를 카탈로그 경로와 결정적으로 매칭한다 (A).
     매칭이 없으면 LLM 이 카탈로그 안에서 경로를 고른다 (B, 닫힌 집합).
  3. 선택한 경로만 조회하는 SPARQL 을 실행하고, 각 트리플의 s-p-o 와 정확히
     일치하는 reification statement 로 근거 청크를 조인한다.
  4. 청크는 트리플 연결 순으로 정렬한다 (임베딩 유사도 아님).
  5. 이 과정을 Execution Log 용 추론 리포트로 남긴다.

이 모듈은 Fuseki 호출 없이 SPARQL 문자열 생성 / 바인딩 해석 / 매칭만 담당하므로
단위 테스트가 가능하고 다른 그래프 백엔드(Neo4j)에서도 재사용할 수 있다.
"""

import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.retrieval.entity_linking import _compact, normalize_text, tokens

INST_PREFIX = "http://rag.local/inst/"
STMT_PREFIX = "http://rag.local/stmt/"
STRUCT_NODE_REGEX = "/inst/root_[0-9]+_"
_STRUCT_NODE_RE = re.compile(r"/inst/root_[0-9]+_")

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

MAX_SELECTED_PATHS = 12      # 한 질문에서 조회할 경로 상한
MAX_TARGETED_TRIPLES = 300   # 타게팅 SPARQL LIMIT
OVERVIEW_LIMIT = 40          # 개요 질문 이웃 상한
MAX_CATALOG_FOR_LLM = 80     # B 단계 프롬프트에 싣는 카탈로그 상한

# 서사형 그래프의 역관계 (graph_postprocessor 기본 매핑과 동일).
DEFAULT_INVERSE_MAP: Dict[str, str] = {
    "스승": "제자", "제자": "스승", "부모": "자식", "자식": "부모",
    "선배": "후배", "후배": "선배", "형": "동생", "동생": "형",
    "남편": "아내", "아내": "남편",
}

_PREFIXES = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX meta: <http://rag.local/meta/>"""

_EXCLUDED_PREDICATES = (
    "rdf:type", "rdfs:label", "rdf:subject", "rdf:predicate", "rdf:object",
)


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

def local_name(uri: str) -> str:
    """URI 의 마지막 세그먼트 (URL 디코드)."""
    if not uri:
        return ""
    tail = uri.rsplit("#", 1)[-1] if "#" in uri.rsplit("/", 1)[-1] else uri.rsplit("/", 1)[-1]
    return urllib.parse.unquote(tail)


def is_struct_node(uri: str) -> bool:
    """구조화(JSON/YAML) 문서의 익명 구조 노드(inst:root_N_…)인가."""
    return bool(uri) and bool(_STRUCT_NODE_RE.search(uri))


def _iri(uri: str) -> str:
    return f"<{uri}>"


def _anchor_term(anchor, var: str = "?anchor") -> Tuple[str, str]:
    """앵커 1개면 (<uri>, ""), 동일 엔티티 묶음(여러 URI)이면 (?anchor, "VALUES ?anchor {…} ").

    VALUES 는 UNION 각 분기 안 맨 앞에 넣는다 — 분기 안의 BIND(?anchor AS ?s) 가 바인딩을 보도록.
    """
    uris = [anchor] if isinstance(anchor, str) else list(dict.fromkeys(anchor))
    if len(uris) == 1:
        return _iri(uris[0]), ""
    return var, f"VALUES {var} {{ {' '.join(_iri(u) for u in uris)} }} "


def _val(b: Dict[str, Any], key: str) -> Optional[str]:
    v = b.get(key)
    return v.get("value") if isinstance(v, dict) else None


def path_key(direction: str, segments: Sequence[str]) -> str:
    """경로 표기: 'out|tradeoffs.pros', 'in|related_patterns'."""
    return f"{direction}|{'.'.join(segments)}"


def path_label(path: Dict[str, Any]) -> str:
    """사람이 읽는 경로 표기 (incoming 은 '←' 접두)."""
    name = ".".join(path["segments"])
    return f"← {name}" if path["dir"] == "in" else name


def parse_json_loose(text: str) -> Optional[Dict[str, Any]]:
    """LLM 응답에서 JSON 객체 추출 (코드펜스·앞뒤 설명문 허용)."""
    if not text:
        return None
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            v = json.loads(t[start:end + 1])
            return v if isinstance(v, dict) else None
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# 1. 관계 경로 카탈로그
# ---------------------------------------------------------------------------

def build_catalog_query(anchor_uri) -> str:
    """앵커의 관계 경로 카탈로그 SPARQL.

    out: depth1(값 노드) / depth2·3(구조 노드 경유), in: depth1.
    결과: ?dir ?p0 ?p1 ?p2 ?n ?ex
    """
    a, v = _anchor_term(anchor_uri)
    excluded = ", ".join(_EXCLUDED_PREDICATES)
    return f"""{_PREFIXES}
SELECT ?dir ?p0 ?p1 ?p2 (COUNT(*) AS ?n) (SAMPLE(?o) AS ?ex)
FROM <urn:x-arq:UnionGraph>
WHERE {{
  {{
    {v}BIND("out" AS ?dir)
    {a} ?p0 ?o .
    FILTER(!REGEX(STR(?o), "{STRUCT_NODE_REGEX}"))
  }}
  UNION
  {{
    {v}BIND("out" AS ?dir)
    {a} ?p0 ?m .
    FILTER(REGEX(STR(?m), "{STRUCT_NODE_REGEX}"))
    ?m ?p1 ?o .
    FILTER(!REGEX(STR(?o), "{STRUCT_NODE_REGEX}"))
    FILTER(?p1 NOT IN ({excluded}))
  }}
  UNION
  {{
    {v}BIND("out" AS ?dir)
    {a} ?p0 ?m .
    FILTER(REGEX(STR(?m), "{STRUCT_NODE_REGEX}"))
    ?m ?p1 ?m2 .
    FILTER(REGEX(STR(?m2), "{STRUCT_NODE_REGEX}"))
    ?m2 ?p2 ?o .
    FILTER(?p2 NOT IN ({excluded}))
  }}
  UNION
  {{
    {v}BIND("in" AS ?dir)
    ?o ?p0 {a} .
    FILTER(!STRSTARTS(STR(?o), "{STMT_PREFIX}"))
  }}
  FILTER(?p0 NOT IN ({excluded}))
}}
GROUP BY ?dir ?p0 ?p1 ?p2
LIMIT 500"""


def parse_catalog(bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """카탈로그 바인딩 → 경로 목록.

    경로: {"dir", "segments": [로컬네임…], "uris": [predicate URI…], "count", "example", "key"}
    """
    paths: List[Dict[str, Any]] = []
    seen = set()
    for b in bindings:
        direction = _val(b, "dir") or "out"
        uris = [u for u in (_val(b, "p0"), _val(b, "p1"), _val(b, "p2")) if u]
        if not uris:
            continue
        segments = [local_name(u) for u in uris]
        key = path_key(direction, segments)
        if key in seen:
            continue
        seen.add(key)
        try:
            count = int(_val(b, "n") or 0)
        except ValueError:
            count = 0
        example = _val(b, "ex") or ""
        if example.startswith("http"):
            example = local_name(example)
        paths.append({
            "dir": direction, "segments": segments, "uris": uris,
            "count": count, "example": example[:60], "key": key,
        })
    # 안정 정렬: out 먼저, 얕은 경로 먼저, 이름순
    paths.sort(key=lambda p: (p["dir"] != "out", len(p["segments"]), ".".join(p["segments"])))
    return paths


# ---------------------------------------------------------------------------
# 2. 관계어(별칭) 풀과 결정적 매칭 (A)
# ---------------------------------------------------------------------------

def build_alias_pool(
    relation_aliases: Optional[Sequence[str]],
    relationship_type: Optional[str] = None,
    unresolved_entities: Optional[Sequence[str]] = None,
    query_text: str = "",
) -> List[str]:
    """관계어 후보 풀. 질문에 글자 그대로 등장한 별칭을 맨 앞에 둔다.

    순서 = 우선순위: (질문에 등장한 별칭) → 분석기 별칭 순서 → relationship_type
    → 링킹에 실패한 LLM 엔티티(속성어가 엔티티로 잘못 분류된 경우 구제).
    """
    raw: List[str] = []
    for a in relation_aliases or []:
        if isinstance(a, str) and a.strip():
            raw.append(a.strip())
    if isinstance(relationship_type, str) and relationship_type.strip():
        raw.append(relationship_type.strip())
    for e in unresolved_entities or []:
        if isinstance(e, str) and e.strip():
            raw.append(e.strip())

    pool: List[str] = []
    seen = set()
    for a in raw:
        c = _compact(a)
        if not c or c in seen:
            continue
        seen.add(c)
        pool.append(a)

    q_norm = f" {normalize_text(query_text)} "
    q_compact = _compact(query_text)

    def in_query(alias: str) -> bool:
        n = normalize_text(alias)
        if not n:
            return False
        if n.isascii():
            return f" {n} " in q_norm or (len(n) > 3 and f" {n}s " in q_norm)
        return _compact(alias) in q_compact

    literal = [a for a in pool if in_query(a)]
    rest = [a for a in pool if a not in literal]
    return literal + rest


def _prefix_aligned(a_tokens: List[str], s_tokens: List[str]) -> bool:
    """토큰 수가 같고 토큰마다 공통 접두 4자 이상 (testing↔test, complexity↔complexity)."""
    if len(a_tokens) != len(s_tokens) or not a_tokens:
        return False
    remaining = list(s_tokens)
    for at in a_tokens:
        hit = None
        for st in remaining:
            n = 0
            for x, y in zip(at, st):
                if x != y:
                    break
                n += 1
            if at == st or n >= 4:
                hit = st
                break
        if hit is None:
            return False
        remaining.remove(hit)
    return True


def match_tier(alias: str, segment: str) -> int:
    """별칭과 경로 세그먼트의 매칭 등급 (1 최강 ~ 3, 0 불일치).

    1: compact 완전일치        pros = pros, 스승 = 스승, prerequisites = prerequisites
    2: 토큰 접두 정렬 일치      test complexity ≈ testing_complexity
    3: 별칭 토큰 ⊆ 세그먼트 토큰  avoid ⊂ avoid_signals  (영문 3자 이상)
       한글은 부분 포함 (2자 이상)
    토큰 내부 부분 문자열('of' ⊂ 'tradeoffs')은 매칭하지 않는다.
    """
    a_c, s_c = _compact(alias), _compact(segment)
    if not a_c or not s_c:
        return 0
    if a_c == s_c:
        return 1
    a_t, s_t = tokens(alias), tokens(segment)
    if a_c.isascii() and s_c.isascii():
        if _prefix_aligned(a_t, s_t):
            return 2
        if a_t and all(len(t) >= 3 for t in a_t) and set(a_t) <= set(s_t):
            return 3
        return 0
    if not a_c.isascii() and len(a_c) >= 2 and a_c in s_c:
        return 3
    return 0


def match_paths(
    catalog: List[Dict[str, Any]],
    aliases: Sequence[str],
    role: Optional[str] = None,
    inverse_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """별칭 → 카탈로그 경로 선택 (결정적).

    규칙:
      - 별칭을 우선순위 순으로 보며, 등급 1~2 매칭이 있는 첫 별칭을 채택한다.
        (예: 'pros'(1순위)와 'strengths'가 모두 일치해도 'pros' 만 채택 —
         동의어가 엉뚱한 키 quality_attributes.strength 를 끌고 오는 것 방지)
      - 등급 1~2가 하나도 없으면 같은 방식으로 등급 3을 본다.
      - 중간 세그먼트에 매칭되면 그 접두 아래 경로 전체, 리프면 그 경로만.
      - 역관계 별칭(스승→제자)은 역할 반대 방향 경로에만 적용한다.

    반환: (선택 경로 목록, 매칭 설명 목록)
    """
    inverse_map = DEFAULT_INVERSE_MAP if inverse_map is None else inverse_map
    role_dir = "in" if role == "object" else "out"
    opposite = "out" if role_dir == "in" else "in"

    def hits_for(alias: str, allowed_dirs: Tuple[str, ...]) -> List[Tuple[int, Dict[str, Any], int]]:
        out = []
        for p in catalog:
            if p["dir"] not in allowed_dirs:
                continue
            best = None
            for i, seg in enumerate(p["segments"]):
                t = match_tier(alias, seg)
                if t and (best is None or t < best[0] or (t == best[0] and i > best[1])):
                    best = (t, i)
            if best:
                out.append((best[0], p, best[1]))
        return out

    chosen: List[Tuple[str, int, Dict[str, Any], int, bool]] = []  # (alias, tier, path, seg_idx, inverse)
    for max_tier in (2, 3):
        for alias in aliases:
            direct = [h for h in hits_for(alias, ("out", "in")) if h[0] <= max_tier]
            inv_alias = inverse_map.get(normalize_text(alias)) or inverse_map.get(alias)
            inverse = []
            if inv_alias:
                inverse = [h for h in hits_for(inv_alias, (opposite,)) if h[0] <= max_tier]
            if direct or inverse:
                top = min(h[0] for h in direct + inverse)
                for t, p, i in direct:
                    if t == top:
                        chosen.append((alias, t, p, i, False))
                for t, p, i in inverse:
                    if t == top:
                        chosen.append((inv_alias, t, p, i, True))
                break
        if chosen:
            break

    selected: List[Dict[str, Any]] = []
    selected_keys = set()
    matches: List[Dict[str, Any]] = []
    for alias, tier, p, seg_idx, inv in chosen:
        prefix = p["segments"][: seg_idx + 1]
        matches.append({
            "alias": alias, "tier": tier, "inverse": inv,
            "matched": path_label({"dir": p["dir"], "segments": prefix}),
            "expanded": seg_idx < len(p["segments"]) - 1,
        })
        for q in catalog:
            if q["dir"] == p["dir"] and q["segments"][: len(prefix)] == prefix and q["key"] not in selected_keys:
                selected_keys.add(q["key"])
                selected.append(q)

    # 매칭 설명 중복 제거
    uniq, seen = [], set()
    for m in matches:
        k = (m["alias"], m["matched"])
        if k not in seen:
            seen.add(k)
            uniq.append(m)

    # 역할에 맞는 방향 먼저
    selected.sort(key=lambda q: q["dir"] != role_dir)
    return selected[:MAX_SELECTED_PATHS], uniq


# ---------------------------------------------------------------------------
# 3. B 단계: 닫힌 집합 LLM 경로 선택 (프롬프트 + 검증)
# ---------------------------------------------------------------------------

def build_path_select_messages(query_text: str, catalog: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    items = sorted(catalog, key=lambda p: -p["count"])[:MAX_CATALOG_FOR_LLM]
    lines = []
    for i, p in enumerate(items):
        ex = f", 예: {p['example']}" if p.get("example") else ""
        lines.append(f"{i}. [{p['dir']}] {'.'.join(p['segments'])} ({p['count']}건{ex})")
    catalog_text = "\n".join(lines)
    user = f"""질문: {query_text}

아래는 질문의 대상 엔티티에서 나가는(out) / 들어오는(in) 관계 경로 목록이다.
질문이 묻는 관계/속성에 해당하는 경로 번호만 골라라.

{catalog_text}

규칙:
- 질문이 특정 관계/속성을 묻으면 mode="targeted" 와 해당 경로 번호들(최대 6개).
- 질문이 엔티티 전반을 묻는 개요 질문("~에 대해 알려줘", "~란?")이면 mode="overview", paths=[].
- 목록에 질문이 묻는 관계가 없으면 mode="none", paths=[]. 억지로 고르지 마라.
JSON 만 출력: {{"mode": "targeted|overview|none", "paths": [번호...], "reason": "한 줄 근거"}}"""
    return [
        {"role": "system", "content": "You select knowledge-graph relation paths from a closed list. Output JSON only."},
        {"role": "user", "content": user},
    ], items


def validate_llm_selection(
    data: Optional[Dict[str, Any]], items: List[Dict[str, Any]]
) -> Tuple[str, List[Dict[str, Any]], str]:
    """B 응답 검증: 목록에 실재하는 번호만 채택. (mode, 경로들, 근거)"""
    if not data:
        return "none", [], "LLM 응답 해석 불가"
    mode = str(data.get("mode") or "none").lower()
    reason = str(data.get("reason") or "")[:200]
    if mode not in ("targeted", "overview", "none"):
        mode = "none"
    picked: List[Dict[str, Any]] = []
    if mode == "targeted":
        for idx in data.get("paths") or []:
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(items) and items[i] not in picked:
                picked.append(items[i])
        if not picked:
            mode = "none"
    return mode, picked[:6], reason


# ---------------------------------------------------------------------------
# 4. 타게팅 / 개요 / 두 엔티티 SPARQL
# ---------------------------------------------------------------------------

_TAIL = """  OPTIONAL { ?s rdfs:label ?sLabel }
  OPTIONAL { ?o rdfs:label ?oLabel }
  OPTIONAL {
    ?st rdf:subject ?s ; rdf:predicate ?p ; rdf:object ?o ;
        meta:sourceNodeId ?chunk .
  }"""


def build_targeted_query(anchor_uri, paths: List[Dict[str, Any]]) -> str:
    """선택 경로만 조회 + 리프 트리플의 s-p-o 정확 일치 statement 로 청크 조인.

    anchor_uri 는 URI 하나 또는 동일 엔티티 묶음(URI 목록).
    """
    a, v = _anchor_term(anchor_uri)
    branches = []
    for p in paths:
        u = p["uris"]
        key = p["key"].replace('"', "")
        if p["dir"] == "in":
            body = f"BIND({a} AS ?o) BIND(<{u[0]}> AS ?p) ?s ?p ?o ."
        elif len(u) == 1:
            body = f"BIND({a} AS ?s) BIND(<{u[0]}> AS ?p) ?s ?p ?o ."
        elif len(u) == 2:
            body = (f"{a} <{u[0]}> ?s . FILTER(REGEX(STR(?s), \"{STRUCT_NODE_REGEX}\")) "
                    f"BIND(?s AS ?mid) BIND(<{u[1]}> AS ?p) ?s ?p ?o .")
        else:
            body = (f"{a} <{u[0]}> ?mid . FILTER(REGEX(STR(?mid), \"{STRUCT_NODE_REGEX}\")) "
                    f"?mid <{u[1]}> ?s . FILTER(REGEX(STR(?s), \"{STRUCT_NODE_REGEX}\")) "
                    f"BIND(<{u[2]}> AS ?p) ?s ?p ?o .")
        if len(u) >= 2:
            # 구조 경로 간선(앵커 → 첫 구조 노드)의 근거 청크 — 깊은 분기 안에서만 조인
            body += (f" OPTIONAL {{ ?est rdf:subject {a} ; rdf:predicate <{u[0]}> ; "
                     f"rdf:object ?mid ; meta:sourceNodeId ?edgeChunk . }}")
        branches.append(f"  {{ {v}{body} BIND(\"{key}\" AS ?path) }}")
    union = "\n  UNION\n".join(branches)
    return f"""{_PREFIXES}
SELECT DISTINCT ?path ?s ?p ?o ?sLabel ?oLabel ?chunk ?edgeChunk
FROM <urn:x-arq:UnionGraph>
WHERE {{
{union}
{_TAIL}
}}
LIMIT {MAX_TARGETED_TRIPLES}"""


def build_overview_query(anchor_uri) -> str:
    """개요 질문: 앵커의 depth-1 이웃 (구조 노드로 가는 간선 제외)."""
    a, v = _anchor_term(anchor_uri)
    excluded = ", ".join(_EXCLUDED_PREDICATES)
    return f"""{_PREFIXES}
SELECT DISTINCT ?path ?s ?p ?o ?sLabel ?oLabel ?chunk
FROM <urn:x-arq:UnionGraph>
WHERE {{
  {{ {v}BIND({a} AS ?s) ?s ?p ?o . FILTER(!REGEX(STR(?o), "{STRUCT_NODE_REGEX}")) BIND("overview" AS ?path) }}
  UNION
  {{ {v}BIND({a} AS ?o) ?s ?p ?o . FILTER(!STRSTARTS(STR(?s), "{STMT_PREFIX}")) BIND("overview-in" AS ?path) }}
  FILTER(?p NOT IN ({excluded}))
{_TAIL}
}}
LIMIT {OVERVIEW_LIMIT * 3}"""


def build_pair_query(uri1, uri2) -> str:
    """두 엔티티 사이의 직접 관계 (양방향, URI 고정). 각 쪽은 URI 하나 또는 동일 엔티티 묶음."""
    a, va = _anchor_term(uri1, "?anchorA")
    b, vb = _anchor_term(uri2, "?anchorB")
    excluded = ", ".join(_EXCLUDED_PREDICATES)
    return f"""{_PREFIXES}
SELECT DISTINCT ?path ?s ?p ?o ?sLabel ?oLabel ?chunk
FROM <urn:x-arq:UnionGraph>
WHERE {{
  {{ {va}{vb}BIND({a} AS ?s) BIND({b} AS ?o) ?s ?p ?o . BIND("pair" AS ?path) }}
  UNION
  {{ {va}{vb}BIND({b} AS ?s) BIND({a} AS ?o) ?s ?p ?o . BIND("pair" AS ?path) }}
  FILTER(?p NOT IN ({excluded}))
{_TAIL}
}}
LIMIT 100"""


# ---------------------------------------------------------------------------
# 5. 결과 해석 / 청크 정렬
# ---------------------------------------------------------------------------

def _label(b: Dict[str, Any], label_key: str, uri_key: str) -> str:
    lab = _val(b, label_key)
    if lab:
        return lab
    raw = _val(b, uri_key) or ""
    return local_name(raw) if raw.startswith("http") else raw


def parse_triple_bindings(
    bindings: List[Dict[str, Any]],
    anchor_label: str = "",
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """타게팅/개요/두 엔티티 SPARQL 바인딩 → 트리플 목록 (s-p-o 단위로 청크 병합).

    트리플: {"subject","predicate","object","path","dir","chunk_ids","edge_chunk_ids",
             "s_uri","p_uri","o_uri"}
    구조 경로(깊이 2~3)는 (앵커 라벨, "tradeoffs.pros", 값) 으로 평탄화한다.
    """
    order: List[Tuple[str, str, str]] = []
    by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for b in bindings:
        s, p, o = _val(b, "s"), _val(b, "p"), _val(b, "o")
        if not (s and p and o):
            continue
        k = (s, p, o)
        t = by_key.get(k)
        if t is None:
            raw_path = _val(b, "path") or ""
            direction, _, seg_str = raw_path.partition("|")
            if not seg_str:
                direction, seg_str = ("in" if raw_path.endswith("-in") else "out"), ""
            segments = seg_str.split(".") if seg_str else [local_name(p)]
            if len(segments) >= 2:
                subject = anchor_label or local_name(s)
                predicate = ".".join(segments)
            else:
                subject = _label(b, "sLabel", "s")
                predicate = local_name(p)
            t = {
                "subject": subject, "predicate": predicate, "object": _label(b, "oLabel", "o"),
                "path": raw_path, "dir": direction or "out",
                "chunk_ids": [], "edge_chunk_ids": [],
                "s_uri": s, "p_uri": p, "o_uri": o,
            }
            by_key[k] = t
            order.append(k)
        c = _val(b, "chunk")
        if c and c not in t["chunk_ids"]:
            t["chunk_ids"].append(c)
        ec = _val(b, "edgeChunk")
        if ec and ec not in t["edge_chunk_ids"]:
            t["edge_chunk_ids"].append(ec)
    triples = [by_key[k] for k in order]
    return triples[:limit] if limit else triples


def rank_chunk_ids(triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """근거 청크를 트리플 연결 순으로 정렬.

    1순위: 리프 트리플을 직접 지지하는 청크 — 지지 트리플 수 내림차순, 첫 등장 순.
    2순위: 구조 경로 간선(앵커→구조노드)의 청크.
    반환: [{"chunk_id", "triple_idx": [1-based…], "kind": "triple|edge"}]
    """
    support: Dict[str, List[int]] = {}
    first: Dict[str, int] = {}
    for i, t in enumerate(triples, 1):
        for c in t.get("chunk_ids") or []:
            support.setdefault(c, []).append(i)
            first.setdefault(c, i)
    ranked = sorted(support, key=lambda c: (-len(support[c]), first[c]))
    out = [{"chunk_id": c, "triple_idx": support[c], "kind": "triple"} for c in ranked]
    seen = set(ranked)
    for i, t in enumerate(triples, 1):
        for c in t.get("edge_chunk_ids") or []:
            if c not in seen:
                seen.add(c)
                out.append({"chunk_id": c, "triple_idx": [i], "kind": "edge"})
    return out


# ---------------------------------------------------------------------------
# 6. Execution Log 추론 리포트
# ---------------------------------------------------------------------------

MODE_LABELS = {
    "A": "A(결정적 매칭)",
    "B": "B(LLM 경로 선택)",
    "C": "C(LLM SPARQL 생성)",
    "overview": "overview(개요 이웃 조회)",
    "pair": "pair(두 엔티티 직접 관계)",
    "none": "none(일치 관계 없음)",
    "P": "P(질의 계획 — 유형 수준)",
    "H": "H(다단계 체인 — 홉별 관계 고정 조회)",
    "E": "E(앵커별 관계 조회 — 두 엔티티를 각각 조회해 비교·계산)",
}
ROLE_LABELS = {"filter": "필터", "aggregate": "집계", "return": "반환"}
TIER_LABELS = {1: "완전일치", 2: "어간일치", 3: "토큰포함"}


def _short_chunk(cid: str) -> str:
    return cid.split("::")[-1] if "::" in cid else cid


def render_reasoning_report(reasoning: Dict[str, Any], max_triples: int = 15) -> List[str]:
    """추론 리포트 → Execution Log 라인 목록.

    주의: retrieval.py 가 로그 문자열의 'error/failed/fallback' 을 스캔해
    has_error/used_fallback 을 켜므로 그 단어를 쓰지 않는다.
    """
    lines = ["[Graph] ━━ 추론 리포트 ━━"]
    an = reasoning.get("analysis") or {}
    roles = an.get("entity_roles") or {}
    ents = an.get("entities") or []
    ent_txt = ", ".join(f"'{e}'({roles[e]})" if e in roles else f"'{e}'" for e in ents) or "(없음)"
    aliases = an.get("relation_aliases") or []
    tc = f" | 대상 유형: '{an['target_class']}'" if an.get("target_class") else ""
    lines.append(
        f"[Graph 1/5 질문 분석] intent={an.get('intent') or '-'}{tc} | 엔티티: {ent_txt} | "
        f"관계어: {', '.join(aliases) if aliases else '(없음)'}"
        + (f" | 모델: {an['model']}" if an.get("model") else "")
    )

    if an.get("llm_issue"):
        lines.append(f"    ⚠ 질의 분석 LLM 호출 불가 — 엔티티/관계어를 spaCy 토큰으로 대체: {an['llm_issue']}")

    linking = reasoning.get("linking") or []
    tg = reasoning.get("targeting") or {}
    kinds_txt = ""
    if tg.get("kinds"):
        ks = []
        for k in tg["kinds"]:
            how = "rdf:type" if k.get("typed") else "경로 시그니처 추론"
            ks.append(f"{k['name']}({how}, 멤버 {k['members']}개: {', '.join(k.get('examples') or [])})")
        kinds_txt = " | 유형: " + "; ".join(ks)
    if linking:
        parts = []
        for l in linking:
            note = ""
            if l.get("value_node"):
                note = " (값 노드 — 부분일치라 조건 힌트로 쓰지 않음)" if l.get("hint_dropped") else " (값 노드 — 조건 값으로 사용)"
            eq = l.get("equivalents") or []
            if eq:
                note += f" (동일 엔티티 {len(eq)}개 함께 조회: {', '.join(local_name(u) for u in eq)})"
            parts.append(f"'{l['entity']}' → inst:{local_name(l['uri'])}{note}")
        lines.append(f"[Graph 2/5 엔티티 링킹] {' | '.join(parts)}{kinds_txt}")
    else:
        lines.append(f"[Graph 2/5 엔티티 링킹] 그래프 노드에 연결된 엔티티 없음{kinds_txt}")

    mode = tg.get("mode") or "-"
    head = f"[Graph 3/5 관계 타게팅] mode={MODE_LABELS.get(mode, mode)}"
    details = []
    for m in tg.get("matches") or []:
        rel = TIER_LABELS.get(m.get("tier"), "")
        suffix = " (하위 경로 전체)" if m.get("expanded") else ""
        inv = " [역관계]" if m.get("inverse") else ""
        details.append(f"'{m['alias']}' = {m['matched']}{suffix} ({rel}){inv}")
    if details:
        head += " | " + "; ".join(details)
    if tg.get("catalog_size") is not None:
        head += f" | 후보 경로 {tg['catalog_size']}개 중 {len(tg.get('selected_paths') or [])}개 선택"
    if tg.get("reason"):
        head += f" | 근거: {tg['reason']}"
    lines.append(head)
    for sp in tg.get("selected_paths") or []:
        lines.append(f"    · {sp}")
    plan = tg.get("plan") or {}
    if plan.get("value_matches"):
        lines.append(f"    · 값 매칭: {'; '.join(plan['value_matches'])}")
    for e in tg.get("equivalences") or []:
        lines.append(f"    · 동치: {e}")
    for adj in tg.get("adjustments") or []:
        lines.append(f"    · 조정: {adj}")
    for w in tg.get("warnings") or []:
        lines.append(f"    ⚠ {w}")
    if tg.get("result_entities") is not None and mode == "P":
        more = " (상한 초과, 일부만)" if tg.get("truncated") else ""
        lines.append(f"    · 결과 엔티티 {len(tg['result_entities'])}개{more}: {', '.join(tg['result_entities'])}")
    if reasoning.get("sparql"):
        lines.append("  SPARQL:\n" + "\n".join("    " + l for l in reasoning["sparql"].strip().splitlines()))

    triples = reasoning.get("triples") or []
    grouped = any(t.get("entity") for t in triples)
    if grouped:
        n_ent = len({t.get("entity") for t in triples})
        lines.append(f"[Graph 4/5 선택 트리플] 결과 엔티티 {n_ent}개 · 트리플 {len(triples)}건")
    else:
        lines.append(f"[Graph 4/5 선택 트리플] {len(triples)}건")
    limit = max_triples * 2 if grouped else max_triples
    current = None
    for i, t in enumerate(triples[:limit], 1):
        if grouped and t.get("entity") != current:
            current = t.get("entity")
            lines.append(f"  ▸ {current}")
        src = ", ".join(_short_chunk(c) for c in (t.get("chunk_ids") or [])) or "청크 연결 없음"
        arrow = f"—{t['predicate']}→"
        role = f"[{ROLE_LABELS.get(t.get('role'), t.get('role'))}] " if t.get("role") else ""
        indent = "    " if grouped else "  "
        lines.append(f"{indent}{i}. {role}{t['subject']} {arrow} {str(t['object'])[:80]}   ⟵ {src}")
    if len(triples) > limit:
        lines.append(f"  … 외 {len(triples) - limit}건")

    chunks = reasoning.get("chunks") or []
    order_txt = reasoning.get("chunk_order_label") or "트리플 연결 순"
    lines.append(f"[Graph 5/5 근거 청크] {len(chunks)}건 ({order_txt})")
    for i, c in enumerate(chunks, 1):
        idx = ",".join(str(x) for x in c.get("triple_idx") or [])
        kind = " (구조 간선)" if c.get("kind") == "edge" else ""
        missing = " — 벡터 저장소에 본문 없음" if c.get("missing") else ""
        lines.append(f"  #{i} {_short_chunk(c['chunk_id'])} ⟵ 트리플 {idx}{kind}{missing}")
    if reasoning.get("note"):
        lines.append(f"[Graph] 참고: {reasoning['note']}")
    lines.append("[Graph] ── 상세 trace ──")
    return lines
