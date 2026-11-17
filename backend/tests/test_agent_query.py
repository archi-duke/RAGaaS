"""외부 에이전트용 조회 P1 단위 테스트 (docs/design/agent/design-mcp-agent-query.md)."""
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


# --- 용어 사전 (docs/design/agent/design-kb-lexicon.md) ---------------------------------------------------------
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


def test_run_plan_reports_query_failure(monkeypatch):
    """그래프 조회 실패를 '결과 없음'으로 숨기지 않고 status=error 로 돌려준다."""
    import asyncio
    from app.services.agent_query import plan as pl
    from app.services.agent_query import catalog as ct

    kinds, cats = _catalog()

    async def fake_load(kb_id):
        return None, kinds, cats, "v1"

    def boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(ct, "load_catalog", fake_load)
    import app.core.fuseki as F
    monkeypatch.setattr(F.fuseki_client, "query_sparql_strict", boom)
    r = asyncio.run(pl.run_plan("kb", {"kind": "Style", "where": {"path": "consistency_model", "op": "eq", "value": "strong"}}))
    assert r["status"] == "error" and "조회 실패" in r["message"]


def test_year_condition_parse_and_compile():
    assert cq.parse_year_cond(1933) == ({"gte": 1933, "lte": 1933}, None)
    assert cq.parse_year_cond({"gte": 1930, "lte": 1939}) == ({"gte": 1930, "lte": 1939}, None)
    assert cq.parse_year_cond({"gt": 1929, "lt": 1940}) == ({"gte": 1930, "lte": 1939}, None)
    assert cq.parse_year_cond({"gte": 1940, "lte": 1930})[1]
    assert cq.parse_year_cond({"from": 1930})[1]
    assert cq.parse_year_cond(99)[1]
    kinds, cats = _catalog()
    f = [{"path": "has_positive_effect_on", "op": "exists", "year": {"gte": 1930, "lte": 1939}}]
    r = cq.validate_plan({"kind": "Style", "filters": f}, kinds, cats, strict=True)
    assert r["status"] == "ok" and r["plan"]["filters"][0]["year"] == {"gte": 1930, "lte": 1939}
    sp = cq.compile_member_query(r["plan"])
    assert "meta:year ?yrf0" in sp and "?yrf0 >= 1930 && ?yrf0 <= 1939" in sp
    assert "meta:year" in cq.compile_evidence_query(["http://x/s1"], r["plan"])
    # ne 와 함께는 반려
    f = [{"path": "consistency_model", "op": "ne", "value": "strong", "year": 1933}]
    assert cq.validate_plan({"kind": "Style", "filters": f}, kinds, cats, strict=True)["status"] == "reject"


def test_parse_evidence_collects_years():
    b = lambda y: {"e": {"value": "http://x/e"}, "s": {"value": "http://x/e"}, "p": {"value": "http://r/p"},
                   "o": {"value": "http://x/o"}, "oLabel": {"value": "노벨 물리학상"}, "role": {"value": "filter"},
                   **({"year": {"value": str(y)}} if y else {})}
    ts = cq.parse_evidence([b(1933), b(1922), b(None)], ["http://x/e"])
    assert len(ts) == 1 and ts[0]["years"] == [1922, 1933]


def test_followup_ask_detection():
    from app.services.retrieval.entity_linking import has_followup_ask
    assert has_followup_ask("피르나우 저온 흑체 측정이 기반한 보정법은 무엇이며, 누가 몇 년에 제안했는가?")
    assert has_followup_ask("그 실험은 무엇이고 언제 수행되었나?")
    assert not has_followup_ask("특수상대성이론이 계승·발전시킨 두 선행 개념(원리·변환)은 무엇이며, "
                                "특수상대성이론을 기하학적으로 계승·발전시킨 개념은 무엇인가?")
    assert not has_followup_ask("뉴턴이 저술한 책은 무엇인가?")


def test_term_matched_paths_promotes_tail_paths():
    vals = lambda *ls: [{"uri": f"http://x/{l}", "label": l, "members": 1} for l in ls]
    cat = [{"key": f"p{i}", "uris": [f"http://r/p{i}"], "type": "text", "values": vals(f"값{i}"), "examples": [], "dv": 1} for i in range(200)]
    cat.append({"key": "자문", "uris": ["http://r/a"], "type": "text", "values": vals("원자폭탄 개발"), "examples": [], "dv": 1})
    cat.append({"key": "참여", "uris": ["http://r/b"], "type": "text", "values": vals("전시 원자폭탄 개발 계획"), "examples": [], "dv": 1})
    kinds = [{"name": "Person", "members": ["http://x/p"], "examples": [], "class_uri": "http://c/P"}]
    cats = {"Person": cat}
    hits = cq.term_matched_paths(["원자 폭탄", "atomic bomb"], kinds, cats)
    assert [k for k, _ in hits["Person"]] == ["자문", "참여"]
    promoted = cq.promote_paths(cats, hits)
    assert [p["key"] for p in promoted["Person"][:2]] == ["자문", "참여"] and len(promoted["Person"]) == len(cat)
    msg = cq.build_plan_messages("원자 폭탄 개발에 기여한 사람은?", kinds, promoted, None, "", hits)[1]["content"]
    assert "0. 자문 = '원자폭탄 개발'" in msg and "1. 참여 = '전시 원자폭탄 개발 계획'" in msg
    assert cq.term_matched_paths(["a"], kinds, cats) == {}   # 1글자·영문만은 힌트 안 만듦


def test_fuzzy_match_jamo_typos_and_auto_rule():
    from app.services.agent_query import fuzzy_match as fm
    labels = ["슈뢰딩거 방정식", "디랙 방정식", "하이젠베르크", "원자폭탄 개발", "불확정성 원리",
              "확률 해석·불확정성 원리·상보성 원리를 거침", "광전 효과"]
    top = lambda t: fm.fuzzy_candidates(t, labels)
    assert top("슈레딩거 방정식")[0]["label"] == "슈뢰딩거 방정식" and top("슈레딩거 방정식")[0]["auto"]
    assert top("하이젠베르그")[0]["label"] == "하이젠베르크"
    assert top("광전효과")[0] == {"label": "광전 효과", "distance": 0.0, "via": "fuzzy", "auto": True}
    # 긴 설명형 라벨은 부분 일치여도 자동 확정하지 않는다
    long_ = [c for c in top("불확정성원리") if c["label"].startswith("확률")]
    assert long_ and not long_[0]["auto"]
    # 오타가 큰 말은 후보일 뿐 자동 확정 안 함
    c = top("핵폭틴 개방")
    assert c and c[0]["label"] == "원자폭탄 개발" and not c[0]["auto"]
    assert fm.fuzzy_candidates("QED", labels) == []      # 한글 없는 말은 자모 대상 아님


def test_contains_accepts_value_list_as_or():
    kinds, cats = _catalog()
    f = [{"path": "has_positive_effect_on", "op": "contains", "value": ["변경", "확장"]}]
    r = cq.validate_plan({"kind": "Style", "filters": f}, kinds, cats, strict=True)
    assert r["status"] == "ok" and r["plan"]["filters"][0]["texts"] == ["변경", "확장"]
    sp = cq.compile_member_query(r["plan"])
    assert 'CONTAINS(LCASE(STR(?tlf0)), LCASE("변경")) || CONTAINS(LCASE(STR(?tlf0)), LCASE("확장"))' in sp
    assert "['" not in sp


def test_resolve_max_hops_and_plan_truncation():
    from app.services.retrieval import chain_query as chq
    assert chq.resolve_max_hops({}) == 6                                   # 기본
    assert chq.resolve_max_hops({"is_auto_hops": True, "hops": 2}) == 6   # 옛 Auto → 기본
    assert chq.resolve_max_hops({"is_auto_hops": False, "hops": 3}) == 3  # 옛 고정 hops → 상한
    assert chq.resolve_max_hops({"max_hops": 20}) == 8                    # 절대 상한
    vocab = [{"name": "영향_줌", "domain": "", "range": "", "description": "", "count": 5}]
    data = {"chainable": True, "start": "A", "hops": [{"relations": ["영향_줌"], "direction": "out", "expect": ""}] * 5}
    plan, notes = chq.validate_plan(data, vocab, max_hops=3)
    assert len(plan["hops"]) == 3 and any("최대 홉 설정 3" in n for n in notes)


def test_prune_dead_branches_keeps_only_complete_paths():
    from app.services.retrieval import chain_query as chq
    T = lambda s, o: {"s_uri": f"u:{s}", "o_uri": f"u:{o}"}
    hop_runs = [
        (["u:맥스웰"], [T("맥스웰", "아인슈타인"), T("맥스웰", "볼츠만")]),
        (["u:아인슈타인", "u:볼츠만"], [T("아인슈타인", "광양자"), T("볼츠만", "엔트로피공식")]),
        (["u:광양자", "u:엔트로피공식"], [T("광양자", "물질파")]),          # 엔트로피공식 은 막다른 갈래
    ]
    kept, removed = chq.prune_dead_branches(hop_runs, lambda u: [u])
    assert removed == 2
    assert kept[0] == [T("맥스웰", "아인슈타인")] and kept[1] == [T("아인슈타인", "광양자")]


def test_hop_direction_flags():
    from app.services.retrieval import chain_query as chq
    vocab = [{"name": "지도교수_of", "domain": "Person", "range": "Person", "description": "", "count": 9},
             {"name": "계승_발전", "domain": "TheoryOrConcept", "range": "TheoryOrConcept", "description": "", "count": 20},
             {"name": "제안함", "domain": "Person", "range": "TheoryOrConcept", "description": "", "count": 50}]
    plan, _ = chq.validate_plan({"chainable": True, "start": "A", "hops": [
        {"relations": ["지도교수_of"], "direction": "in"}, {"relations": ["계승_발전"], "direction": "out"},
        {"relations": ["제안함"], "direction": "out"}]}, vocab)
    h1, h2, h3 = plan["hops"]
    assert h1["same_class"] and not h1["lineage"]          # 사제: 반대 방향 재시도 안 함
    assert h2["lineage"] and not h2.get("both")             # 계보: 계획 방향 먼저 (0건이면 양방향)
    assert not h3["same_class"] and not h3["lineage"]       # 제안함: 재시도 허용


def test_numeric_terms_are_not_typo_candidates():
    from app.services.agent_query import fuzzy_match as fm
    from app.services.retrieval import class_query as cq
    assert fm.fuzzy_candidates("1930년대", ["1950년대", "1920년대"]) == []
    kinds = [{"name": "Person"}]
    cats = {"Person": [{"key": "명명_시기", "values": [{"label": "1930년대 이론"}]}]}
    assert cq.term_matched_paths(["1930년대"], kinds, cats) == {}
