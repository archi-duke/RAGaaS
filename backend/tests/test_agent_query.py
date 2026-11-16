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


# --- 용어 사전 (docs/design-kb-lexicon.md) ---------------------------------------------------------
from types import SimpleNamespace

from app.services.agent_query import lexicon as lx


def _e(label, ko=(), en=(), syn=(), broader=(), concept_only=False, skip=False, variants=()):
    return SimpleNamespace(label=label, norm=lx._compact(label), ko=list(ko), en=list(en), syn=list(syn),
                           broader=[{"label": b, "status": "proposed"} for b in broader],
                           concept_only=concept_only, skip=skip, variants=list(variants))


def test_compact_normalizes_dashes():
    assert lx._compact("Michelson–Morley experiment") == lx._compact("Michelson-Morley experiment")


def test_index_alias_variant_and_generic_suffix():
    idx = lx.build_index([
        _e("Hexagonal 아키텍처", ko=["헥사고날 아키텍처"], syn=["Ports and Adapters", "포트와 어댑터"], broader=["아키텍처 스타일"]),
        _e("Clean Architecture", ko=["클린 아키텍처"], variants=["clean-architecture"]),
        _e("변경 용이성", en=["modifiability"], syn=["수정 용이성"], broader=["유지보수성"]),
        _e("유지보수성", en=["maintainability"], concept_only=True),
    ])
    top = lambda t: [m["label"] for m in lx.match_term(idx, t)]
    assert top("헥사고날")[0] == "Hexagonal 아키텍처"                  # 일반어 제거 표기
    assert lx.match_term(idx, "헥사고날")[0]["score"] == lx.SCORE_STRIPPED
    assert top("포트와 어댑터") == ["Hexagonal 아키텍처"]
    assert set(top("클린 아키텍처")) == {"Clean Architecture", "clean-architecture"}   # 변형 라벨
    assert top("수정 용이성") == ["변경 용이성"]
    assert top("블록체인") == []
    # 상위 개념: 한국어·영어 표기 모두 하위 라벨로
    assert [n["label"] for n in lx.narrower_of(idx, "유지보수성")] == ["변경 용이성"]
    assert [n["label"] for n in lx.narrower_of(idx, "maintainability")] == ["변경 용이성"]
    assert lx.narrower_of(idx, "유지보수성")[0]["reviewed"] is False


def test_index_concept_lends_aliases_and_descriptive_labels_not_aliased():
    idx = lx.build_index([
        _e("deployability", ko=["배포 가능성"]),
        _e("배포성", ko=["배포 용이성"], en=["deployability"], concept_only=True),
        _e("단순 CRUD에 포트/어댑터 도입은 과설계", syn=["헥사고날"]),
    ])
    assert [m["label"] for m in lx.match_term(idx, "배포 용이성")] == ["deployability"]
    assert lx.match_term(idx, "헥사고날") == []          # 설명형 라벨의 별칭은 색인하지 않음


def test_rejected_broader_ignored():
    e = _e("변경 용이성", broader=["유지보수성"])
    e.broader[0]["status"] = "rejected"
    assert lx.narrower_of(lx.build_index([e]), "유지보수성") == []


def test_english_forms_for_translated_fallback():
    fm = lx.english_forms([
        _e("하이젠베르크", en=["Heisenberg", "Werner Heisenberg"]),
        _e("Microservices", ko=["마이크로서비스"], syn=["MSA", "마이크로서비스 아키텍처"]),
        _e("circuit_breaker", en=["circuit breaker"]),
        _e("단순 CRUD에 포트/어댑터 도입은 과설계", en=["over-engineering for simple CRUD"]),
        _e("deployability", ko=["배포 가능성"]),
        _e("배포성", en=["deployability", "ease of deployment"], concept_only=True),
    ])
    assert fm["Heisenberg"] == {"하이젠베르크"} and fm["Werner Heisenberg"] == {"하이젠베르크"}
    assert fm["Microservices"] == {"Microservices"} and fm["MSA"] == {"Microservices"}
    assert "마이크로서비스 아키텍처" not in fm                       # 한글 동의어는 영어 표기 아님
    assert fm["circuit breaker"] == {"circuit_breaker"}               # snake_case → 띄어쓰기
    assert not any("CRUD" in f for f in fm)                           # 설명형 라벨 제외
    assert fm["ease of deployment"] == {"deployability"}              # 상위 개념 항목이 빌려준 영어 표기


# --- query_plan (P2) -------------------------------------------------------------------------------
from app.services.agent_query.plan import PlanError, to_dnf
from app.services.retrieval import class_query as cq

A = {"path": "a", "op": "eq", "value": 1}
B = {"path": "b", "op": "eq", "value": 2}
C = {"path": "c", "op": "eq", "value": 3}


def test_to_dnf():
    assert to_dnf(None) == [[]]
    assert to_dnf(A) == [[A]]
    assert to_dnf({"all": [A, B]}) == [[A, B]]
    assert to_dnf({"any": [A, B]}) == [[A], [B]]
    assert to_dnf({"all": [A, {"any": [B, C]}]}) == [[A, B], [A, C]]
    assert to_dnf([A, B]) == [[A, B]]                       # 맨 리스트 = all
    with pytest.raises(PlanError):
        to_dnf({"all": [A], "any": [B]})
    with pytest.raises(PlanError):
        to_dnf({"any": []})
    many = {"all": [{"any": [A, B]} for _ in range(7)]}      # 2^7 = 128 > 64
    with pytest.raises(PlanError):
        to_dnf(many)


def _catalog():
    vals = lambda *ls: [{"uri": f"http://x/{l}", "label": l, "members": 1} for l in ls]
    paths = [
        {"key": "has_positive_effect_on", "uris": ["http://r/p"], "type": "text", "values": vals("변경 용이성", "확장성"), "examples": [], "dv": 20},
        {"key": "consistency_model", "uris": ["http://r/c"], "type": "enum", "values": vals("eventual", "strong")},
    ]
    kinds = [{"name": "Style", "members": ["http://x/s1"], "examples": [], "class_uri": "http://c/Style"}]
    return kinds, {"Style": paths}


def test_validate_plan_accepts_keys_and_text_in():
    kinds, cats = _catalog()
    r = cq.validate_plan({"kind": "Style", "filters": [{"path": "has_positive_effect_on", "op": "in",
                                                        "value": ["변경 용이성", "확장성"]}]}, kinds, cats, strict=True)
    assert r["status"] == "ok" and len(r["plan"]["filters"][0]["values"]) == 2
    # 번호(내부 LLM)도 그대로
    r = cq.validate_plan({"kind": "Style", "filters": [{"path": 1, "op": "eq", "value": "strong"}]}, kinds, cats)
    assert r["status"] == "ok"
    # 모르는 key → reject
    assert cq.validate_plan({"kind": "Style", "filters": [{"path": "nope", "op": "eq", "value": "x"}]},
                            kinds, cats, strict=True)["status"] == "reject"


def test_validate_plan_strict_no_loose_text_match():
    kinds, cats = _catalog()
    f = [{"path": "has_positive_effect_on", "op": "eq", "value": "변경"}]
    assert cq.validate_plan({"kind": "Style", "filters": f}, kinds, cats, strict=True)["status"] == "zero"
    # 필터 수 초과는 strict 에서 반려 (내부는 잘라냄)
    five = [{"path": "consistency_model", "op": "exists"}] * 5
    assert cq.validate_plan({"kind": "Style", "filters": five}, kinds, cats, strict=True)["status"] == "reject"
    assert cq.validate_plan({"kind": "Style", "filters": five}, kinds, cats)["status"] == "ok"


def test_validate_plan_strict_in_skips_unknown_values():
    kinds, cats = _catalog()
    f = [{"path": "consistency_model", "op": "in", "value": ["strong", "medium_or_lower"]}]
    r = cq.validate_plan({"kind": "Style", "filters": f}, kinds, cats, strict=True)
    assert r["status"] == "ok" and [v["label"] for v in r["plan"]["filters"][0]["values"]] == ["strong"]
    assert any("medium_or_lower" in a for a in r["adjustments"])
    # 전부 목록 밖이면 zero, 내부(비 strict)는 기존대로 zero
    assert cq.validate_plan({"kind": "Style", "filters": [{"path": "consistency_model", "op": "in", "value": ["x", "y"]}]},
                            kinds, cats, strict=True)["status"] == "zero"
    assert cq.validate_plan({"kind": "Style", "filters": f}, kinds, cats)["status"] == "zero"


def test_to_dnf_allows_many_or_leaves():
    leaves = [{"path": f"p{i}", "op": "eq", "value": i} for i in range(40)]
    assert len(to_dnf({"any": leaves})) == 40
