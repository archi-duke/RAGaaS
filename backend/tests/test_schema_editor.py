"""스키마 편집기 단위 테스트 (정규화·검증·변경 요약)."""
from app.services.schema_alignment import schema_editor as se

OLD = {
    "classes": [{"name": "Person", "description": "인물"}, {"name": "Theory", "description": "이론"}],
    "properties": [
        {"name": "제안함", "description": "인물 → 이론", "domain": "Person", "range": "Theory", "members": ["제안함", "제안"]},
        {"name": "영향_줌", "description": "A가 B에 영향", "domain": "Person", "range": "Person", "members": ["영향_줌"]},
    ],
}


def test_norm_spec_names_and_aliases():
    s = se._norm_spec({"classes": [{"name": " Theory Or Concept "}],
                       "properties": [{"name": "계승 발전", "aliases": "계승, 발전시킴, 계승", "domain": "Theory Or Concept"}]})
    assert s["classes"][0]["name"] == "TheoryOrConcept"
    p = s["properties"][0]
    assert p["name"] == "계승_발전"
    assert p["members"] == ["계승_발전", "계승", "발전시킴"]  # 대표 이름 맨 앞, 중복 제거
    assert p["domain"] == "TheoryOrConcept"


def test_validate_spec_errors():
    s = se._norm_spec({"classes": [{"name": "Person"}, {"name": "Person"}],
                       "properties": [{"name": "a", "domain": "Nope", "description": "x"},
                                      {"name": "b", "aliases": ["a"], "description": "y"}]})
    errors, warnings = se.validate_spec(s)
    assert any("클래스 이름 중복" in e for e in errors)
    assert any("domain 'Nope'" in e for e in errors)
    assert any("별칭 'a'" in e for e in errors)


def test_validate_spec_warns_missing_description():
    s = se._norm_spec({"classes": [{"name": "Person"}], "properties": [{"name": "a", "domain": "Person"}]})
    errors, warnings = se.validate_spec(s)
    assert not errors
    assert any("정의가 없습니다" in w for w in warnings)


def test_diff_spec_rename_vs_add_remove():
    new = se._norm_spec({
        "classes": [{"name": "Person", "description": "인물"}, {"name": "TheoryOrConcept", "renamed_from": "Theory"}],
        "properties": [
            {"name": "제안함", "description": "인물 → 이론·개념", "domain": "Person", "range": "TheoryOrConcept",
             "aliases": ["제안"]},
            {"name": "영향을_줌", "renamed_from": "영향_줌", "description": "A가 B에 영향", "domain": "Person", "range": "Person"},
            {"name": "발견함", "description": "인물 → 현상", "domain": "Person"},
        ]})
    d = se.diff_spec(OLD, new)
    assert d["classes_renamed"] == {"Theory": "TheoryOrConcept"}
    assert d["classes_removed"] == [] and d["classes_added"] == []
    assert d["properties_renamed"] == {"영향_줌": "영향을_줌"}
    assert d["properties_added"] == ["발견함"]
    assert d["properties_removed"] == []
    assert "제안함" in d["properties_changed"]  # 정의·range 변경
    assert "이름" in se._summary_text(d)


def test_diff_spec_no_change():
    new = se._norm_spec({"classes": OLD["classes"],
                         "properties": [{**p, "aliases": [a for a in p["members"] if a != p["name"]]} for p in OLD["properties"]]})
    d = se.diff_spec(OLD, new)
    assert se._summary_text(d) == "변경 없음"
