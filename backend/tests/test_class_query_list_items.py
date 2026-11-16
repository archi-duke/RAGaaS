"""목록 항목 조건은 같은 항목에서 맞아야 한다 (quality_attributes.attribute AND .effect)."""
from app.services.retrieval import class_query as cq

QA = "http://rag.local/rel/quality_attributes"
ATTR = "http://rag.local/rel/attribute"
EFF = "http://rag.local/rel/effect"
FIT = "http://rag.local/rel/fit_signals"


def _plan(filters):
    return {"kind": {"members": ["http://rag.local/inst/a"]}, "filters": filters}


def _f(uris, val):
    return {"op": "eq", "path": {"uris": uris}, "values": [{"uri": val}]}


def test_sibling_list_fields_share_item_node():
    q = cq.compile_member_query(_plan([_f([QA, ATTR], "http://rag.local/inst/deployability"),
                                       _f([QA, EFF], "http://rag.local/inst/positive")]))
    # 두 조건이 같은 구조노드 변수(?ms0)를 쓴다
    assert q.count(f"<{QA}> ?ms0") == 2 and "?mf1" not in q


def test_different_parents_do_not_share():
    q = cq.compile_member_query(_plan([_f([QA, ATTR], "http://rag.local/inst/deployability"),
                                       _f([FIT, "http://rag.local/rel/modifiability"], "http://rag.local/inst/high")]))
    assert "?ms0" in q and "?ms1" in q


def test_negated_filter_keeps_own_node():
    neg = {"op": "ne", "path": {"uris": [QA, EFF]}, "values": [{"uri": "http://rag.local/inst/negative"}]}
    q = cq.compile_member_query(_plan([_f([QA, ATTR], "http://rag.local/inst/deployability"), neg]))
    assert "?mf1" in q
