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
