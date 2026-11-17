"""유형 수준 질문(class_query) 단위 테스트.

설계: docs/design/graph/design-graph-class-query.md
픽스처: 아키텍처 스타일 3개(rdf:type 없음)의 멤버 시그니처와 경로 카탈로그.
"""
from app.services.retrieval.class_query import (
    compile_aggregate_query,
    compile_evidence_query,
    compile_member_query,
    extract_spo_from_bindings,
    infer_kinds,
    parse_evidence,
    parse_kind_catalog,
    pick_top_with_ties,
    rank_chunk_ids_grouped,
    resolve_value,
    result_summary,
    validate_plan,
)
from app.services.retrieval.relation_targeting import render_reasoning_report

INST = "http://rag.local/inst/"
REL = "http://rag.local/relation/"


def _b(**kv):
    return {k: {"value": v} for k, v in kv.items()}


def _members():
    preds = " ".join(REL + p for p in ("label", "testing_complexity", "tradeoffs", "avoid_signals"))
    return [
        _b(e=INST + "micro_frontend", preds=preds),
        _b(e=INST + "microservices", preds=preds + " " + REL + "fit_signals"),
        _b(e=INST + "layered", preds=preds),
        _b(e=INST + "lonely_value_like", preds=REL + "label"),   # 단독 + predicate 1개 → 유형 제외
    ]


def _catalog():
    rows = []
    for e, v in (("micro_frontend", "high"), ("microservices", "high"), ("layered", "low")):
        rows.append(_b(p0=REL + "testing_complexity", v=INST + v, vLabel=v, ne="1"))
    rows.append(_b(p0=REL + "testing_complexity", v=INST + "high", vLabel="high", ne="2"))
    rows.append(_b(p0=REL + "avoid_signals", p1=REL + "team_size", v=INST + "small", vLabel="small", ne="2"))
    for i in range(20):
        rows.append(_b(p0=REL + "tradeoffs", p1=REL + "pros", v=INST + f"pro_{i}", vLabel=f"장점 {i}", ne="1"))
    rows.append(_b(p0=REL + "decision_rules", p1=REL + "then", p2=REL + "score", v=INST + "_3", vLabel="-3", ne="1"))
    rows.append(_b(p0=REL + "decision_rules", p1=REL + "then", p2=REL + "score", v=INST + "2", vLabel="2", ne="1"))
    return parse_kind_catalog(rows)


def _setup():
    kinds = infer_kinds(_members())
    cat = _catalog()
    return kinds, {kinds[0]["name"]: cat}, {p["key"]: i for i, p in enumerate(cat)}


def test_kinds_by_signature_without_rdf_type():
    kinds = infer_kinds(_members())
    assert len(kinds) == 1 and kinds[0]["name"] == "K1"
    assert len(kinds[0]["members"]) == 3                     # 라벨성 단독 노드 제외


def test_value_types():
    by = {p["key"]: p for p in _catalog()}
    assert by["testing_complexity"]["type"] == "enum"
    assert by["tradeoffs.pros"]["type"] == "text"            # 값 20종 > 15
    assert by["decision_rules.then.score"]["type"] == "number"  # 라벨 '-3' (URI 는 inst:_3)


def test_resolve_value_synonym_and_missing():
    by = {p["key"]: p for p in _catalog()}
    vals, note = resolve_value("높음", by["testing_complexity"])
    assert [v["label"] for v in vals] == ["high"] and "동의어" in note
    vals, note = resolve_value("very low", by["testing_complexity"])
    assert vals is None and "값 목록에 없음" in note


def test_validate_rejects_invalid_filter_and_zero_for_missing_value():
    kinds, cats, idx = _setup()
    bad_op = validate_plan({"mode": "plan", "kind": "K1",
                            "filters": [{"path": idx["testing_complexity"], "op": "gt", "value": 1}]}, kinds, cats)
    assert bad_op["status"] == "reject"
    bad_path = validate_plan({"mode": "plan", "kind": "K1", "filters": [{"path": 999, "op": "eq", "value": "x"}]},
                             kinds, cats)
    assert bad_path["status"] == "reject"
    zero = validate_plan({"mode": "plan", "kind": "K1",
                          "filters": [{"path": idx["testing_complexity"], "op": "eq", "value": "very_low"}]},
                         kinds, cats)
    assert zero["status"] == "zero"


def test_validate_drops_invalid_return_and_passes_through_unsupported():
    kinds, cats, idx = _setup()
    ok = validate_plan({"mode": "plan", "kind": "K1",
                        "filters": [{"path": idx["testing_complexity"], "op": "eq", "value": "high"}],
                        "return": [idx["tradeoffs.pros"], 777]}, kinds, cats)
    assert ok["status"] == "ok" and len(ok["plan"]["returns"]) == 1 and ok["adjustments"]
    assert validate_plan({"mode": "unsupported", "reason": "조인"}, kinds, cats)["status"] == "unsupported"


def test_compile_member_query_nested_and_numeric():
    kinds, cats, idx = _setup()
    plan = validate_plan({"mode": "plan", "kind": "K1", "filters": [
        {"path": idx["avoid_signals.team_size"], "op": "eq", "value": "small"},
        {"path": idx["decision_rules.then.score"], "op": "lt", "value": 0},
    ]}, kinds, cats)["plan"]
    q = compile_member_query(plan)
    assert "VALUES ?e" in q and f"<{REL}avoid_signals>" in q and f"<{INST}small>" in q
    assert "xsd:decimal" in q and "< 0" in q


def test_evidence_query_joins_exact_statement_and_scopes_same_item():
    kinds, cats, idx = _setup()
    plan = validate_plan({"mode": "plan", "kind": "K1",
                          "filters": [{"path": idx["decision_rules.then.score"], "op": "lt", "value": 0}],
                          "return": [idx["decision_rules.then.score"]]}, kinds, cats)["plan"]
    q = compile_evidence_query([INST + "micro_frontend"], plan)
    assert "rdf:subject ?s ; rdf:predicate ?p ; rdf:object ?o" in q
    assert 'BIND("filter" AS ?role)' in q and 'BIND("return" AS ?role)' in q


def test_aggregate_count_with_value_and_having():
    kinds, cats, idx = _setup()
    plan = validate_plan({"mode": "plan", "kind": "K1", "aggregate": {
        "fn": "count", "path": idx["testing_complexity"], "value": "high", "having": {"op": "gte", "value": 1}}},
        kinds, cats)["plan"]
    q = compile_aggregate_query([INST + "micro_frontend"], plan["aggregate"])
    assert "COUNT(DISTINCT" in q and "HAVING (?agg >= 1)" in q and f"<{INST}high>" in q


def test_pick_top_with_ties():
    rows = [("a", 3.0), ("b", 3.0), ("c", 2.0)]
    assert pick_top_with_ties(rows, 1) == [("a", 3.0), ("b", 3.0)]


def test_parse_evidence_and_round_robin_chunks():
    e1, e2 = INST + "micro_frontend", INST + "layered"
    bindings = [
        _b(e=e1, role="filter", path="testing_complexity", s=e1, p=REL + "testing_complexity", o=INST + "high",
           oLabel="high", chunk="d1::struct::micro_frontend"),
        _b(e=e1, role="return", path="tradeoffs.pros", s=INST + "root_0_d1_tradeoffs_2", p=REL + "pros",
           o=INST + "x", oLabel="x", chunk="d1::struct::root_0_d1_tradeoffs_2"),
        _b(e=e2, role="filter", path="testing_complexity", s=e2, p=REL + "testing_complexity", o=INST + "high",
           oLabel="high", chunk="d2::struct::layered"),
    ]
    triples = parse_evidence(bindings, [e1, e2])
    assert [t["role"] for t in triples] == ["filter", "return", "filter"]
    assert triples[1]["subject"] == "micro_frontend" and triples[1]["predicate"] == "tradeoffs.pros"
    ranked = [c["chunk_id"].split("::")[0] for c in rank_chunk_ids_grouped(triples, [e1, e2])]
    assert ranked[:2] == ["d1", "d2"]                          # 엔티티별 라운드로빈


def test_spo_extraction_for_free_sparql():
    b = [_b(s=INST + "a", p=REL + "r", o=INST + "b"), _b(subject=INST + "c", predicate=REL + "r", object=INST + "d"),
         _b(x="no spo")]
    assert len(extract_spo_from_bindings(b)) == 2


def test_report_groups_entities_without_flag_words():
    kinds, cats, idx = _setup()
    plan = validate_plan({"mode": "plan", "kind": "K1",
                          "filters": [{"path": idx["testing_complexity"], "op": "eq", "value": "high"}]},
                         kinds, cats)["plan"]
    summary = result_summary([INST + "micro_frontend"], plan)
    assert "micro_frontend" in summary
    report = render_reasoning_report({
        "analysis": {"intent": "class_query", "target_class": "스타일", "entities": ["high"]},
        "linking": [{"entity": "high", "uri": INST + "high", "value_node": True}],
        "targeting": {"mode": "P", "kinds": [{"name": "K1", "members": 3, "examples": ["layered"]}],
                      "catalog_size": 5, "selected_paths": ["필터: testing_complexity = high"],
                      "plan": {"value_matches": ["'high'→high(완전일치)"]}, "result_entities": ["micro_frontend"]},
        "triples": [{"entity": "micro_frontend", "role": "filter", "subject": "micro_frontend",
                     "predicate": "testing_complexity", "object": "high", "chunk_ids": ["d::struct::micro_frontend"]}],
        "chunks": [{"chunk_id": "d::struct::micro_frontend", "triple_idx": [1]}],
    })
    text = "\n".join(report)
    assert "P(질의 계획" in text and "▸ micro_frontend" in text and "[필터]" in text and "값 노드" in text
    for w in ("error", "failed", "fallback"):
        assert w not in text.lower()
