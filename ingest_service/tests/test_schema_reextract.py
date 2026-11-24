"""스키마 기준 재추출(승격 L2) 단위 테스트."""
from app.core.schema_reextract import build_schema_text, parse_response


def test_schema_text_lists_properties_aliases_values():
    t = build_schema_text({
        "classes": [{"name": "ArchitecturePattern", "description": "스타일", "members": ["CQRS"]}],
        "properties": [{"name": "장점", "domain": "ArchitecturePattern", "aliases": ["장점", "has_advantage"],
                        "values": []},
                       {"name": "테스트_복잡도", "aliases": [], "values": ["높다", "중간"]}],
    })
    assert "ArchitecturePattern" in t and "CQRS" in t
    assert "별칭: has_advantage" in t and "값: 높다, 중간" in t


def test_parse_marks_out_of_schema_and_keeps_evidence():
    data = {"triples": [{"subject": "CQRS", "predicate": "장점", "object": "독립 확장"},
                        {"subject": "CQRS", "predicate": "invented", "object": "x"},
                        {"subject": "", "predicate": "장점", "object": "y"}],
            "out_of_schema": [{"subject": "CQRS", "predicate": "도입 시기", "object": "초기"}]}
    out = parse_response(data, "node-1", {"장점"})
    assert len(out) == 3
    assert all(t["source_node_id"] == "node-1" for t in out)
    assert [t["out_of_schema"] for t in out] == [False, True, True]
    assert parse_response(None, "n", set()) == []


def test_schema_text_includes_definition_and_direction():
    from app.core.schema_reextract import build_schema_text
    t = build_schema_text({"classes": [{"name": "Person", "description": "인물"}],
                           "properties": [{"name": "지도교수_of", "domain": "Person", "range": "Person",
                                           "description": "스승 → 제자", "aliases": ["지도교수_of"]}]})
    assert "- 지도교수_of (Person → Person): 스승 → 제자" in t


def test_domain_check_flips_or_moves_out_of_schema():
    from app.core.schema_reextract import build_type_index, parse_response
    spec = {"classes": [{"name": "Person", "members": ["드브로이", "막스 플랑크"]},
                        {"name": "TheoryOrConcept", "members": ["광양자_가설", "에너지 양자"]}],
            "properties": [{"name": "계승_발전", "domain": "TheoryOrConcept", "range": "TheoryOrConcept"},
                           {"name": "제안함", "domain": "Person", "range": "TheoryOrConcept"}]}
    ti = build_type_index(spec)
    allowed = {"계승_발전", "제안함"}
    out = parse_response({"triples": [
        {"subject": "드브로이", "predicate": "계승_발전", "object": "광양자_가설"},     # 인물 주어 → 스키마 밖
        {"subject": "에너지_양자", "predicate": "제안함", "object": "막스_플랑크"},       # 뒤집힘 → 바로잡음
        {"subject": "모르는_이름", "predicate": "제안함", "object": "광양자_가설"},       # 클래스 모름 → 그대로
    ]}, "n1", allowed, ti)
    assert out[0]["drop"] == "domain" and out[0]["domain_violation"] == "Person ≠ TheoryOrConcept"
    assert (out[1]["subject"], out[1]["object"], out[1]["direction_fixed"]) == ("막스_플랑크", "에너지_양자", True)
    assert not out[2]["out_of_schema"] and "direction_fixed" not in out[2]


def test_ungrounded_object_is_dropped():
    from app.core.schema_reextract import is_grounded, parse_response
    text = "피르나우는 1931년 세상을 떠났고, 할스테트 연구소는 다른 기관에 흡수되었다. 피르나우는 저온 흑체 복사를 측정했다."
    assert not is_grounded("1931년도_노벨_물리학상", text)          # '노벨'·'물리학상' 이 원문에 없음
    assert is_grounded("1931년", text)
    assert is_grounded("저온_흑체_측정", text)                     # '측정했다' ↔ '측정'
    out = parse_response({"triples": [{"subject": "아델하이트_피르나우", "predicate": "수상함", "object": "1931년도_노벨_물리학상"}]},
                         "n1", {"수상함"}, None, text)
    assert out[0]["drop"] == "ungrounded"


def test_vocabulary_value_still_needs_evidence():
    """값 어휘에 있는 표기라도 청크에 근거가 없으면 제외 (cqrs.md 'Availability' 사례, 2026-11-24)."""
    from app.core.grounding import build_alias_index
    from app.core.schema_reextract import parse_response
    rules = [{"rule_type": "value", "source_value": "가용성", "target_value": "Availability"}]
    aliases = build_alias_index(rules)
    cqrs = "- 감사 가능성 요구가 높으면 +2점. 명령 로그를 감사와 재처리의 근거로 활용할 수 있다."
    eda = "감사 가능성과 가용성에는 중간 정도의 긍정 효과가 있다."
    t = {"subject": "CQRS", "predicate": "has_moderate_positive_effect_on", "object": "Availability"}
    assert parse_response({"triples": [t]}, "n1", {"has_moderate_positive_effect_on"}, None, cqrs, aliases)[0]["drop"] == "ungrounded"
    out = parse_response({"triples": [{**t, "subject": "EDA"}]}, "n2", {"has_moderate_positive_effect_on"}, None, eda, aliases)
    assert "drop" not in out[0]      # 원래 표기 '가용성' 이 원문에 있음
