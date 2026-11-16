"""1글자 엔티티 class 규칙이 다른 1글자 엔티티로 번지지 않는다."""
from app.core.schema_normalizer import apply_rules_to_triples, compact


def test_one_char_class_rule_does_not_spread():
    rules = [{"rule_type": "class", "source_value": "줄", "target_value": "Person", "status": "active"}]
    triples = [{"subject": "줄", "predicate": "영향_줌", "object": "크뢰벨"},
               {"subject": "암", "predicate": "원인", "object": "빛"}]
    out, rep = apply_rules_to_triples(triples, rules)
    assert out[0].get("subject_type") == "Person"
    assert "subject_type" not in out[1] and "object_type" not in out[1]
    assert compact("줄") != compact("암")
