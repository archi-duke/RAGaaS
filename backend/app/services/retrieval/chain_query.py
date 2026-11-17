"""다단계 질문 — 홉별 결정적 체인 검색 (mode H)

설계: docs/design/graph/design-graph-multihop-chain.md

"광전효과를 처음 발견한 사람의 박사 지도교수가 1847년에 제안한 법칙은?" 같은 질문을
LLM 이 SPARQL 을 통째로 짓는 대신(C, 실패가 잦고 느림),
  1. LLM 1회: 질문을 체인 계획으로 분해 — 시작 엔티티 + 홉마다 관계(KB 관계 어휘 닫힌 집합)·방향
  2. 검증: 관계는 어휘에 실재하는 것만, 홉 ≤ MAX_HOPS
  3. 실행(결정적): 시작 URI → 홉마다 VALUES 프론티어 + 관계 고정 SPARQL → 다음 프론티어
     · 0건이면 같은 관계 반대 방향으로 한 번 더 (추출 방향 뒤바뀜 대비)
  4. 모든 홉의 트리플과 s-p-o 정확 일치 근거 청크를 모아 답변 컨텍스트로
연도·국적 같은 조건은 SPARQL 필터로 걸지 않는다 — 후보를 모두 모으고, 근거 청크로 답변 LLM 이 고른다.
"""

import re
import urllib.parse
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.retrieval.relation_targeting import (
    _PREFIXES,
    _TAIL,
    _iri,
    local_name,
    parse_triple_bindings,
)

REL_NS = "http://rag.local/rel/"
MAX_HOPS = 6            # 기본 최대 홉 (그래프 스테이지 Max Hop 옵션이 없을 때)
MAX_HOPS_CAP = 8        # 옵션으로도 넘을 수 없는 상한 (홉마다 후보가 불어나 지연·잡음)


def resolve_max_hops(params: Dict[str, Any]) -> int:
    """그래프 스테이지 옵션 → 최대 홉. max_hops 우선, 옛 설정(is_auto_hops=false 면 hops) 호환."""
    v = params.get("max_hops")
    if v is None and params.get("is_auto_hops") is False:
        v = params.get("hops")
    try:
        v = int(v) if v is not None else MAX_HOPS
    except (TypeError, ValueError):
        v = MAX_HOPS
    return max(1, min(v, MAX_HOPS_CAP))
MAX_FRONTIER = 15
MAX_HOP_TRIPLES = 120
MAX_VOCAB = 80


def _compact(x: str) -> str:
    return re.sub(r"[\s_\-]", "", str(x or "")).lower()


# ---------------------------------------------------------------------------
# 1. 관계 어휘
# ---------------------------------------------------------------------------

def build_vocab_query() -> str:
    return """SELECT ?p (COUNT(*) AS ?n) WHERE {
  GRAPH ?g { ?s ?p ?o }
  FILTER(STRSTARTS(STR(?g), "urn:doc:"))
  FILTER(STRSTARTS(STR(?p), "http://rag.local/rel/"))
  FILTER(!CONTAINS(STR(?p), "/inverse_"))
} GROUP BY ?p ORDER BY DESC(?n) LIMIT 300"""


def build_vocab(bindings: List[Dict[str, Any]], schema_props: Optional[List[Dict[str, Any]]] = None
                ) -> List[Dict[str, Any]]:
    """그래프 관계(건수) + 승격 스키마의 정의·방향. 스키마 속성은 건수와 무관하게 앞에."""
    counts: Dict[str, int] = {}
    for b in bindings:
        name = urllib.parse.unquote(b["p"]["value"].rsplit("/", 1)[-1])
        counts[name] = int(b["n"]["value"])
    vocab: List[Dict[str, Any]] = []
    seen = set()
    for p in schema_props or []:
        n = p.get("name")
        if n and n in counts and n not in seen:
            vocab.append({"name": n, "count": counts[n], "description": p.get("description") or "",
                          "domain": p.get("domain") or "", "range": p.get("range") or ""})
            seen.add(n)
    for n, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        if len(vocab) >= MAX_VOCAB:
            break
        if n not in seen and c >= 2:
            vocab.append({"name": n, "count": c, "description": "", "domain": "", "range": ""})
            seen.add(n)
    return vocab


# ---------------------------------------------------------------------------
# 2. 체인 계획 (LLM 1회)
# ---------------------------------------------------------------------------

def build_plan_messages(question: str, vocab: List[Dict[str, Any]], max_hops: int = MAX_HOPS) -> List[Dict[str, str]]:
    lines = []
    for v in vocab:
        dr = f" ({v['domain'] or '?'} → {v['range'] or '?'})" if (v["domain"] or v["range"]) else ""
        desc = f": {v['description']}" if v["description"] else ""
        lines.append(f"- {v['name']}{dr}{desc} [{v['count']}건]")
    user = f"""질문을 지식 그래프의 관계 체인으로 분해하라.

[관계 어휘 — 이 이름만 쓴다. 트리플은 '주어 —관계→ 목적어' 방향이다]
{chr(10).join(lines)}

질문: {question}

규칙:
1. start: 체인의 출발 엔티티 — 질문에 이름이 직접 나온 고유명 하나 (예: '광전효과', '패러데이').
2. hops: 출발점에서 답까지 따라갈 관계를 순서대로 (최대 {max_hops}개).
   - relations: 그 홉에서 쓸 관계 이름 1~3개 (같은 뜻 후보). 위 어휘에 있는 이름만.
   - direction: 현재 노드가 주어면 "out", 목적어면 "in".
     예) "X를 발견한 사람" = X 가 목적어 → {{"relations": ["발견함"], "direction": "in"}}
     예) "A의 지도교수" 에서 관계가 '스승 → 제자' 방향이면 A 는 목적어 → "in"
   - expect: 이 홉에서 얻는 대상 설명 (예: "인물", "1847년에 제안된 법칙"). 연도·국적 같은 조건은 여기에만 적는다.
3. 마지막 노드에 대해 여러 가지를 묻는다면(예: "어떤 원리를 제안했고 몇 년에 상을 받았나") 마지막 홉 다음에
   final_relations 로 그 노드에서 더 볼 관계들을 적는다 (방향 포함).
   "…은 무엇이며, 누가 (몇 년에) 제안했는가" 처럼 마지막 노드를 만든 주체를 물으면, 마지막 노드가 목적어이므로
   {{"relation": "제안함", "direction": "in"}} 처럼 direction=in. 연도는 관계(진술)에 붙어 있으니 따로 관계를 찾지 않는다.
4. 체인으로 표현할 수 없는 질문(같은 해 비교, 기간 계산 등)이면 {{"chainable": false}}.
JSON 만: {{"chainable": true, "start": "...", "hops": [{{"relations": [...], "direction": "out|in", "expect": "..."}}],
 "final_relations": [{{"relation": "...", "direction": "out|in"}}]}}"""
    return [
        {"role": "system", "content": "You decompose multi-hop questions into relation chains over a given closed vocabulary. Output JSON only."},
        {"role": "user", "content": user},
    ]


def is_lineage_relation(v: Optional[Dict[str, Any]]) -> bool:
    """domain 과 range 가 같은 비인물 관계 (계승_발전, 일반화함, 근사_극한 …).

    이런 관계는 이름의 자연스러운 읽기와 정의 방향이 엇갈려 추출 그래프에 양방향이 섞여 있다
    (예: '민코프스키_시공간 —계승_발전→ 특수_상대론'). 처음부터 양방향을 조회하고, 어느 쪽이
    맞는지는 근거 청크로 답변 LLM 이 판단한다. 인물→인물(지도교수_of)은 방향이 뜻을 가르므로 제외.
    """
    if not v:
        return False
    from app.services.retrieval.entity_linking import _is_person_type
    dom, rng = (v.get("domain") or "").strip(), (v.get("range") or "").strip()
    return bool(dom) and dom == rng and not _is_person_type([dom])


def validate_plan(data: Optional[Dict[str, Any]], vocab: List[Dict[str, Any]],
                  max_hops: int = MAX_HOPS) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """어휘에 없는 관계는 버린다. 쓸 관계가 없는 홉이 있으면 계획 무효."""
    notes: List[str] = []
    if not data or data.get("chainable") is False:
        return None, ["체인으로 분해할 수 없는 질문"]
    names = {_compact(v["name"]): v["name"] for v in vocab}
    by_name = {v["name"]: v for v in vocab}
    start = str(data.get("start") or "").strip()
    if not start:
        return None, ["출발 엔티티 없음"]
    hops = []
    raw_hops = data.get("hops") or [] if isinstance(data, dict) else []
    if len(raw_hops) > max_hops:
        notes.append(f"계획 {len(raw_hops)}홉 → 최대 홉 설정 {max_hops} 에서 자름 (답이 그 너머에 있으면 찾지 못함)")
    for i, h in enumerate(raw_hops[:max_hops], 1):
        rels = []
        for r in h.get("relations") or []:
            n = names.get(_compact(r))
            if n:
                rels.append(n)
            else:
                notes.append(f"홉{i} 관계 '{r}' 는 어휘에 없음 — 제외")
        if not rels:
            return None, notes + [f"홉{i} 에 쓸 수 있는 관계 없음"]
        d = h.get("direction") if h.get("direction") in ("out", "in") else "out"
        rels = list(dict.fromkeys(rels))[:3]
        hops.append({"relations": rels, "direction": d, "expect": str(h.get("expect") or "")[:80],
                     "both": all(is_lineage_relation(by_name.get(r)) for r in rels)})
    if not hops:
        return None, notes + ["홉 없음"]
    finals = []
    for f in (data.get("final_relations") or [])[:3]:
        n = names.get(_compact((f or {}).get("relation")))
        if n:
            finals.append({"relations": [n], "direction": f.get("direction") if f.get("direction") in ("out", "in") else "out",
                           "expect": "마지막 노드의 추가 속성", "final": True})
    return {"start": start, "hops": hops, "finals": finals}, notes


# ---------------------------------------------------------------------------
# 3. 홉 실행 SPARQL
# ---------------------------------------------------------------------------

def build_hop_query(frontier: Sequence[str], relations: Sequence[str], direction: str, tag: str) -> str:
    """프론티어(현재 노드들)에서 지정 관계로 한 홉. direction=out: 노드가 주어, in: 노드가 목적어."""
    nodes = " ".join(_iri(u) for u in frontier)
    # 관계 이름은 그래프에서 읽은 실제 이름(어휘 검증 통과)이라 URI 에 그대로 쓴다 (데이터 URI 가 비인코딩)
    preds = " ".join(f"<{REL_NS}{r}>" for r in relations if not re.search(r"[<>\"\s{}|^`\\]", r))
    anchor_var = "?s" if direction == "out" else "?o"
    return f"""{_PREFIXES}
SELECT DISTINCT ?path ?s ?p ?o ?sLabel ?oLabel ?chunk
FROM <urn:x-arq:UnionGraph>
WHERE {{
  VALUES {anchor_var} {{ {nodes} }}
  VALUES ?p {{ {preds} }}
  ?s ?p ?o .
  BIND("{tag}" AS ?path)
{_TAIL}
}}
LIMIT {MAX_HOP_TRIPLES}"""


def next_frontier(triples: List[Dict[str, Any]], direction: str,
                  frontier: Optional[Sequence[str]] = None, visited: Optional[set] = None) -> List[str]:
    """홉 결과에서 다음 노드 (리소스만, 등장 순, 상한).

    frontier 가 주어지면 트리플에서 프론티어가 아닌 쪽 끝을 다음 노드로 삼는다 (양방향 홉 대응).
    visited(이미 거친 노드)는 제외 — 홉2 에서 출발점으로 되돌아오는 순환 방지.
    """
    out: List[str] = []
    fset = set(frontier or [])
    seen = set(visited or ())
    for t in triples:
        if fset:
            if t["s_uri"] in fset and t["o_uri"] not in fset:
                u = t["o_uri"]
            elif t["o_uri"] in fset and t["s_uri"] not in fset:
                u = t["s_uri"]
            else:
                continue
        else:
            u = t["o_uri"] if direction == "out" else t["s_uri"]
        if u.startswith("http://rag.local/inst/") and u not in out and u not in seen:
            out.append(u)
        if len(out) >= MAX_FRONTIER:
            break
    return out


def parse_hop(bindings: List[Dict[str, Any]], hop_no: int) -> List[Dict[str, Any]]:
    triples = parse_triple_bindings(bindings, "")
    for t in triples:
        t["hop"] = hop_no
    return triples


def order_chunks_by_hop(triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """홉별로 번갈아 청크를 고른다 — top_k 안에 모든 홉의 근거가 들어가도록."""
    per_hop: Dict[int, List[Tuple[str, List[int]]]] = {}
    idx_of: Dict[str, List[int]] = {}
    for i, t in enumerate(triples, 1):
        for c in t.get("chunk_ids") or []:
            idx_of.setdefault(c, []).append(i)
            lst = per_hop.setdefault(t.get("hop", 0), [])
            if c not in [x for x, _ in lst]:
                lst.append((c, []))
    out, seen = [], set()
    hops = sorted(per_hop)
    pos = {h: 0 for h in hops}
    while any(pos[h] < len(per_hop[h]) for h in hops):
        for h in hops:
            while pos[h] < len(per_hop[h]):
                c, _ = per_hop[h][pos[h]]
                pos[h] += 1
                if c not in seen:
                    seen.add(c)
                    out.append({"chunk_id": c, "triple_idx": idx_of[c], "kind": "triple"})
                    break
    return out


def hop_label(h: Dict[str, Any], n_from: int, n_triples: int, n_next: int, flipped: bool) -> str:
    arrow = "↔" if h.get("both") else ("→" if h["direction"] == "out" else "←")
    kind = "추가 속성" if h.get("final") else f"홉{h['no']}"
    flip = " (반대 방향으로 재시도해 찾음)" if flipped else ""
    exp = f" — 기대: {h['expect']}" if h.get("expect") else ""
    return (f"{kind}: 노드 {n_from}개 {arrow}[{'|'.join(h['relations'])}]{arrow} 트리플 {n_triples}건,"
            f" 다음 노드 {n_next}개{flip}{exp}")


def frontier_names(uris: Sequence[str], limit: int = 8) -> str:
    names = [local_name(u).replace("_", " ") for u in uris[:limit]]
    return ", ".join(names) + (f" 외 {len(uris) - limit}" if len(uris) > limit else "")


# ---------------------------------------------------------------------------
# 4. 끊긴 홉 재선택 — 프론티어 노드에 실제로 달린 관계 중에서 LLM 이 고른다 (1회)
# ---------------------------------------------------------------------------

def build_frontier_relations_query(frontier: Sequence[str]) -> str:
    nodes = " ".join(_iri(u) for u in frontier)
    return f"""SELECT ?p ?dir (COUNT(*) AS ?n) (SAMPLE(?x) AS ?ex) WHERE {{
  VALUES ?node {{ {nodes} }}
  {{ GRAPH ?g {{ ?node ?p ?x }} BIND("out" AS ?dir) }}
  UNION
  {{ GRAPH ?g {{ ?x ?p ?node }} BIND("in" AS ?dir) }}
  FILTER(STRSTARTS(STR(?g), "urn:doc:"))
  FILTER(STRSTARTS(STR(?p), "{REL_NS}"))
  FILTER(!CONTAINS(STR(?p), "/inverse_"))
}} GROUP BY ?p ?dir ORDER BY DESC(?n) LIMIT 40"""


def parse_frontier_relations(bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for b in bindings:
        name = urllib.parse.unquote(b["p"]["value"].rsplit("/", 1)[-1])
        if re.search(r"[<>\"\s{}|^`\\]", name):
            continue
        ex = b.get("ex", {}).get("value", "")
        out.append({"relation": name, "direction": b["dir"]["value"], "count": int(b["n"]["value"]),
                    "example": local_name(ex) if ex.startswith("http") else ex[:40]})
    return out


def build_repick_messages(question: str, hop: Dict[str, Any], frontier_label: str,
                          options: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    lines = [f"{i}. {o['relation']} ({'현재 노드가 주어' if o['direction'] == 'out' else '현재 노드가 목적어'}, "
             f"{o['count']}건, 예: {o['example']})" for i, o in enumerate(options, 1)]
    user = f"""다단계 질문의 체인이 한 홉에서 끊겼다. 현재 노드에 실제로 달린 관계 중에서 이 홉을 대신할 것을 골라라.

질문: {question}
현재 노드: {frontier_label}
계획했던 관계: {', '.join(hop['relations'])} — 기대: {hop.get('expect') or '-'}

현재 노드의 실제 관계:
{chr(10).join(lines)}

같은 사실을 다른 이름·방향으로 담은 관계만 고른다 (최대 3개). 맞는 것이 없으면 빈 목록.
JSON 만: {{"picks": [번호, ...], "reason": "..."}}"""
    return [
        {"role": "system", "content": "You repair a broken hop in a knowledge-graph relation chain. Output JSON only."},
        {"role": "user", "content": user},
    ]


def validate_repick(data: Optional[Dict[str, Any]], options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    picks = []
    for x in (data or {}).get("picks") or []:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(options) and options[i - 1] not in picks:
            picks.append(options[i - 1])
    return picks[:3]
