"""관계 타게팅(relation_targeting) 단위 테스트.

설계: docs/design-graph-relation-targeting.md
픽스처는 test-ontology(구조화 YAML)의 micro_frontend 실제 카탈로그 일부와
서사형 그래프(스승/제자) 가상 카탈로그다.
"""
from app.services.retrieval.relation_targeting import (
    build_alias_pool,
    build_targeted_query,
    match_paths,
    match_tier,
    parse_triple_bindings,
    rank_chunk_ids,
    render_reasoning_report,
    validate_llm_selection,
)

REL = "http://rag.local/relation/"


def _p(direction, *segs, count=1):
    return {
        "dir": direction, "segments": list(segs), "uris": [REL + s for s in segs],
        "count": count, "example": "", "key": f"{direction}|{'.'.join(segs)}",
    }


STRUCT_CATALOG = [
    _p("out", "testing_complexity"),
    _p("out", "related_patterns"),
    _p("out", "avoid_signals", "team_size"),
    _p("out", "avoid_signals", "simple_crud"),
    _p("out", "prerequisites", "technical", count=3),
    _p("out", "prerequisites", "design", count=2),
    _p("out", "prerequisites", "organizational", "team_size"),
    _p("out", "quality_attributes", "strength", count=6),
    _p("out", "tradeoffs", "pros", count=3),
    _p("out", "tradeoffs", "cons", count=3),
    _p("out", "decision_rules", "if", "team_size"),
]

NARRATIVE_CATALOG = [
    _p("out", "스승"),
    _p("out", "제자"),
    _p("in", "제자"),
    _p("in", "스승"),
    _p("out", "사용"),
]


def _keys(paths):
    return [p["key"] for p in paths]


def test_match_tier_rules():
    assert match_tier("pros", "pros") == 1
    assert match_tier("test complexity", "testing_complexity") == 2
    assert match_tier("avoid", "avoid_signals") == 3
    assert match_tier("of", "tradeoffs") == 0          # 토큰 내부 부분 문자열 금지
    assert match_tier("장점", "pros") == 0
    assert match_tier("스승", "스승") == 1


def test_leaf_match_selects_only_that_path():
    pool = build_alias_pool(["pros", "장점", "advantages", "strengths"], query_text="pros of micro frontend?")
    sel, matches = match_paths(STRUCT_CATALOG, pool, "subject")
    assert _keys(sel) == ["out|tradeoffs.pros"]
    assert matches[0]["alias"] == "pros"


def test_synonym_does_not_pull_unrelated_key():
    # 'strengths' 가 quality_attributes.strength 와 완전일치해도 우선순위 높은 'pros' 만 채택
    pool = build_alias_pool(["장점", "pros", "advantages", "strengths"], query_text="마이크로 프론트엔드의 장점")
    sel, _ = match_paths(STRUCT_CATALOG, pool, "subject")
    assert _keys(sel) == ["out|tradeoffs.pros"]


def test_intermediate_match_expands_subtree():
    sel, matches = match_paths(STRUCT_CATALOG, ["prerequisites"], "subject")
    assert set(_keys(sel)) == {
        "out|prerequisites.technical", "out|prerequisites.design",
        "out|prerequisites.organizational.team_size",
    }
    assert matches[0]["expanded"] is True


def test_stronger_tier_wins_over_earlier_weak_alias():
    sel, _ = match_paths(STRUCT_CATALOG, ["avoid", "avoid_signals"], "subject")
    assert set(_keys(sel)) == {"out|avoid_signals.team_size", "out|avoid_signals.simple_crud"}


def test_no_match_returns_empty():
    sel, matches = match_paths(STRUCT_CATALOG, ["가격", "price", "cost"], "subject")
    assert sel == [] and matches == []


def test_alias_pool_puts_literal_words_first_and_rescues_unresolved_entity():
    pool = build_alias_pool(["benefits", "pros"], None, ["테스트 복잡도"], "pros of X")
    assert pool[0] == "pros"
    assert "테스트 복잡도" in pool


def test_narrative_inverse_only_in_opposite_direction():
    # "성기훈의 스승" (subject): out:스승 + in:스승(방향 불일치 대비) + in:제자(역관계)
    # out:제자 (= 성기훈의 제자) 는 선택되면 안 된다.
    sel, matches = match_paths(NARRATIVE_CATALOG, ["스승", "master"], "subject")
    keys = _keys(sel)
    assert "out|스승" in keys and "in|제자" in keys
    assert "out|제자" not in keys
    assert keys[0].startswith("out|")                   # 역할 방향 우선
    assert any(m["inverse"] for m in matches)


def test_targeted_query_joins_exact_statement():
    q = build_targeted_query("http://rag.local/inst/micro_frontend", [STRUCT_CATALOG[8]])
    assert "rdf:subject ?s ; rdf:predicate ?p ; rdf:object ?o" in q
    assert "<http://rag.local/relation/tradeoffs>" in q and "<http://rag.local/relation/pros>" in q


def _b(**kv):
    return {k: {"value": v} for k, v in kv.items()}


def test_parse_and_rank_chunks_by_linkage():
    inst = "http://rag.local/inst/"
    bindings = [
        _b(path="out|tradeoffs.pros", s=inst + "root_0_tradeoffs_22", p=REL + "pros", o=inst + "a",
           oLabel="A", chunk="d::struct::root_0_tradeoffs_22", edgeChunk="d::struct::micro_frontend"),
        _b(path="out|tradeoffs.pros", s=inst + "root_0_tradeoffs_22", p=REL + "pros", o=inst + "b",
           oLabel="B", chunk="d::struct::root_0_tradeoffs_22"),
        _b(path="out|testing_complexity", s=inst + "micro_frontend", p=REL + "testing_complexity",
           o=inst + "high", chunk="d::struct::micro_frontend"),
    ]
    triples = parse_triple_bindings(bindings, "micro_frontend")
    assert [t["predicate"] for t in triples] == ["tradeoffs.pros", "tradeoffs.pros", "testing_complexity"]
    assert triples[0]["subject"] == "micro_frontend"       # 구조 경로 평탄화
    ranked = rank_chunk_ids(triples)
    assert ranked[0]["chunk_id"].endswith("root_0_tradeoffs_22")
    assert ranked[0]["triple_idx"] == [1, 2]
    assert ranked[1]["chunk_id"].endswith("micro_frontend")


def test_llm_selection_validated_against_catalog():
    items = STRUCT_CATALOG[:3]
    mode, picked, _ = validate_llm_selection({"mode": "targeted", "paths": [1, 99, "x"]}, items)
    assert mode == "targeted" and picked == [items[1]]
    mode, picked, _ = validate_llm_selection({"mode": "targeted", "paths": [99]}, items)
    assert mode == "none" and picked == []
    assert validate_llm_selection(None, items)[0] == "none"


def test_report_avoids_flag_words():
    report = render_reasoning_report({
        "analysis": {"intent": "attribute", "entities": ["micro frontend"], "relation_aliases": ["pros"]},
        "linking": [{"entity": "micro frontend", "uri": "http://rag.local/inst/micro_frontend"}],
        "targeting": {"mode": "none", "catalog_size": 39, "reason": "일치 경로 없음"},
        "triples": [], "chunks": [],
    })
    text = "\n".join(report).lower()
    assert "1/5" in text and "5/5" in text
    for w in ("error", "failed", "fallback"):
        assert w not in text


def test_builders_accept_equivalent_anchor_set():
    from app.services.retrieval import relation_targeting as rt
    a = ["http://rag.local/inst/볼츠만", "http://rag.local/inst/루트비히_볼츠만"]
    cat = rt.build_catalog_query(a)
    assert cat.count("VALUES ?anchor { <http://rag.local/inst/볼츠만> <http://rag.local/inst/루트비히_볼츠만> }") == 4
    assert "?anchor ?p0 ?o" in cat
    q = rt.build_targeted_query(a, [{"uris": ["http://rag.local/rel/소속"], "key": "out:소속", "dir": "out"}])
    assert "VALUES ?anchor" in q and "BIND(?anchor AS ?s)" in q
    # 단일 앵커는 기존과 같은 형태
    assert "VALUES" not in rt.build_catalog_query(a[0])
    pq = rt.build_pair_query(a, "http://rag.local/inst/빈_대학")
    assert "VALUES ?anchorA" in pq and "BIND(?anchorA AS ?s) BIND(<http://rag.local/inst/빈_대학> AS ?o)" in pq
