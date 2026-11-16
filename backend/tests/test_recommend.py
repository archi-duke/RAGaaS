"""AI 추천 처리안 검증 (docs/design-schema-editor.md §14)."""
from app.services.schema_alignment import recommend as rc

CTX = {"spec": {"classes": [{"name": "ArchitectureStyle"}, {"name": "QualityAttribute"}, {"name": "Requirement"}],
                "properties": [{"name": "is_suitable_for", "domain": "ArchitectureStyle", "range": "Requirement", "description": "x"},
                               {"name": "관련_패턴", "domain": "ArchitectureStyle", "range": "ArchitectureStyle", "description": "y"}]},
       "problems": [{"subject": "Clean Architecture", "predicate": "is_suitable_for", "object": "Microservices",
                     "source": "c1", "doc_id": "d1", "doc": "clean.md"}]}


def test_validate_actions_filters_unknown_names_and_resolves_refs():
    data = {"actions": [
        {"type": "set_definition", "property": "is_suitable_for", "description": "새 정의", "confidence": 0.9},
        {"type": "set_definition", "property": "없는관계", "description": "x"},
        {"type": "set_range", "property": "is_suitable_for", "range": "NoClass"},
        {"type": "move_triples", "triples": ["T0"], "target_property": "관련_패턴", "confidence": 0.8},
        {"type": "move_triples", "triples": ["T9"], "target_property": "관련_패턴"},
        {"type": "add_class", "name": "Design Principle", "description": "원칙", "members": ["단일 책임"]},
        {"type": "assign_members", "class": "DesignPrinciple", "entities": ["개방 폐쇄"]},
        {"type": "delete_triples", "triples": ["T0"]},
    ]}
    out = rc.validate_actions(data, CTX)
    types = [a["type"] for a in out]
    assert types == ["set_definition", "move_triples", "add_class", "assign_members", "delete_triples"]
    mv = out[1]
    assert mv["triples"][0]["subject"] == "Clean Architecture" and mv["triples"][0]["source"] == "c1"
    assert out[2]["name"] == "DesignPrinciple"          # 새 클래스는 같은 응답의 멤버 지정 대상이 될 수 있다


def test_nested_merge_gets_warning_and_low_confidence():
    out = rc.validate_actions({"actions": [{"type": "merge_entities", "canonical": "확장성", "aliases": ["확장성 요구"], "confidence": 0.9}]}, CTX)
    assert out[0]["confidence"] <= 0.4 and "포함 관계" in out[0]["warning"]


def test_simulated_rules_and_schema_actions():
    acts = rc.validate_actions({"actions": [
        {"type": "set_range", "property": "is_suitable_for", "range": "QualityAttribute"},
        {"type": "move_triples", "triples": ["T0"], "target_property": "관련_패턴"},
        {"type": "merge_entities", "canonical": "운영 복잡도", "aliases": ["operational complexity"]}]}, CTX)
    spec = rc._apply_schema_actions(CTX["spec"], acts)
    assert next(p for p in spec["properties"] if p["name"] == "is_suitable_for")["range"] == "QualityAttribute"
    rules = rc._simulated_rules(acts)
    assert {r["rule_type"] for r in rules} == {"triple", "entity"}
    assert next(r for r in rules if r["rule_type"] == "triple")["target_path"] == "관련_패턴"
