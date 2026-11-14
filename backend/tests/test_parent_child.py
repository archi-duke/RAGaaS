"""Parent-Child 검색 치환(merge_into_parents) 테스트."""
from app.services.retrieval.parent_child import merge_into_parents


def _r(cid, content, score, doc="d1"):
    return {"chunk_id": cid, "content": content, "score": score, "metadata": {"doc_id": doc}}


def test_children_replaced_by_parent_and_deduplicated():
    results = [_r("c1", "child-1", 0.9), _r("c2", "child-2", 0.8), _r("c3", "child-3", 0.7)]
    meta = {
        "c1": {"parent_id": "parent_0", "parent_content": "PARENT-0"},
        "c2": {"parent_id": "parent_1", "parent_content": "PARENT-1"},
        "c3": {"parent_id": "parent_0", "parent_content": "PARENT-0"},
    }
    out = merge_into_parents(results, meta)
    assert [r["content"] for r in out] == ["PARENT-0", "PARENT-1"]
    assert out[0]["score"] == 0.9                       # 최상위 child 점수 유지
    assert out[0]["metadata"]["child_chunk_ids"] == ["c1", "c3"]
    assert out[0]["metadata"]["matched_child_content"] == "child-1"
    assert out[0]["metadata"]["retrieval_unit"] == "parent"


def test_non_parent_chunks_untouched():
    results = [_r("c1", "plain", 0.9), _r("c2", "child", 0.8)]
    meta = {"c1": {}, "c2": {"parent_id": 0, "parent_content": "PARENT"}}
    out = merge_into_parents(results, meta)
    assert out[0] is results[0]
    assert out[1]["content"] == "PARENT"


def test_same_parent_id_in_different_docs_not_merged():
    results = [_r("a1", "x", 0.9, doc="A"), _r("b1", "y", 0.8, doc="B")]
    meta = {
        "a1": {"parent_id": "parent_0", "parent_content": "A-PARENT"},
        "b1": {"parent_id": "parent_0", "parent_content": "B-PARENT"},
    }
    out = merge_into_parents(results, meta)
    assert [r["content"] for r in out] == ["A-PARENT", "B-PARENT"]


def test_input_not_mutated():
    results = [_r("c1", "child", 0.9)]
    merge_into_parents(results, {"c1": {"parent_id": 0, "parent_content": "P"}})
    assert results[0]["content"] == "child"
    assert "child_chunk_ids" not in results[0]["metadata"]
