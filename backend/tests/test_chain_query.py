"""다단계 체인 검색(chain_query) 단위 테스트 — docs/design-graph-multihop-chain.md"""
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
