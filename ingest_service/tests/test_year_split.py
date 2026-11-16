"""연도 분리 (D4 Y1) — 결정적 규칙."""
from app.core.schema_normalizer import split_year, apply_rules_to_triples


def test_paren_year():
    assert split_year("노벨 물리학상 (1933년)") == ("노벨 물리학상", 1933, "1933년")
    assert split_year("루스벨트 대통령에게 핵분열 경고 편지 (1939)") == ("루스벨트 대통령에게 핵분열 경고 편지", 1939, "1939")
    assert split_year("『새로운 두 과학』 (1638년 출간)") == ("『새로운 두 과학』", 1638, "1638년 출간")
    assert split_year("프린시페섬(1919년 일식)") == ("프린시페섬", 1919, "1919년 일식")


def test_lead_and_comma_year():
    assert split_year("1908년 쾰른 강연") == ("쾰른 강연", 1908, "1908년")
    assert split_year("1919년 11월 런던 왕립학회·왕립천문학회 합동 회의")[1:] == (1919, "1919년 11월")
    assert split_year("기체 분자 속도 분포, 1860년") == ("기체 분자 속도 분포", 1860, "1860년")


def test_not_split():
    for v in ["1887년", "1850년대", "1801~1803년 무렵", "1665년부터 1666년 (흑사병으로 대학 휴교)",
              "1919년 발표 이후", "1703년부터 왕립학회 회장", "기원전 384년", "패러데이의 역선을 수학적 언어로 번역하는 작업 (1850년대 중반)",
              "1642년 성탄절 (율리우스력, 그레고리력으로는 1643년 1월)", "측정 결과 1847년과 1850년", "노벨 물리학상", "1900년 10월", "1610년 초", "1900년 12월 14일", "1920년대 중반", None, 1933]:
        assert split_year(v) is None, v


def test_replay_merges_prize_and_keeps_old_triple_rule():
    raw = [
        {"subject": "피르나우", "predicate": "수상함", "object": "노벨 물리학상 (1933년)", "source_node_id": "c1"},
        {"subject": "보어", "predicate": "수상함", "object": "노벨 물리학상 (1922년)", "source_node_id": "c2"},
        {"subject": "갑", "predicate": "수상함", "object": "노벨 물리학상 (1918년)", "source_node_id": "c3"},
    ]
    rules = [{"rule_type": "triple", "pair": ["갑", "수상함", "노벨 물리학상 (1918년)"], "target_path": None}]
    out, rep = apply_rules_to_triples(raw, rules)
    assert rep["counts"]["year"] == 3 and rep["counts"]["triple_deleted"] == 1
    assert {t["object"] for t in out} == {"노벨 물리학상"}
    assert sorted(t["year"] for t in out) == [1922, 1933]
    # 입력은 그대로 (멱등)
    assert raw[0]["object"] == "노벨 물리학상 (1933년)"
    out2, _ = apply_rules_to_triples(raw, rules)
    assert out2 == out


def test_extraction_year_grounding():
    from app.core.schema_reextract import grounded_year, parse_response
    text = "크뢰벨은 열을 연구했다. 1872년 크뢰벨은 『열과 일의 정밀측정』을 저술했다. 같은 해 그는 교수가 되었다."
    assert grounded_year(1872, text, "크뢰벨", "『열과 일의 정밀측정』") == 1872
    assert grounded_year("1872년", text, "크뢰벨", "교수") == 1872          # 주어가 같은 문장에 있으면 받는다
    assert grounded_year(1873, text, "크뢰벨", "교수") is None             # 원문에 없는 연도
    assert grounded_year(1872, "1872년 일이 있었다. 크뢰벨은 교수가 되었다.", "크뢰벨", "교수") is None  # 다른 문장
    assert grounded_year(99999, text, "크뢰벨", "교수") is None
    out = parse_response({"triples": [{"subject": "크뢰벨", "predicate": "저술함", "object": "『열과 일의 정밀측정』", "year": 1872}]},
                         "c1", {"저술함"}, None, text)
    assert out[0]["year"] == 1872


def test_add_rule_survives_replay_and_scopes_to_doc():
    raw = [{"subject": "피르나우", "predicate": "수행함", "object": "피르나우 저온 흑체 측정", "source_node_id": "c9"}]
    rules = [{"rule_type": "triple", "pair": ["피르나우 저온 흑체 측정", "기반함", "크뢰벨 보정"], "target_path": "@add",
              "source_value": "c9", "scope_paths": ["docA"], "target_value": None},
             {"rule_type": "class", "source_value": "크뢰벨 보정", "target_value": "TheoryOrConcept"}]
    out, rep = apply_rules_to_triples(raw, rules, "docA")
    add = [t for t in out if t.get("edited") == "added"]
    assert rep["counts"]["added"] == 1 and add[0]["source_node_id"] == "c9" and add[0]["object_type"] == "TheoryOrConcept"
    assert apply_rules_to_triples(raw, rules, "docB")[1]["counts"]["added"] == 0     # 다른 문서엔 안 넣음
    # 추출이 같은 트리플을 이미 냈으면 중복으로 넣지 않는다
    dup = raw + [{"subject": "피르나우 저온 흑체 측정", "predicate": "기반함", "object": "크뢰벨 보정", "source_node_id": "c9"}]
    out2, _ = apply_rules_to_triples(dup, rules, "docA")
    assert sum(1 for t in out2 if t["predicate"] == "기반함") == 1
    # @add 규칙은 이동 규칙으로 오해하지 않는다
    assert all(t["predicate"] != "@add" for t in out)
