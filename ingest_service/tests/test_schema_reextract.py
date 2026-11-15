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
    assert out[0]["out_of_schema"] and out[0]["domain_violation"] == "Person ≠ TheoryOrConcept"
    assert (out[1]["subject"], out[1]["object"], out[1]["direction_fixed"]) == ("막스_플랑크", "에너지_양자", True)
    assert not out[2]["out_of_schema"] and "direction_fixed" not in out[2]
