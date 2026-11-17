"""다단계 체인 검색(chain_query) 단위 테스트 — docs/design/graph/design-graph-multihop-chain.md"""
from app.services.retrieval import chain_query as cq

INST = "http://rag.local/inst/"
REL = "http://rag.local/rel/"


def _vb(name, n):
    return {"p": {"value": REL + name}, "n": {"value": str(n)}}


VOCAB = cq.build_vocab(
    [_vb("발견함", 115), _vb("지도교수_of", 21), _vb("제안함", 181), _vb("설명", 1)],
    [{"name": "지도교수_of", "description": "스승 → 제자", "domain": "Person", "range": "Person"}],
)


def test_vocab_schema_first_and_rare_dropped():
    assert [v["name"] for v in VOCAB] == ["지도교수_of", "제안함", "발견함"]   # 건수 1 인 '설명' 제외
    assert VOCAB[0]["description"] == "스승 → 제자"
    msgs = cq.build_plan_messages("광전효과를 처음 발견한 사람의 지도교수는?", VOCAB)
    assert "- 지도교수_of (Person → Person): 스승 → 제자" in msgs[1]["content"]


def test_validate_plan_keeps_vocab_relations_only():
    plan, notes = cq.validate_plan({
        "chainable": True, "start": "광전효과",
        "hops": [{"relations": ["발견함", "발견했다"], "direction": "in", "expect": "인물"},
                 {"relations": ["지도교수 of"], "direction": "in"},
                 {"relations": ["제안함"], "direction": "sideways"}],
        "final_relations": [{"relation": "없는관계", "direction": "out"}],
    }, VOCAB)
    assert [h["relations"] for h in plan["hops"]] == [["발견함"], ["지도교수_of"], ["제안함"]]
    assert plan["hops"][2]["direction"] == "out"          # 잘못된 방향 → 기본 out
    assert plan["finals"] == []
    assert any("발견했다" in n for n in notes)


def test_validate_plan_rejects():
    assert cq.validate_plan({"chainable": False}, VOCAB)[0] is None
    assert cq.validate_plan({"start": "X", "hops": [{"relations": ["모름"]}]}, VOCAB)[0] is None
    assert cq.validate_plan(None, VOCAB)[0] is None


def test_hop_query_binds_frontier_by_direction():
    q = cq.build_hop_query([INST + "헤르츠"], ["지도교수_of"], "in", "hop2")
    assert "VALUES ?o { <http://rag.local/inst/헤르츠> }" in q
    assert "VALUES ?p { <http://rag.local/rel/지도교수_of> }" in q
    assert "rdf:subject ?s ; rdf:predicate ?p ; rdf:object ?o" in q
    assert "VALUES ?s" in cq.build_hop_query([INST + "a"], ["제안함"], "out", "hop1")


def _b(s, p, o, chunk, path="hop1"):
    return {"s": {"value": INST + s}, "p": {"value": REL + p}, "o": {"value": INST + o},
            "chunk": {"value": chunk}, "path": {"value": path}}


def test_frontier_and_chunk_interleave():
    h1 = cq.parse_hop([_b("헤르츠", "발견함", "광전효과", "c1"), _b("레나르트", "발견함", "광전효과", "c2")], 1)
    assert cq.next_frontier(h1, "in") == [INST + "헤르츠", INST + "레나르트"]
    h2 = cq.parse_hop([_b("헬름홀츠", "지도교수_of", "헤르츠", "c3")], 2)
    h3 = cq.parse_hop([_b("헬름홀츠", "제안함", "에너지_보존_법칙", "c4")], 3)
    ranked = cq.order_chunks_by_hop(h1 + h2 + h3)
    assert [c["chunk_id"] for c in ranked][:3] == ["c1", "c3", "c4"]     # 홉별 하나씩 먼저
    assert [c["chunk_id"] for c in ranked][3] == "c2"


# --- 보강: 양방향 계보 관계, 순환 방지, 끊긴 홉 재선택 ---

LINEAGE_VOCAB = cq.build_vocab(
    [_vb("계승_발전", 30), _vb("지도교수_of", 21)],
    [{"name": "계승_발전", "description": "선행 → 후속", "domain": "TheoryOrConcept", "range": "TheoryOrConcept"},
     {"name": "지도교수_of", "description": "스승 → 제자", "domain": "Person", "range": "Person"}],
)


def test_lineage_relation_is_bidirectional_but_person_relation_is_not():
    # 2026-11-17: 계보 관계는 계획 방향을 먼저 조회하고 0건일 때만 양방향(both)으로 넓힌다 (fuseki run_hop).
    # 인물 관계(지도교수_of)는 같은 클래스라 반대 방향 재시도도 하지 않는다.
    plan, _ = cq.validate_plan({"start": "광양자 가설", "hops": [
        {"relations": ["계승_발전"], "direction": "out"}, {"relations": ["지도교수_of"], "direction": "in"}]},
        LINEAGE_VOCAB)
    assert plan["hops"][0]["lineage"] is True and not plan["hops"][0].get("both")
    assert plan["hops"][1]["lineage"] is False
    assert "↔" in cq.hop_label({**plan["hops"][0], "both": True, "no": 1}, 1, 2, 2, False)


def test_next_frontier_takes_far_end_and_skips_visited():
    start = INST + "광양자_가설"
    trip = cq.parse_hop([_b("광양자_가설", "계승_발전", "물질파_가설", "c1"),
                         _b("드브로이", "계승_발전", "광양자_가설", "c2")], 1)
    assert cq.next_frontier(trip, "out", frontier=[start]) == [INST + "물질파_가설", INST + "드브로이"]
    assert cq.next_frontier(trip, "out", frontier=[start], visited={INST + "드브로이"}) == [INST + "물질파_가설"]


def test_repick_options_and_validation():
    opts = cq.parse_frontier_relations([
        {"p": {"value": REL + "확인함"}, "dir": {"value": "out"}, "n": {"value": "3"}, "ex": {"value": INST + "맥스웰_방정식"}},
        {"p": {"value": REL + "수행함"}, "dir": {"value": "in"}, "n": {"value": "1"}, "ex": {"value": INST + "하인리히_헤르츠"}},
    ])
    assert opts[0] == {"relation": "확인함", "direction": "out", "count": 3, "example": "맥스웰_방정식"}
    msgs = cq.build_repick_messages("헤르츠의 실험이 확인한 이론은?", {"relations": ["검증함"], "expect": "이론"}, "전자기파 실험", opts)
    assert "1. 확인함 (현재 노드가 주어, 3건, 예: 맥스웰_방정식)" in msgs[1]["content"]
    assert cq.validate_repick({"picks": [1, "2", 9, 1]}, opts) == opts
    assert cq.validate_repick({"picks": []}, opts) == []
    assert cq.validate_repick(None, opts) == []


def test_filter_hop_keeps_node_and_filters_by_value():
    plan, _ = cq.validate_plan({"start": "제임스 줄", "hops": [
        {"relations": ["지도교수_of"], "direction": "out"},
        {"relations": ["계승_발전"], "direction": "out", "filter": True, "value": "할스테트"},
        {"relations": ["지도교수_of"], "direction": "out"}]}, LINEAGE_VOCAB)
    assert plan["hops"][1]["filter"] and plan["hops"][1]["value"] == "할스테트"
    a, b = INST + "크뢰벨", INST + "다른사람"
    trip = [{"s_uri": a, "o_uri": INST + "할스테트_연구소", "subject": "크뢰벨", "object": "할스테트 연구소"},
            {"s_uri": b, "o_uri": INST + "베를린_대학", "subject": "다른사람", "object": "베를린 대학"}]
    keep, nodes, by_value = cq.apply_filter_hop(trip, [a, b], "할스테트")
    assert nodes == [a] and by_value and len(keep) == 1
    keep, nodes, by_value = cq.apply_filter_hop(trip, [a, b], "없는값")
    assert nodes == [a, b] and not by_value          # 값이 안 맞으면 관계만으로


def test_filter_hop_value_tolerates_typo():
    a = INST + "크뢰벨"
    trip = [{"s_uri": a, "o_uri": INST + "할스테트_정밀물리연구소", "subject": "크뢰벨", "object": "할스테트 정밀물리연구소"}]
    _, nodes, by_value = cq.apply_filter_hop(trip, [a], "할스테드")
    assert nodes == [a] and by_value
