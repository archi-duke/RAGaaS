"""외부 에이전트용 조회 P1 단위 테스트 (docs/design-mcp-agent-query.md)."""
import pytest
from fastapi import HTTPException

from app.api.agent_query import check_readonly
from app.services.agent_query import catalog as cat


def test_relation_traits():
    t = cat.relation_traits("has_moderate_negative_effect_on")
    assert t == {"polarity": "negative", "strength": "moderate", "family": "has_effect_on"}
    t = cat.relation_traits("has_positive_effect_on")
    assert t["polarity"] == "positive" and t["strength"] == "strong" and t["family"] == "has_effect_on"
    assert cat.relation_traits("requires") == {}
    assert cat.relation_traits("quality_attributes.effect") == {}


def test_path_view_enum_text_number():
    enum = {"key": "consistency_model", "type": "enum", "dv": 3,
            "values": [{"uri": "u1", "label": "eventual", "members": 3}, {"uri": "u2", "label": "strong", "members": 2},
                       {"uri": "u3", "label": "n/a", "members": 5}]}
    v = cat._path_view(enum, max_values=2)
    assert [x["label"] for x in v["values"]] == ["eventual", "strong"] and v["values_truncated"] is True
    # 짧은 라벨이 대부분인 text 경로도 어휘로
    text = {"key": "has_positive_effect_on", "type": "text", "dv": 2,
            "values": [{"uri": "a", "label": "변경 용이성", "members": 5}, {"uri": "b", "label": "확장성", "members": 4}]}
    v = cat._path_view(text, max_values=30)
    assert v["values"][0] == {"label": "변경 용이성", "members": 5} and v["polarity"] == "positive"
    # 문장형 text 는 예시만
    long_ = {"key": "description", "type": "text", "dv": 2,
             "values": [{"uri": "a", "label": "가" * 60, "members": 1}, {"uri": "b", "label": "나" * 70, "members": 1}]}
    assert "values" not in cat._path_view(long_, 30) and len(cat._path_view(long_, 30)["examples"]) == 2
    num = {"key": "score", "type": "number", "range": [-3, 3]}
    assert cat._path_view(num, 30)["range"] == [-3, 3]
    same = {"key": "metadata.ops", "type": "enum", "values": [], "equiv_rep": "ops_complexity"}
    assert cat._path_view(same, 30)["same_as"] == "ops_complexity"


def test_local_label():
    assert cat._local_label("http://rag.local/inst/Hexagonal_%EC%95%84%ED%82%A4%ED%85%8D%EC%B2%98") == "Hexagonal 아키텍처"
    assert cat._local_label("http://rag.local/inst/Clean_Architecture") == "Clean Architecture"


@pytest.mark.parametrize("q", [
    "SELECT ?s WHERE { ?s ?p ?o } LIMIT 5",
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nSELECT ?l WHERE { ?s rdfs:label ?l }",
    'SELECT ?s WHERE { ?s ?p "please DELETE me" }',          # 리터럴 안의 단어는 무시
    "SELECT ?s WHERE { ?s <http://x/insert> ?o }",            # IRI 안의 단어는 무시
    "ASK { ?s ?p ?o }",
])
def test_readonly_allows(q):
    assert check_readonly(q) in ("SELECT", "ASK")


@pytest.mark.parametrize("q", [
    "INSERT DATA { <a> <b> <c> }",
    "DELETE WHERE { ?s ?p ?o }",
    "SELECT * WHERE { SERVICE <http://evil/sparql> { ?s ?p ?o } }",
    "LOAD <http://x/data.ttl>",
    "DROP ALL",
    "WITH <g> DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }",
    "",
])
def test_readonly_rejects(q):
    with pytest.raises(HTTPException):
        check_readonly(q)
