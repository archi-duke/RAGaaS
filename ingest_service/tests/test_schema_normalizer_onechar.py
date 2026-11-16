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


def test_triple_rules_move_and_delete_after_normalization():
    rules = [
        {"rule_type": "entity", "source_value": "operational complexity", "target_value": "운영 복잡도", "status": "active"},
        # 그래프 표기(정규화 뒤) 기준으로 매칭
        {"rule_type": "triple", "pair": ["Modular Monolith", "has_negative_effect_on", "Microservices"],
         "target_path": "관련_패턴", "status": "active"},
        {"rule_type": "triple", "pair": ["팀 규모가 작음", "has_negative_effect_on", "규율을 유지하기 어렵다"],
         "target_path": None, "status": "active"},
        {"rule_type": "triple", "pair": ["A", "p", "운영 복잡도"], "target_path": None, "status": "active"},
    ]
    triples = [{"subject": "Modular Monolith", "predicate": "has_negative_effect_on", "object": "Microservices"},
               {"subject": "팀 규모가 작음", "predicate": "has_negative_effect_on", "object": "규율을 유지하기 어렵다"},
               {"subject": "A", "predicate": "p", "object": "operational complexity"},
               {"subject": "B", "predicate": "p", "object": "operational complexity"}]
    out, rep = apply_rules_to_triples(triples, rules)
    assert {"subject": "Modular Monolith", "predicate": "관련_패턴"}.items() <= out[0].items()
    assert len(out) == 2 and out[1]["subject"] == "B" and out[1]["object"] == "운영 복잡도"
    assert rep["counts"]["triple_moved"] == 1 and rep["counts"]["triple_deleted"] == 2
