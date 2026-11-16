"""P2: query_plan — 클라이언트 에이전트가 쓴 질의 계획을 검증·컴파일·실행 (LLM 없음).

docs/design-mcp-agent-query.md §4.4

계획:
  {"kind": "ArchitectureStyle",
   "where": {"all": [ {"any": [leaf, leaf]}, leaf ]},     # all=AND, any=OR, leaf={"path", "op", "value"}
   "return": ["has_positive_effect_on", ...],
   "aggregate": {"fn": "count|max|min|count_members", "path": key, "value", "order", "limit", "having"},
   "rank_by": "matched" | null, "limit": 50, "include_evidence": true}

실행 방식:
  - 조건 트리를 DNF(OR of AND)로 펼친다. 각 AND 묶음은 기존 validate_plan + compile_member_query 로 한 질의 —
    구조화 KB 의 '같은 목록 항목' 조건(공유 구조 노드)이 컴파일러 안에서 지켜진다.
  - 묶음 결과의 합집합이 최종 엔티티. 조건(leaf)마다 따로 조회해 엔티티별 충족 조건 수(matched)를 센다.
  - 내부 검색과 달리 AND 결과가 0이어도 OR 로 **완화하지 않는다** — 논리는 에이전트가 정한다. zero 로 정직하게 보고.
"""
from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

MAX_LEAVES = 12
MAX_CONJUNCTIONS = 16
MAX_LIMIT = 200


class PlanError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 조건 트리 → DNF
# ---------------------------------------------------------------------------

def _is_leaf(node: Any) -> bool:
    return isinstance(node, dict) and "path" in node and "op" in node


def to_dnf(node: Any) -> List[List[Dict[str, Any]]]:
    """조건 트리 → [[leaf, ...] (AND), ...] (OR). 빈 트리는 [[]] (조건 없음)."""
    if node is None or node == {} or node == []:
        return [[]]
    if _is_leaf(node):
        return [[node]]
    if isinstance(node, list):            # 맨 리스트는 all 로 본다
        node = {"all": node}
    if not isinstance(node, dict):
        raise PlanError(f"조건 형식 오류: {str(node)[:120]}")
    keys = [k for k in ("all", "any") if k in node]
    if len(keys) != 1 or len(node) != 1:
        raise PlanError(f"조건 노드는 all / any / leaf(path·op·value) 중 하나여야 함: {str(node)[:120]}")
    kids = node[keys[0]]
    if not isinstance(kids, list) or not kids:
        raise PlanError(f"{keys[0]} 에는 조건 목록이 필요함")
    parts = [to_dnf(k) for k in kids]
    if keys[0] == "any":
        out = [conj for p in parts for conj in p]
    else:
        out = []
        for combo in itertools.product(*parts):
            out.append([leaf for conj in combo for leaf in conj])
            if len(out) > MAX_CONJUNCTIONS:
                break
    if len(out) > MAX_CONJUNCTIONS:
        raise PlanError(f"조건 조합이 너무 많음 (OR 펼침 {MAX_CONJUNCTIONS}개 초과) — any 를 줄이거나 path 배열·op=in 을 쓸 것")
    return out


def _leaf_key(leaf: Dict[str, Any]) -> str:
    import json
    return json.dumps({"path": leaf.get("path"), "op": str(leaf.get("op", "")).lower(), "value": leaf.get("value")},
                      ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def _label_map_query(uris: Sequence[str]) -> str:
    vals = " ".join(f"<{u}>" for u in uris)
    return f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?e (SAMPLE(?l) AS ?label) FROM <urn:x-arq:UnionGraph> WHERE {{ VALUES ?e {{ {vals} }} OPTIONAL {{ ?e rdfs:label ?l }} }} GROUP BY ?e"""


async def run_plan(kb_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.agent_query.catalog import load_catalog
    from app.services.retrieval import class_query as cq
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend

    t0 = time.time()
    _kb, kinds, catalogs, version = await load_catalog(kb_id)
    fb = FusekiBackend()

    async def q(sparql: str):
        return await asyncio.to_thread(fb._bindings, kb_id, sparql)

    def fail(status: str, message: str, **extra) -> Dict[str, Any]:
        return {"status": status, "message": message, "schema_version": version,
                "stale_schema": bool(body.get("schema_version")) and body.get("schema_version") != version,
                "elapsed_ms": int((time.time() - t0) * 1000), **extra}

    kind = body.get("kind")
    if not kind and len(kinds) == 1:
        kind = kinds[0]["name"]
    if not any(k["name"] == kind for k in kinds):
        return fail("reject", f"kind '{kind}' 가 없음. describe 의 kinds 중 하나: {[k['name'] for k in kinds]}")
    try:
        dnf = to_dnf(body.get("where"))
    except PlanError as e:
        return fail("reject", str(e))
    leaves: Dict[str, Dict[str, Any]] = {}
    for conj in dnf:
        if len(conj) > cq.MAX_FILTERS:
            return fail("reject", f"한 AND 묶음의 조건이 {len(conj)}개 — 최대 {cq.MAX_FILTERS}개. "
                                  "같은 경로의 여러 값은 op=in, 여러 경로의 같은 값은 path 배열로 줄일 것")
        for leaf in conj:
            leaves.setdefault(_leaf_key(leaf), leaf)
    if len(leaves) > MAX_LEAVES:
        return fail("reject", f"조건이 {len(leaves)}개 — 최대 {MAX_LEAVES}개")

    returns = [r for r in (body.get("return") or []) if isinstance(r, (str, list))]
    agg = body.get("aggregate") if isinstance(body.get("aggregate"), dict) else None
    try:
        limit = max(1, min(int(body.get("limit") or 50), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = 50

    def validate(filters, with_extras=True):
        data = {"mode": "plan", "kind": kind, "filters": filters,
                "return": returns if with_extras else [], "aggregate": agg if with_extras else None}
        if not filters and not with_extras:
            return None
        return cq.validate_plan(data, kinds, catalogs, strict=True)

    # 1) 묶음별 검증 — reject 는 전체 반려 (조건을 버리면 결과가 넓어져 오답)
    conj_plans: List[Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]] = []
    zero_notes: List[str] = []
    adjustments: List[str] = []
    for conj in dnf:
        checked = validate(conj)
        st = checked["status"]
        if st == "reject":
            return fail("reject", f"{checked['message']} — 조건 {[_leaf_key(l) for l in conj]}")
        if st in ("unsupported", "none"):
            return fail("reject", checked.get("message") or st)
        if st == "zero":
            zero_notes.append(checked.get("message") or "값이 목록에 없음")
            conj_plans.append((conj, None))
            continue
        adjustments.extend(checked.get("adjustments") or [])
        conj_plans.append((conj, checked["plan"]))
    adjustments = list(dict.fromkeys(adjustments))

    # 2) 묶음별 실행 → 합집합
    sparqls: List[str] = []
    entities: List[str] = []
    ent_conj: Dict[str, List[int]] = {}
    for i, (conj, plan) in enumerate(conj_plans):
        if plan is None:
            continue
        if not plan["filters"]:
            # 조건 없음 — 유형 멤버 전체
            kinfo = next(k for k in kinds if k["name"] == kind)
            got = list(kinfo["members"])
        else:
            sp = cq.compile_member_query(plan)
            sparqls.append(f"# 조건 묶음 {i + 1}\n{sp}")
            got = [cq._val(b, "e") for b in await q(sp) if cq._val(b, "e")]
        for e in got:
            if e not in ent_conj:
                entities.append(e)
            ent_conj.setdefault(e, []).append(i)

    # 3) 조건별 충족 수 (순위·설명용) — 조건이 2개 이상일 때만
    matched: Dict[str, List[str]] = {e: [] for e in entities}
    leaf_status: List[Dict[str, Any]] = []
    if len(leaves) >= 2 and entities:
        for lk, leaf in leaves.items():
            chk = validate([leaf], with_extras=False)
            if not chk or chk["status"] != "ok":
                leaf_status.append({"condition": leaf, "status": chk["status"] if chk else "skip",
                                    "message": (chk or {}).get("message")})
                continue
            sp = cq.compile_member_query({**chk["plan"], "filters": chk["plan"]["filters"]})
            hit = {cq._val(b, "e") for b in await q(sp)}
            leaf_status.append({"condition": leaf, "status": "ok", "entities": len(hit)})
            for e in entities:
                if e in hit:
                    matched[e].append(lk)
    elif len(leaves) == 1:
        lk = next(iter(leaves))
        for e in entities:
            matched[e].append(lk)

    # 4) 집계 (첫 유효 묶음의 검증된 집계 사용)
    agg_values: Optional[Dict[str, float]] = None
    vplan = next((p for _c, p in conj_plans if p is not None), None)
    if vplan and vplan.get("aggregate") and entities:
        a = vplan["aggregate"]
        if a["fn"] == "count_members":
            agg_values = None
        else:
            sp = cq.compile_aggregate_query(entities, a)
            sparqls.append(f"# 집계\n{sp}")
            rows = []
            for b in await q(sp):
                try:
                    rows.append((cq._val(b, "e"), float(cq._val(b, "agg") or 0)))
                except ValueError:
                    continue
            if a.get("having"):
                op, val = a["having"]["op"], a["having"]["value"]
                cmp = {"gte": lambda x: x >= val, "gt": lambda x: x > val, "lte": lambda x: x <= val,
                       "lt": lambda x: x < val, "eq": lambda x: x == val}[op]
                rows = [r for r in rows if cmp(r[1])]
                rows.sort(key=lambda r: -r[1] if a.get("order") != "asc" else r[1])
            else:
                rows = cq.pick_top_with_ties(rows, a["limit"])
            entities = [e for e, _ in rows]
            agg_values = dict(rows)

    # 5) 순위: 충족 조건 수 → 집계값 → 원래 순서
    pos = {e: i for i, e in enumerate(entities)}
    if body.get("rank_by") == "matched" or (len(leaves) >= 2 and not agg_values):
        entities.sort(key=lambda e: (-len(matched.get(e, [])), pos[e]))
    total = len(entities)
    entities = entities[:limit]

    # 6) 근거 트리플 (묶음별, 그 묶음을 만족한 엔티티만) + 반환 경로
    triples: List[Dict[str, Any]] = []
    if body.get("include_evidence", True) and entities:
        seen = set()
        for i, (conj, plan) in enumerate(conj_plans):
            if plan is None:
                continue
            ents = [e for e in entities if i in ent_conj.get(e, [])]
            if not ents:
                continue
            sp = cq.compile_evidence_query(ents, plan)
            if not sp:
                continue
            for t in cq.parse_evidence(await q(sp), ents):
                k = (t["entity_uri"], t["predicate"], str(t["object"]))
                if k not in seen:
                    seen.add(k)
                    triples.append(t)
        if not any(p for _c, p in conj_plans if p is not None and p["filters"]) and vplan:
            sp = cq.compile_evidence_query(entities, vplan)
            if sp:
                triples.extend(cq.parse_evidence(await q(sp), entities))

    # 7) 라벨
    labels: Dict[str, str] = {}
    for i in range(0, len(entities), 200):
        for b in await q(_label_map_query(entities[i:i + 200])):
            if cq._val(b, "label"):
                labels[cq._val(b, "e")] = cq._val(b, "label")
    name = lambda u: labels.get(u) or cq.local_name(u).replace("_", " ")

    by_ent: Dict[str, List[Dict[str, Any]]] = {}
    for t in triples:
        by_ent.setdefault(t["entity_uri"], []).append(t)
    # 응답 크기 (클라이언트 토큰): compact = (p, o) 별로 묶어 청크 ID 합침 / full = 원래 트리플 / none
    mode = str(body.get("evidence") or "compact").lower()
    leaf_keys = list(leaves)
    out_entities = []
    for e in entities:
        ts = by_ent.get(e, [])
        values: Dict[str, List[str]] = {}
        grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for t in ts:
            o = str(t["object"])
            values.setdefault(t["predicate"], [])
            if o not in values[t["predicate"]]:
                values[t["predicate"]].append(o)
            g = grouped.setdefault((t["predicate"], o), {"p": t["predicate"], "o": o, "chunk_ids": []})
            for c in t["chunk_ids"] + list(t.get("edge_chunk_ids") or []):
                if c not in g["chunk_ids"]:
                    g["chunk_ids"].append(c)
        item: Dict[str, Any] = {
            "label": name(e),
            "matched": len(matched.get(e, [])),
            "matched_conditions": [leaf_keys.index(k) for k in matched.get(e, [])],   # conditions 의 번호
            **({"aggregate": agg_values.get(e)} if agg_values else {}),
        }
        if mode == "full":
            item["values"] = values
            item["evidence"] = [{"s": name(e), "p": t["predicate"], "o": str(t["object"]), "role": t["role"],
                                 "chunk_ids": t["chunk_ids"] + [c for c in t.get("edge_chunk_ids", []) if c not in t["chunk_ids"]]}
                                for t in ts]
        elif mode != "none":
            item["evidence"] = list(grouped.values())      # values 는 evidence 의 p·o 로 충분
        out_entities.append(item)

    status = "ok" if out_entities else "zero"
    if vplan and (vplan.get("aggregate") or {}).get("fn") == "count_members":
        out_count = total
    else:
        out_count = None
    return {
        "status": status,
        "schema_version": version,
        "stale_schema": bool(body.get("schema_version")) and body.get("schema_version") != version,
        "kind": kind,
        "total": total,
        **({"count": out_count} if out_count is not None else {}),
        "entities": out_entities,
        "conditions": leaf_status or [{"condition": leaves[k], "status": "ok"} for k in leaf_keys],
        "zero_conditions": zero_notes,
        "adjustments": adjustments + ([f"결과 {total}개 중 {limit}개만 반환"] if total > limit else []),
        "message": None if out_entities else (
            "조건을 만족하는 엔티티 없음" + (f" — 값 확인 필요: {'; '.join(zero_notes)} (lookup_values 로 표기 확인)"
                                     if zero_notes else " — AND 를 any 로 풀거나 조건을 줄여 보세요 (자동 완화하지 않음)")),
        "sparql": "\n\n".join(sparqls),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
