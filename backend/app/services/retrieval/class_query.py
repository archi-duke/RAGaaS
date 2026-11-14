"""유형 수준(class-level) 그래프 질문 — 질의 계획 기반 SPARQL (순수 함수).

설계: docs/design-graph-class-query.md

앵커 엔티티가 없거나 앵커가 '조건 값'인 질문(필터·역방향·집계)을 처리한다.
  1. 스키마 카탈로그: 데이터에서 유형(kind)별 경로·값 종류·값 어휘를 추출
  2. LLM 은 카탈로그 번호·값 목록 안에서만 질의 계획(JSON)을 낸다
  3. 코드가 계획을 검증(무효 필터 → 계획 반려)하고 SPARQL 로 결정적 컴파일
  4. 근거 청크는 트리플 s-p-o 정확 일치 statement 로 조인, 엔티티별 라운드로빈 정렬
Fuseki 호출은 하지 않는다 (fuseki.py 가 쿼리를 실행하고 결과를 넘긴다).
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.retrieval.entity_linking import _compact, normalize_text, score_candidate
from app.services.retrieval.relation_targeting import (
    STMT_PREFIX,
    STRUCT_NODE_REGEX,
    _EXCLUDED_PREDICATES,
    _PREFIXES,
    _val,
    is_struct_node,
    local_name,
    match_tier,
)

INST_PREFIX = "http://rag.local/inst/"
MAX_MEMBERS = 500
ENUM_MAX_VALUES = 15
MAX_FILTERS = 4
MAX_RETURNS = 6
MAX_RESULT_ENTITIES = 50
MAX_PATHS_FOR_LLM = 150

OPS_BY_TYPE = {
    "enum": {"eq", "ne", "in", "exists", "not_exists"},
    "number": {"eq", "ne", "in", "gt", "gte", "lt", "lte", "exists", "not_exists"},
    "text": {"eq", "contains", "exists", "not_exists"},
}
_NUM_OPS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")

# 값 표기 안전망 (해당 경로의 값 목록에 있을 때만 적용)
VALUE_SYNONYMS: Dict[str, str] = {
    "높음": "high", "높은": "high", "높다": "high", "상": "high",
    "중간": "medium", "보통": "medium", "중": "medium",
    "낮음": "low", "낮은": "low", "낮다": "low", "하": "low",
    "작은": "small", "작음": "small", "소규모": "small", "작을": "small",
    "큰": "large", "큼": "large", "대규모": "large",
    "긍정": "positive", "긍정적": "positive", "부정": "negative", "부정적": "negative",
}

_EXCL = ", ".join(_EXCLUDED_PREDICATES)


def _iri(u: str) -> str:
    return f"<{u}>"


def _values_clause(var: str, uris: Sequence[str]) -> str:
    return f"VALUES {var} {{ {' '.join(_iri(u) for u in uris)} }}"


def _sparql_str(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


# ---------------------------------------------------------------------------
# 1. 멤버 / 유형(kind)
# ---------------------------------------------------------------------------

def build_member_query() -> str:
    """레코드 후보: inst: 노드(구조 노드 제외) 중 시스템 predicate 외 outgoing 이 있는 노드."""
    return f"""{_PREFIXES}
SELECT ?e ?t (GROUP_CONCAT(DISTINCT STR(?p); separator=" ") AS ?preds)
FROM <urn:x-arq:UnionGraph>
WHERE {{
  ?e ?p ?o .
  FILTER(STRSTARTS(STR(?e), "{INST_PREFIX}"))
  FILTER(!REGEX(STR(?e), "{STRUCT_NODE_REGEX}"))
  FILTER(?p NOT IN ({_EXCL}))
  OPTIONAL {{ ?e rdf:type ?t }}
}}
GROUP BY ?e ?t
LIMIT 5000"""


def infer_kinds(bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """멤버를 유형으로 묶는다.

    rdf:type 이 있으면 클래스별, 없으면 depth-1 predicate 집합 Jaccard ≥ 0.5 로
    결정적 탐욕 군집화(predicate 수 내림차순 → URI 순).
    반환: [{"name", "class_uri", "members": [uri…], "examples": [로컬네임…]}] (멤버 수 내림차순)
    """
    preds: Dict[str, set] = {}
    types: Dict[str, str] = {}
    for b in bindings:
        e = _val(b, "e")
        if not e:
            continue
        preds.setdefault(e, set()).update((_val(b, "preds") or "").split())
        t = _val(b, "t")
        if t and e not in types:
            types[e] = t

    kinds: List[Dict[str, Any]] = []
    by_class: Dict[str, List[str]] = {}
    untyped: List[str] = []
    for e in preds:
        if e in types:
            by_class.setdefault(types[e], []).append(e)
        else:
            untyped.append(e)
    for cls, members in by_class.items():
        kinds.append({"name": local_name(cls), "class_uri": cls, "members": sorted(members)})

    clusters: List[Tuple[set, List[str]]] = []
    for e in sorted(untyped, key=lambda x: (-len(preds[x]), x)):
        placed = False
        for sig, members in clusters:
            inter, union = len(sig & preds[e]), len(sig | preds[e])
            if union and inter / union >= 0.5:
                members.append(e)
                placed = True
                break
        if not placed:
            clusters.append((set(preds[e]), [e]))
    # 단독 멤버이면서 predicate 가 1개뿐인 노드(라벨성 노드)는 유형에서 제외
    clusters = [(s, m) for s, m in clusters if len(m) > 1 or len(s) > 1]
    for i, (_, members) in enumerate(sorted(clusters, key=lambda c: -len(c[1])), 1):
        kinds.append({"name": f"K{i}", "class_uri": None, "members": sorted(members)})

    kinds.sort(key=lambda k: -len(k["members"]))
    for k in kinds:
        k["members"] = k["members"][:MAX_MEMBERS]
        k["examples"] = [local_name(m) for m in k["members"][:5]]
    return kinds


# ---------------------------------------------------------------------------
# 2. 유형별 경로 카탈로그 (값 종류·값 어휘)
# ---------------------------------------------------------------------------

def build_kind_catalog_query(members: Sequence[str]) -> str:
    values = _values_clause("?e", members)
    return f"""{_PREFIXES}
SELECT ?p0 ?p1 ?p2 ?v (SAMPLE(?vl) AS ?vLabel) (COUNT(DISTINCT ?e) AS ?ne)
FROM <urn:x-arq:UnionGraph>
WHERE {{
  {values}
  {{
    ?e ?p0 ?v .
    FILTER(!REGEX(STR(?v), "{STRUCT_NODE_REGEX}"))
  }}
  UNION
  {{
    ?e ?p0 ?m .
    FILTER(REGEX(STR(?m), "{STRUCT_NODE_REGEX}"))
    ?m ?p1 ?v .
    FILTER(!REGEX(STR(?v), "{STRUCT_NODE_REGEX}"))
    FILTER(?p1 NOT IN ({_EXCL}))
  }}
  UNION
  {{
    ?e ?p0 ?m .
    FILTER(REGEX(STR(?m), "{STRUCT_NODE_REGEX}"))
    ?m ?p1 ?m2 .
    FILTER(REGEX(STR(?m2), "{STRUCT_NODE_REGEX}"))
    ?m2 ?p2 ?v .
    FILTER(?p2 NOT IN ({_EXCL}))
  }}
  FILTER(?p0 NOT IN ({_EXCL}))
  OPTIONAL {{ ?v rdfs:label ?vl }}
}}
GROUP BY ?p0 ?p1 ?p2 ?v
LIMIT 20000"""


def build_kind_path_members_query(members: Sequence[str]) -> str:
    """경로별 보유 멤버 (동치 판정의 멤버 상보성·접두 공존 게이트용)."""
    values = _values_clause("?e", members)
    return f"""{_PREFIXES}
SELECT DISTINCT ?e ?p0 ?p1 ?p2
FROM <urn:x-arq:UnionGraph>
WHERE {{
  {values}
  {{
    ?e ?p0 ?v .
    FILTER(!REGEX(STR(?v), "{STRUCT_NODE_REGEX}"))
  }}
  UNION
  {{
    ?e ?p0 ?m .
    FILTER(REGEX(STR(?m), "{STRUCT_NODE_REGEX}"))
    ?m ?p1 ?v .
    FILTER(!REGEX(STR(?v), "{STRUCT_NODE_REGEX}"))
    FILTER(?p1 NOT IN ({_EXCL}))
  }}
  UNION
  {{
    ?e ?p0 ?m .
    FILTER(REGEX(STR(?m), "{STRUCT_NODE_REGEX}"))
    ?m ?p1 ?m2 .
    FILTER(REGEX(STR(?m2), "{STRUCT_NODE_REGEX}"))
    ?m2 ?p2 ?v .
    FILTER(?p2 NOT IN ({_EXCL}))
  }}
  FILTER(?p0 NOT IN ({_EXCL}))
}}
LIMIT 50000"""


def attach_coverage(paths: List[Dict[str, Any]], bindings: List[Dict[str, Any]]) -> None:
    by_key = {p["key"]: p for p in paths}
    for p in paths:
        p["member_ids"] = set()
    for b in bindings:
        uris = [u for u in (_val(b, "p0"), _val(b, "p1"), _val(b, "p2")) if u]
        key = ".".join(local_name(u) for u in uris)
        if key in by_key and _val(b, "e"):
            by_key[key]["member_ids"].add(_val(b, "e"))


def parse_kind_catalog(bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """경로별 값 어휘·값 종류.

    경로: {"segments", "uris", "key", "type": enum|number|text,
           "values": [{"uri","label","members"}], "dv", "members_max", "examples"}
    """
    by_key: Dict[str, Dict[str, Any]] = {}
    for b in bindings:
        uris = [u for u in (_val(b, "p0"), _val(b, "p1"), _val(b, "p2")) if u]
        v = _val(b, "v")
        if not uris or not v:
            continue
        segs = [local_name(u) for u in uris]
        key = ".".join(segs)
        p = by_key.setdefault(key, {"segments": segs, "uris": uris, "key": key, "values": []})
        label = _val(b, "vLabel") or (local_name(v) if v.startswith("http") else v)
        try:
            ne = int(_val(b, "ne") or 0)
        except ValueError:
            ne = 0
        p["values"].append({"uri": v, "label": label, "members": ne})

    paths = []
    for p in by_key.values():
        vals = sorted(p["values"], key=lambda x: (-x["members"], x["label"]))
        p["dv"] = len(vals)
        p["members_max"] = max((x["members"] for x in vals), default=0)
        labels = [x["label"] for x in vals]
        if labels and all(_NUM_RE.match(str(l).strip()) for l in labels):
            p["type"] = "number"
            nums = [float(l) for l in labels]
            p["range"] = [min(nums), max(nums)]
        elif p["dv"] <= ENUM_MAX_VALUES:
            p["type"] = "enum"
        else:
            p["type"] = "text"
        p["values"] = vals
        p["examples"] = [x["label"][:40] for x in vals[:3]]
        paths.append(p)
    paths.sort(key=lambda p: (len(p["segments"]), p["key"]))
    return paths


# ---------------------------------------------------------------------------
# 3. 질의 계획: 프롬프트 / 검증 / 값 해석
# ---------------------------------------------------------------------------

def _path_line(i: int, p: Dict[str, Any], index: Optional[Dict[str, int]] = None) -> str:
    if p.get("equiv") and p.get("equiv_rep") and p["equiv_rep"] != p["key"]:
        rep_no = (index or {}).get(p["equiv_rep"])
        ref = f"{rep_no}번" if rep_no is not None else p["equiv_rep"]
        return f"{i}. {p['key']} → {ref}과 동치 ({ref} 사용)"
    eq = f" (동치: {', '.join(p['equiv'])})" if p.get("equiv") else ""
    if p["type"] == "enum":
        def lab(v):
            eqv = (p.get("value_equiv") or {}).get(v["uri"]) or []
            return f"{v['label']}({v['members']})" + "".join(f" ≡ {e['label']}" for e in eqv if e['label'] != v['label'])
        vals = ", ".join(lab(v) for v in p["values"])
        return f"{i}. {p['key']}{eq} [enum: {vals}]"
    if p["type"] == "number":
        lo, hi = p.get("range", [0, 0])
        return f"{i}. {p['key']}{eq} [number: {lo:g}~{hi:g}]"
    ex = " / ".join(p["examples"])
    return f"{i}. {p['key']}{eq} [text, 값 {p['dv']}종, 예: {ex}]"


def build_plan_messages(
    query_text: str,
    kinds: List[Dict[str, Any]],
    catalogs: Dict[str, List[Dict[str, Any]]],
    value_hints: Optional[Sequence[str]] = None,
    retry_note: str = "",
) -> List[Dict[str, str]]:
    kind_lines = []
    for k in kinds:
        cls = f" (class {k['name']})" if k.get("class_uri") else " (rdf:type 없음 · 경로 시그니처로 묶음)"
        kind_lines.append(f"- {k['name']}{cls}: 멤버 {len(k['members'])}개, 예: {', '.join(k['examples'])}")
    path_blocks = []
    for k in kinds:
        cat = catalogs.get(k["name"], [])[:MAX_PATHS_FOR_LLM]
        index = {p["key"]: i for i, p in enumerate(cat)}
        lines = [_path_line(i, p, index) for i, p in enumerate(cat)]
        path_blocks.append(f"[{k['name']}] 경로 목록\n" + "\n".join(lines))
    hints = ""
    if value_hints:
        hints = f"\n질문에 등장한 그래프 값 노드(조건 값일 가능성 높음): {', '.join(value_hints)}\n"
    user = f"""질문: {query_text}
{hints}
유형(kind):
{chr(10).join(kind_lines)}

{chr(10).join(path_blocks)}

위 목록만 사용해 질문을 질의 계획(JSON)으로 표현하라.
- kind: 결과로 나와야 하는 엔티티 유형 이름.
- filters: [{{"path": 경로번호, "op": 연산자, "value": 값}}] (AND, 최대 {MAX_FILTERS}개)
  "(동치: …)" 로 표시된 경로는 같은 필드의 다른 표기라 대표 번호 하나만 쓰면 자동으로 함께 조회된다.
  목록에서 같은 필드인데 동치로 묶이지 않은 경로를 발견하면 path 에 번호 배열(최대 4)을 써도 된다.
  op: enum → eq|ne|in|exists|not_exists, number → eq|ne|in|gt|gte|lt|lte|exists|not_exists,
      text → contains|eq|exists|not_exists. in 은 value 에 배열.
  enum 값은 목록에 적힌 표기 그대로 써라 (예: "작을 때" → "small", "높은" → "high").
  질문의 값이 목록에 없으면(예: "very low" 인데 목록엔 low 뿐) 비슷한 값으로 바꾸지 말고 질문 표기 그대로 써라.
  "X와 잘 어울리는/관련된 Y" 같은 역방향 질문은 X 가 값으로 들어가는 경로의 eq 필터로 표현한다.
- return: 결과 엔티티마다 보여줄 경로 번호 (질문이 묻는 속성, 최대 {MAX_RETURNS}개, 없으면 []).
- aggregate: 개수/최대/최소를 물으면 {{"fn": "count|max|min|count_members", "path": 경로번호, "order": "desc|asc", "limit": 1}}
  (count = 경로 값 개수로 엔티티 순위, count_members = 조건을 만족하는 엔티티 수, max/min 은 number 경로)
  같은 항목의 특정 값만 세려면 "value": 값 (예: quality_attributes.effect 중 positive 만 → path=effect 경로, value="positive"),
  개수 조건("3개 이상")은 "having": {{"op": "gte|gt|lte|lt|eq", "value": 3}} (having 이 있으면 limit 무시, 조건 만족 전부).
  집계가 아니면 null.
- mode: 표현 가능하면 "plan", 목록 경로로 표현할 수 없는 질문(유형 간 조인, 산술 등)이면 "unsupported",
  질문이 묻는 속성이 목록에 없으면 "none".
{retry_note}
JSON 만 출력: {{"mode": "...", "kind": "...", "filters": [...], "return": [...], "aggregate": null, "reason": "한 줄 근거"}}"""
    return [
        {"role": "system", "content": "You translate questions into a constrained knowledge-graph query plan. Use only the listed paths and values. Output JSON only."},
        {"role": "user", "content": user},
    ]


def resolve_value(raw: Any, path: Dict[str, Any], value_hints_uris: Sequence[str] = ()) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """계획의 값 → 경로 값 목록의 항목들. (해석된 값들 | None, 매칭 설명)"""
    items = raw if isinstance(raw, list) else [raw]
    out: List[Dict[str, Any]] = []
    notes = []
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        hit = None
        how = ""
        for v in path["values"]:
            if v["uri"] in value_hints_uris and (_compact(v["label"]) == _compact(s) or _compact(local_name(v["uri"])) == _compact(s)):
                hit, how = v, "질문 앵커"
                break
        if hit is None:
            for v in path["values"]:
                if _compact(v["label"]) == _compact(s) or _compact(local_name(v["uri"])) == _compact(s):
                    hit, how = v, "완전일치"
                    break
        if hit is None:
            syn = VALUE_SYNONYMS.get(normalize_text(s))
            if syn:
                hit = next((v for v in path["values"] if _compact(v["label"]) == _compact(syn)), None)
                how = "동의어" if hit else ""
        if hit is None:
            best = None
            for v in path["values"]:
                t = match_tier(s, v["label"]) or match_tier(s, local_name(v["uri"]))
                if t and t <= 2 and (best is None or t < best[0]):
                    best = (t, v)
            if best:
                hit, how = best[1], "어간일치"
        if hit is None and path["type"] == "text":
            scored = [(score_candidate(s, v["label"]), v) for v in path["values"]]
            scored = [x for x in scored if x[0] >= 25]
            if scored:
                hit, how = max(scored, key=lambda x: x[0])[1], "라벨 유사"
        if hit is None:
            return None, f"'{s}' 는 {path['key']} 값 목록에 없음"
        if hit not in out:
            out.append(hit)
            notes.append(f"'{s}'→{hit['label']}({how})")
    return out, ", ".join(notes)


def validate_plan(
    data: Optional[Dict[str, Any]],
    kinds: List[Dict[str, Any]],
    catalogs: Dict[str, List[Dict[str, Any]]],
    value_hints_uris: Sequence[str] = (),
) -> Dict[str, Any]:
    """계획 검증 → {"status": ok|reject|zero|unsupported|none, "plan": 정규화된 계획, "message", "adjustments"}

    - 무효 필터(경로/연산자/값 종류 불일치)는 계획 전체 반려 (필터를 버리면 결과가 넓어져 오답)
    - enum 경로에 없는 값은 zero (Strict 빈 결과 확정)
    - 무효 return 은 버리고 adjustments 에 기록
    """
    if not data:
        return {"status": "reject", "message": "계획 JSON 을 해석할 수 없음"}
    mode = str(data.get("mode") or "plan").lower()
    reason = str(data.get("reason") or "")[:200]
    if mode in ("unsupported", "none"):
        return {"status": mode, "message": reason or mode, "reason": reason}

    kind = next((k for k in kinds if k["name"] == data.get("kind")), None)
    if kind is None and len(kinds) == 1:
        kind = kinds[0]
    if kind is None:
        return {"status": "reject", "message": f"kind '{data.get('kind')}' 가 목록에 없음"}
    full_catalog = catalogs.get(kind["name"], [])
    catalog = full_catalog[:MAX_PATHS_FOR_LLM]
    by_key = {c["key"]: c for c in full_catalog}

    def _one(idx) -> Optional[Dict[str, Any]]:
        try:
            i = int(idx)
        except (TypeError, ValueError):
            return None
        return catalog[i] if 0 <= i < len(catalog) else None

    def path_at(idx) -> Optional[Dict[str, Any]]:
        """경로 번호(또는 번호 배열) → 동치 경로까지 확장한 경로 뷰.

        뷰: 대표 경로의 복사본 + alts(실제 경로들) + expansion(추가된 경로와 근거) +
        합친 값 어휘(values)·종류(type). 동치가 없으면 alts=[자기 자신] (기존과 동일한 SPARQL).
        """
        picked = [_one(x) for x in idx] if isinstance(idx, list) else [_one(idx)]
        picked = [x for x in picked[:4] if x is not None]
        if not picked:
            return None
        alts: List[Dict[str, Any]] = []
        expansion: List[Dict[str, str]] = []
        for x in picked:
            if x not in alts:
                alts.append(x)
                if len(alts) > 1:
                    expansion.append({"key": x["key"], "basis": "plan"})
            for k in x.get("equiv") or []:
                y = by_key.get(k)
                if y is not None and y not in alts:
                    alts.append(y)
                    expansion.append({"key": k, "basis": "/".join(x.get("equiv_basis") or []) or "normalized"})
        view = dict(picked[0])
        view["alts"] = alts
        view["expansion"] = expansion
        if len(alts) > 1:
            fams = {("number" if a["type"] == "number" else "nominal") for a in alts}
            if len(fams) > 1:
                view["type_conflict"] = True
            merged: Dict[str, Dict[str, Any]] = {}
            for a in alts:
                for v in a.get("values") or []:
                    if v["uri"] in merged:
                        merged[v["uri"]] = dict(merged[v["uri"]], members=merged[v["uri"]]["members"] + v["members"])
                    else:
                        merged[v["uri"]] = dict(v)
            view["values"] = sorted(merged.values(), key=lambda v: (-v["members"], v["label"]))
            if fams == {"number"}:
                view["type"] = "number"
            else:
                view["type"] = "enum" if len(view["values"]) <= ENUM_MAX_VALUES else "text"
            vq: Dict[str, List[Dict[str, Any]]] = {}
            for a in alts:
                for u, eqs in (a.get("value_equiv") or {}).items():
                    vq.setdefault(u, [])
                    for e in eqs:
                        if e not in vq[u]:
                            vq[u].append(e)
            view["value_equiv"] = vq
        return view

    def expand_values(view: Dict[str, Any], resolved: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """해석된 값에 동치 값(같은 뜻의 다른 표기)을 더한다."""
        out = list(resolved)
        added = []
        for v in resolved:
            for e in (view.get("value_equiv") or {}).get(v["uri"], []):
                if all(e["uri"] != x["uri"] for x in out):
                    out.append(e)
                    added.append(e["label"])
        return out, added

    adjustments: List[str] = []
    filters = []
    for f in (data.get("filters") or [])[:MAX_FILTERS]:
        if not isinstance(f, dict):
            return {"status": "reject", "message": f"필터 형식 오류: {f}"}
        p = path_at(f.get("path"))
        op = str(f.get("op") or "").lower()
        if p is None:
            return {"status": "reject", "message": f"필터 경로 번호 {f.get('path')} 가 목록에 없음"}
        if p.get("type_conflict"):
            return {"status": "reject", "message": f"{p['key']} 와 함께 지정한 경로들의 값 종류가 다름"}
        if op not in OPS_BY_TYPE[p["type"]]:
            return {"status": "reject", "message": f"{p['key']}({p['type']}) 에 연산자 {op} 사용 불가"}
        nf = {"path": p, "op": op}
        if op in ("exists", "not_exists"):
            pass
        elif op in _NUM_OPS or (p["type"] == "number" and op in ("eq", "ne", "in")):
            vals = f.get("value") if isinstance(f.get("value"), list) else [f.get("value")]
            try:
                nf["numbers"] = [float(str(v).strip()) for v in vals]
            except (TypeError, ValueError):
                return {"status": "reject", "message": f"{p['key']} 에 숫자가 아닌 값 {f.get('value')}"}
        elif op == "contains":
            nf["text"] = str(f.get("value") or "").strip()
            if not nf["text"]:
                return {"status": "reject", "message": f"{p['key']} contains 값 없음"}
        else:
            resolved, note = resolve_value(f.get("value"), p, value_hints_uris)
            if resolved is None:
                return {"status": "zero", "message": note, "kind": kind}
            resolved, added = expand_values(p, resolved)
            if added:
                note += f" +{', '.join(added)}(동치 값)"
            nf["values"] = resolved
            nf["note"] = note
        filters.append(nf)

    returns = []
    for idx in (data.get("return") or [])[:MAX_RETURNS]:
        p = path_at(idx)
        if p is None:
            adjustments.append(f"반환 경로 번호 {idx} 무효 → 제외")
        elif p.get("type_conflict"):
            adjustments.append(f"반환 경로 {p['key']} 동치 묶음 종류 불일치 → 첫 경로만")
            p = dict(p, alts=p["alts"][:1], expansion=[])
            returns.append(p)
        elif all(p["key"] != r["key"] for r in returns):
            returns.append(p)

    aggregate = None
    agg = data.get("aggregate")
    if isinstance(agg, dict) and agg.get("fn"):
        fn = str(agg["fn"]).lower()
        order = "asc" if str(agg.get("order") or "desc").lower() == "asc" else "desc"
        try:
            limit = max(1, min(int(agg.get("limit") or 1), MAX_RESULT_ENTITIES))
        except (TypeError, ValueError):
            limit = 1
        if fn == "count_members":
            aggregate = {"fn": fn}
        elif fn in ("count", "max", "min"):
            p = path_at(agg.get("path"))
            if p is None:
                return {"status": "reject", "message": f"집계 경로 번호 {agg.get('path')} 가 목록에 없음"}
            if fn in ("max", "min") and p["type"] != "number":
                return {"status": "reject", "message": f"{fn} 는 number 경로만 가능 ({p['key']} 는 {p['type']})"}
            aggregate = {"fn": fn, "path": p, "order": order, "limit": limit}
            if fn == "count" and agg.get("value") not in (None, "", []):
                resolved, note = resolve_value(agg.get("value"), p, value_hints_uris)
                if resolved is None:
                    return {"status": "zero", "message": note, "kind": kind}
                resolved, added = expand_values(p, resolved)
                if added:
                    note += f" +{', '.join(added)}(동치 값)"
                aggregate["values"] = resolved
                aggregate["note"] = note
            hv = agg.get("having")
            if isinstance(hv, dict) and hv.get("op") in ("gte", "gt", "lte", "lt", "eq"):
                try:
                    aggregate["having"] = {"op": hv["op"], "value": float(hv.get("value"))}
                except (TypeError, ValueError):
                    return {"status": "reject", "message": f"having 값이 숫자가 아님: {hv.get('value')}"}
        else:
            return {"status": "reject", "message": f"집계 함수 {fn} 미지원"}

    if not filters and not aggregate and not returns:
        return {"status": "reject", "message": "필터·집계·반환이 모두 비어 있음"}

    return {
        "status": "ok",
        "plan": {"kind": kind, "filters": filters, "returns": returns, "aggregate": aggregate, "reason": reason},
        "adjustments": adjustments,
    }


def _plan_equivalences(plan: Dict[str, Any]) -> List[str]:
    """계획에서 동치 확장된 경로 설명 (리포트용)."""
    from app.services.schema_alignment.equivalence import BASIS_LABELS
    views = [f["path"] for f in plan["filters"]] + list(plan["returns"])
    if plan.get("aggregate") and plan["aggregate"].get("path"):
        views.append(plan["aggregate"]["path"])
    out, seen = [], set()
    for v in views:
        for e in v.get("expansion") or []:
            basis = "/".join(BASIS_LABELS.get(b, b) for b in e["basis"].split("/"))
            txt = f"{v['key']} ≡ {e['key']} ({basis})"
            if txt not in seen:
                seen.add(txt)
                out.append(txt)
    return out


def plan_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    """리포트/UI 용 계획 요약 (직렬화 가능)."""
    def fdesc(f):
        k = f["path"]["key"]
        op = f["op"]
        if "values" in f:
            vals = ", ".join(v["label"] for v in f["values"])
            return f"{k} {'=' if op == 'eq' else op} {vals}"
        if "numbers" in f:
            sym = _NUM_OPS.get(op, "=" if op == "eq" else op)
            return f"{k} {sym} {', '.join(f'{n:g}' for n in f['numbers'])}"
        if "text" in f:
            return f"{k} contains '{f['text']}'"
        return f"{k} {op}"
    agg = plan.get("aggregate")
    agg_txt = None
    if agg:
        if agg["fn"] == "count_members":
            agg_txt = "조건 만족 엔티티 수"
        else:
            target = agg["path"]["key"]
            if agg.get("values"):
                target += "=" + "|".join(v["label"] for v in agg["values"])
            if agg.get("having"):
                sym = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<", "eq": "="}[agg["having"]["op"]]
                agg_txt = f"{agg['fn']}({target}) {sym} {agg['having']['value']:g}"
            else:
                agg_txt = f"{agg['fn']}({target}) {agg['order']} 상위 {agg['limit']}"
    return {
        "kind": plan["kind"]["name"],
        "kind_members": len(plan["kind"]["members"]),
        "filters": [fdesc(f) for f in plan["filters"]],
        "value_matches": [f["note"] for f in plan["filters"] if f.get("note")]
                         + ([agg["note"]] if agg and agg.get("note") else []),
        "equivalences": _plan_equivalences(plan),
        "returns": [p["key"] for p in plan["returns"]],
        "aggregate": agg_txt,
    }


# ---------------------------------------------------------------------------
# 4. 컴파일
# ---------------------------------------------------------------------------

def _path_pattern(subject_var: str, uris: List[str], leaf_var: str, tag: str) -> Tuple[str, Optional[str]]:
    """?e 에서 경로를 따라 leaf_var 까지 가는 패턴. (패턴, 마지막 구조노드 변수)"""
    if len(uris) == 1:
        return f"{subject_var} <{uris[0]}> {leaf_var} .", None
    m1 = f"?m{tag}"
    pat = f"{subject_var} <{uris[0]}> {m1} . FILTER(REGEX(STR({m1}), \"{STRUCT_NODE_REGEX}\"))"
    if len(uris) == 2:
        return pat + f" {m1} <{uris[1]}> {leaf_var} .", m1
    m2 = f"?n{tag}"
    pat += f" {m1} <{uris[1]}> {m2} . FILTER(REGEX(STR({m2}), \"{STRUCT_NODE_REGEX}\")) {m2} <{uris[2]}> {leaf_var} ."
    return pat, m2


def _filter_condition(f: Dict[str, Any], v: str, tag: str) -> str:
    op = f["op"]
    if "values" in f:
        lst = ", ".join(_iri(x["uri"]) for x in f["values"])
        return f"FILTER({v} IN ({lst}))"
    if "numbers" in f:
        lbl = f"?nl{tag}"
        cmp = _NUM_OPS.get(op, "=")
        if op in ("eq", "ne", "in") or len(f["numbers"]) > 1:
            conds = " || ".join(f"xsd:decimal({lbl}) = {n:g}" for n in f["numbers"])
        else:
            conds = f"xsd:decimal({lbl}) {cmp} {f['numbers'][0]:g}"
        return f"OPTIONAL {{ {v} rdfs:label {lbl}_ }} BIND(COALESCE({lbl}_, STR({v})) AS {lbl}) FILTER({conds})"
    if "text" in f:
        lbl = f"?tl{tag}"
        return (f"OPTIONAL {{ {v} rdfs:label {lbl}_ }} BIND(COALESCE({lbl}_, STR({v})) AS {lbl}) "
                f"FILTER(CONTAINS(LCASE(STR({lbl})), LCASE({_sparql_str(f['text'])})))")
    return ""


def _alts(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    return view.get("alts") or [view]


def compile_member_query(plan: Dict[str, Any]) -> str:
    """필터를 만족하는 결과 엔티티 조회. 동치 경로는 UNION (경로 1개면 기존과 동일한 SPARQL)."""
    members = plan["kind"]["members"]
    parts = [_values_clause("?e", members)]
    for i, f in enumerate(plan["filters"]):
        negated = f["op"] in ("ne", "not_exists")
        blocks = []
        for j, alt in enumerate(_alts(f["path"])):
            tag = f"f{i}" if j == 0 else f"f{i}a{j}"
            v = f"?v{tag}"
            pat, _ = _path_pattern("?e", alt["uris"], v, tag)
            if f["op"] in ("exists", "not_exists"):
                cond = ""
            elif f["op"] == "ne":
                cond = _filter_condition(dict(f, op="eq"), v, tag)
            else:
                cond = _filter_condition(f, v, tag)
            blocks.append(f"{pat} {cond}".strip())
        block = blocks[0] if len(blocks) == 1 else " UNION ".join(f"{{ {b} }}" for b in blocks)
        parts.append(f"FILTER NOT EXISTS {{ {block} }}" if negated else block)
    body = "\n  ".join(parts)
    return f"""{_PREFIXES}
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?e
FROM <urn:x-arq:UnionGraph>
WHERE {{
  {body}
}}
ORDER BY ?e
LIMIT {MAX_RESULT_ENTITIES + 1}"""


def compile_aggregate_query(entities: Sequence[str], agg: Dict[str, Any]) -> str:
    p = agg["path"]
    alts = _alts(p)
    having = ""
    if agg.get("having"):
        sym = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<", "eq": "="}[agg["having"]["op"]]
        having = f"HAVING (?agg {sym} {agg['having']['value']:g})"
    cond = ""
    if agg.get("values"):
        cond = f" FILTER(?va IN ({', '.join(_iri(v['uri']) for v in agg['values'])}))"
    if len(alts) == 1:
        pat, last_struct = _path_pattern("?e", alts[0]["uris"], "?va", "a")
        if agg["fn"] == "count":
            # 리프 트리플 단위로 센다: (구조 항목, 값) 쌍 — pros 는 값 수만큼,
            # quality_attributes.effect=positive 는 항목 수만큼 (같은 값이 여러 항목에 있어도 각각 1)
            unit = f'CONCAT(STR({last_struct}), "|", STR(?va))' if last_struct else "?va"
            sel = f"(COUNT(DISTINCT {unit}) AS ?agg)"
            where = f"OPTIONAL {{ {pat}{cond} }}"
        else:
            fn = "MAX" if agg["fn"] == "max" else "MIN"
            sel = f"({fn}(xsd:decimal(COALESCE(?val, STR(?va)))) AS ?agg)"
            where = f"{pat} OPTIONAL {{ ?va rdfs:label ?val }}"
    else:
        # 동치 경로 합산: 대안마다 단위를 ?unit 으로 바인딩해 UNION
        branches = []
        for j, alt in enumerate(alts):
            pat, last_struct = _path_pattern("?e", alt["uris"], "?va", f"a{j}")
            if agg["fn"] == "count":
                unit = f'CONCAT(STR({last_struct}), "|", STR(?va))' if last_struct else "STR(?va)"
                branches.append(f"{{ {pat}{cond} BIND({unit} AS ?unit) }}")
            else:
                branches.append(f"{{ {pat} OPTIONAL {{ ?va rdfs:label ?val }} "
                                f"BIND(xsd:decimal(COALESCE(?val, STR(?va))) AS ?num) }}")
        union = " UNION ".join(branches)
        if agg["fn"] == "count":
            sel = "(COUNT(DISTINCT ?unit) AS ?agg)"
            where = f"OPTIONAL {{ {union} }}"
        else:
            fn = "MAX" if agg["fn"] == "max" else "MIN"
            sel = f"({fn}(?num) AS ?agg)"
            where = union
    order = "DESC(?agg)" if agg["order"] == "desc" else "ASC(?agg)"
    return f"""{_PREFIXES}
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?e {sel}
FROM <urn:x-arq:UnionGraph>
WHERE {{
  {_values_clause("?e", entities)}
  {where}
}}
GROUP BY ?e
{having}
ORDER BY {order} ?e
LIMIT {MAX_RESULT_ENTITIES}"""


def pick_top_with_ties(rows: List[Tuple[str, float]], limit: int) -> List[Tuple[str, float]]:
    """정렬된 (엔티티, 값) 에서 상위 limit 개 + 경계 동률 포함."""
    if not rows:
        return []
    if len(rows) <= limit:
        return rows
    cutoff = rows[limit - 1][1]
    return [r for i, r in enumerate(rows) if i < limit or r[1] == cutoff]


def compile_evidence_query(entities: Sequence[str], plan: Dict[str, Any]) -> str:
    """결과 엔티티별 근거 트리플: 필터 / 집계 / 반환 경로를 UNION, s-p-o 정확 조인으로 청크."""
    values = _values_clause("?e", entities)
    branches = []

    def branch(uris: List[str], role: str, extra: str, key: str):
        if len(uris) == 1:
            body = f"{values} ?e <{uris[0]}> ?o . BIND(?e AS ?s) BIND(<{uris[0]}> AS ?p) {extra}"
        elif len(uris) == 2:
            body = (f"{values} ?e <{uris[0]}> ?s . FILTER(REGEX(STR(?s), \"{STRUCT_NODE_REGEX}\")) "
                    f"?s <{uris[1]}> ?o . {extra} BIND(?s AS ?mid) BIND(<{uris[1]}> AS ?p)")
        else:
            body = (f"{values} ?e <{uris[0]}> ?mid . FILTER(REGEX(STR(?mid), \"{STRUCT_NODE_REGEX}\")) "
                    f"?mid <{uris[1]}> ?s . FILTER(REGEX(STR(?s), \"{STRUCT_NODE_REGEX}\")) "
                    f"?s <{uris[2]}> ?o . {extra} BIND(<{uris[2]}> AS ?p)")
        if len(uris) >= 2:
            body += (f" OPTIONAL {{ ?est rdf:subject ?e ; rdf:predicate <{uris[0]}> ; "
                     f"rdf:object ?mid ; meta:sourceNodeId ?edgeChunk . }}")
        branches.append(f"  {{ {body} BIND(\"{role}\" AS ?role) BIND(\"{key}\" AS ?path) }}")

    # 같은 구조 항목 한정: 반환 경로가 필터와 같은 부모 구조 노드(경로 접두)를 가지면
    # 그 항목의 필터 조건을 반환 분기에도 건다
    # (style=microservices 인 combines_well_with 항목의 reason 만, score<0 인 then 의 reason 만)
    item_filters: Dict[Tuple[str, ...], List[Tuple[str, Dict[str, Any], int]]] = {}
    for i, f in enumerate(plan["filters"]):
        if f["op"] in ("ne", "not_exists"):
            continue
        extra = ""
        if "values" in f:
            extra = f"FILTER(?o IN ({', '.join(_iri(x['uri']) for x in f['values'])}))"
        elif "numbers" in f or "text" in f:
            extra = _filter_condition(f, "?o", f"e{i}")
        # 동치 경로마다 분기 — ?path 에 실제 키를 바인딩해 리포트에 원래 표기가 보이게
        for alt in _alts(f["path"]):
            if len(alt["uris"]) >= 2 and f["op"] != "exists":
                item_filters.setdefault(tuple(alt["uris"][:-1]), []).append((alt["uris"][-1], f, i))
            branch(alt["uris"], "filter", extra, alt["key"])

    agg = plan.get("aggregate")
    if agg and agg.get("path"):
        extra = ""
        if agg.get("values"):
            extra = f"FILTER(?o IN ({', '.join(_iri(v['uri']) for v in agg['values'])}))"
        for alt in _alts(agg["path"]):
            branch(alt["uris"], "aggregate", extra, alt["key"])

    for j, p in enumerate(plan["returns"]):
        for k, alt in enumerate(_alts(p)):
            extras = []
            # 같은 구조 항목 한정: 자기와 같은 접두를 가진 필터 경로에만 묶인다
            for leaf, f, i in item_filters.get(tuple(alt["uris"][:-1]), []):
                if leaf == alt["uris"][-1]:
                    continue
                fx = f"?fx{j}_{k}_{i}"
                if "values" in f:
                    cond = f"FILTER({fx} IN ({', '.join(_iri(x['uri']) for x in f['values'])}))"
                else:
                    cond = _filter_condition(f, fx, f"r{j}_{k}_{i}")
                extras.append(f"?s <{leaf}> {fx} . {cond}")
            branch(alt["uris"], "return", " ".join(extras), alt["key"])

    if not branches:
        return ""
    union = "\n  UNION\n".join(branches)
    return f"""{_PREFIXES}
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?e ?role ?path ?s ?p ?o ?oLabel ?chunk ?edgeChunk
FROM <urn:x-arq:UnionGraph>
WHERE {{
{union}
  OPTIONAL {{ ?o rdfs:label ?oLabel }}
  OPTIONAL {{
    ?st rdf:subject ?s ; rdf:predicate ?p ; rdf:object ?o ;
        meta:sourceNodeId ?chunk .
  }}
}}
LIMIT 2000"""


# ---------------------------------------------------------------------------
# 5. 결과 해석 / 청크 정렬
# ---------------------------------------------------------------------------

_ROLE_ORDER = {"filter": 0, "aggregate": 1, "return": 2}


def parse_evidence(bindings: List[Dict[str, Any]], entity_order: Sequence[str]) -> List[Dict[str, Any]]:
    """근거 바인딩 → 트리플 (엔티티 순 → 역할 순). 구조 경로는 (엔티티, 'a.b', 값) 으로 평탄화."""
    by_key: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    for b in bindings:
        e, s, p, o = _val(b, "e"), _val(b, "s"), _val(b, "p"), _val(b, "o")
        if not (e and s and p and o):
            continue
        role = _val(b, "role") or "return"
        k = (e, s, p, o)
        t = by_key.get(k)
        if t is None:
            path = _val(b, "path") or local_name(p)
            t = {
                "entity": local_name(e), "entity_uri": e, "role": role,
                "subject": local_name(e), "predicate": path,
                "object": _val(b, "oLabel") or (local_name(o) if o.startswith("http") else o),
                "path": f"out|{path}", "dir": "out",
                "chunk_ids": [], "edge_chunk_ids": [], "s_uri": s, "p_uri": p, "o_uri": o,
            }
            by_key[k] = t
        elif _ROLE_ORDER.get(role, 9) < _ROLE_ORDER.get(t["role"], 9):
            t["role"] = role
        c = _val(b, "chunk")
        if c and c not in t["chunk_ids"]:
            t["chunk_ids"].append(c)
        ec = _val(b, "edgeChunk")
        if ec and ec not in t["edge_chunk_ids"]:
            t["edge_chunk_ids"].append(ec)
    pos = {u: i for i, u in enumerate(entity_order)}
    triples = list(by_key.values())
    triples.sort(key=lambda t: (pos.get(t["entity_uri"], 999), _ROLE_ORDER.get(t["role"], 9), t["predicate"], str(t["object"])))
    return triples


def rank_chunk_ids_grouped(triples: List[Dict[str, Any]], entity_order: Sequence[str]) -> List[Dict[str, Any]]:
    """엔티티별 라운드로빈 — top_k 안에 모든 결과 엔티티의 근거가 들어가도록."""
    per_entity: Dict[str, List[str]] = {}
    support: Dict[str, List[int]] = {}
    edge: Dict[str, List[int]] = {}
    for i, t in enumerate(triples, 1):
        lst = per_entity.setdefault(t["entity_uri"], [])
        for c in t.get("chunk_ids") or []:
            support.setdefault(c, []).append(i)
            if c not in lst:
                lst.append(c)
        for c in t.get("edge_chunk_ids") or []:
            edge.setdefault(c, []).append(i)
    order = [e for e in entity_order if e in per_entity] + [e for e in per_entity if e not in entity_order]
    queues = [list(per_entity[e]) for e in order]
    out, seen = [], set()
    while any(queues):
        for q in queues:
            while q:
                c = q.pop(0)
                if c not in seen:
                    seen.add(c)
                    out.append({"chunk_id": c, "triple_idx": support[c], "kind": "triple"})
                    break
    for c, idx in edge.items():
        if c not in seen:
            seen.add(c)
            out.append({"chunk_id": c, "triple_idx": idx, "kind": "edge"})
    return out


def result_summary(entities: Sequence[str], plan: Dict[str, Any], agg_values: Optional[Dict[str, float]] = None,
                   truncated: bool = False) -> str:
    names = [local_name(e) for e in entities]
    s = plan_summary(plan)
    cond = " AND ".join(s["filters"]) or "(조건 없음)"
    head = f"질의 계획 결과 — 유형 {s['kind']}(전체 {s['kind_members']}개) 중 조건 [{cond}]"
    if plan.get("aggregate") and plan["aggregate"]["fn"] == "count_members":
        return f"{head} 을 만족하는 엔티티 수: {len(names)}{'+' if truncated else ''}개 — {', '.join(names)}"
    if agg_values:
        vals = ", ".join(f"{local_name(e)}={agg_values[e]:g}" for e in entities if e in agg_values)
        return f"{head} 의 {s['aggregate']} 결과: {vals}"
    return f"{head} 을 만족하는 엔티티 전체 {len(names)}{'+' if truncated else ''}개: {', '.join(names) or '없음'}"


# ---------------------------------------------------------------------------
# 6. C 경로(자유 SPARQL) 근거: 바인딩에서 s-p-o 추출
# ---------------------------------------------------------------------------

_SPO_KEYS = [("s", "p", "o"), ("subject", "predicate", "object"), ("s1", "p1", "o1"), ("s2", "p2", "o2")]


def extract_spo_from_bindings(bindings: List[Dict[str, Any]], limit: int = 100) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for b in bindings:
        for ks, kp, ko in _SPO_KEYS:
            s, p, o = _val(b, ks), _val(b, kp), _val(b, ko)
            if s and p and o and s.startswith("http") and p.startswith("http") and o.startswith("http"):
                t = (s, p, o)
                if t not in out:
                    out.append(t)
        if len(out) >= limit:
            break
    return out[:limit]


def build_spo_join_query(spo: Sequence[Tuple[str, str, str]]) -> str:
    rows = " ".join(f"({_iri(s)} {_iri(p)} {_iri(o)})" for s, p, o in spo)
    return f"""{_PREFIXES}
SELECT ?s ?p ?o ?chunk
FROM <urn:x-arq:UnionGraph>
WHERE {{
  VALUES (?s ?p ?o) {{ {rows} }}
  ?st rdf:subject ?s ; rdf:predicate ?p ; rdf:object ?o ; meta:sourceNodeId ?chunk .
}}"""


def build_record_node_chunk_query(uris: Sequence[str]) -> str:
    """노드 기반 청크 조인 — outgoing 관계가 있는 노드(레코드·구조 노드)만 rdf:subject 로.

    공유 값 노드(high, small …)가 문서 전체 청크를 끌어오는 것을 막는다.
    """
    return f"""{_PREFIXES}
SELECT DISTINCT ?target ?chunk
FROM <urn:x-arq:UnionGraph>
WHERE {{
  {_values_clause("?target", uris)}
  FILTER EXISTS {{ ?target ?anyP ?anyO . FILTER(?anyP NOT IN ({_EXCL})) }}
  ?st rdf:subject ?target ; meta:sourceNodeId ?chunk .
}}
LIMIT 200"""


def has_outgoing_query(uri: str) -> str:
    return f"""{_PREFIXES}
ASK FROM <urn:x-arq:UnionGraph> {{ <{uri}> ?p ?o . FILTER(?p NOT IN ({_EXCL})) FILTER(!STRSTARTS(STR(?o), "{STMT_PREFIX}")) }}"""


def triples_view(triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {k: t.get(k) for k in ("subject", "predicate", "object", "chunk_ids", "path", "role", "entity")}
        for t in triples
    ]


__all__ = [
    "build_member_query", "infer_kinds", "build_kind_catalog_query", "parse_kind_catalog",
    "build_plan_messages", "validate_plan", "resolve_value", "plan_summary",
    "compile_member_query", "compile_aggregate_query", "pick_top_with_ties", "compile_evidence_query",
    "parse_evidence", "rank_chunk_ids_grouped", "result_summary",
    "extract_spo_from_bindings", "build_spo_join_query", "build_record_node_chunk_query",
    "has_outgoing_query", "triples_view", "is_struct_node",
]
