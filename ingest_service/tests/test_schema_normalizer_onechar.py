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


def test_reextract_drops_absence_objects_and_prompt_requires_member_names():
    from app.core.schema_reextract import parse_response, build_messages
    data = {"triples": [{"subject": "Microservices", "predicate": "충돌", "object": "없음"},
                        {"subject": "Microservices", "predicate": "충돌", "object": "해당되지 않음"},
                        {"subject": "Microservices", "predicate": "has_positive_effect_on", "object": "테스트 용이성"}]}
    out = parse_response(data, "n1", {"충돌", "has_positive_effect_on"})
    assert [t.get("drop") for t in out] == ["absent", "absent", None]
    msg = build_messages("[클래스]", "text")[1]["content"]
    assert "번역도 대표 이름으로" in msg and "없음" in msg


def test_triple_rule_flip_swaps_subject_object_and_types():
    """방향 검증(D1)에서 승인한 뒤집기: 관계는 그대로, 주어·목적어와 타입을 교환."""
    rules = [{"rule_type": "triple", "pair": ["아인슈타인", "영향_줌", "뉴턴"], "target_path": "@flip", "status": "active"}]
    triples = [{"subject": "아인슈타인", "predicate": "영향_줌", "object": "뉴턴",
                "subject_type": "Person", "object_type": "Scientist"},
               {"subject": "패러데이", "predicate": "영향_줌", "object": "맥스웰"}]
    out, rep = apply_rules_to_triples(triples, rules)
    assert (out[0]["subject"], out[0]["predicate"], out[0]["object"]) == ("뉴턴", "영향_줌", "아인슈타인")
    assert out[0]["subject_type"] == "Scientist" and out[0]["object_type"] == "Person"
    assert out[0]["edited"] == "flipped"
    assert (out[1]["subject"], out[1]["object"]) == ("패러데이", "맥스웰")      # 다른 트리플은 그대로
    assert rep["counts"]["triple_flipped"] == 1
