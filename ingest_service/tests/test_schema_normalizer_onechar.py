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


def test_entity_rules_follow_chain_and_triple_rules_survive_merge():
    """D2: '아르놀트 조머펠트 → 조머펠트'(기존) + '조머펠트 → 아르놀드 조머펠트'(병합) 는 끝까지 따라가고,
    병합 전 이름으로 만든 뒤집기 규칙도 계속 적용된다."""
    rules = [
        {"rule_type": "entity", "source_value": "아르놀트 조머펠트", "target_value": "조머펠트", "status": "active"},
        {"rule_type": "entity", "source_value": "조머펠트", "target_value": "아르놀드 조머펠트", "status": "active"},
        {"rule_type": "triple", "pair": ["파울리", "지도교수_of", "조머펠트"], "target_path": "@flip", "status": "active"},
    ]
    triples = [{"subject": "아르놀트 조머펠트", "predicate": "지도교수_of", "object": "하이젠베르크"},
               {"subject": "파울리", "predicate": "지도교수_of", "object": "조머펠트"}]
    out, rep = apply_rules_to_triples(triples, rules)
    assert (out[0]["subject"], out[0]["object"]) == ("아르놀드 조머펠트", "하이젠베르크")
    assert (out[1]["subject"], out[1]["object"]) == ("아르놀드 조머펠트", "파울리")      # 뒤집기 유지
    # 순환 규칙은 끊는다
    cyc = [{"rule_type": "entity", "source_value": "A", "target_value": "B", "status": "active"},
           {"rule_type": "entity", "source_value": "B", "target_value": "A", "status": "active"}]
    out2, _ = apply_rules_to_triples([{"subject": "A", "predicate": "p", "object": "C"}], cyc)
    assert out2[0]["subject"] in ("A", "B")


def test_entity_rename_applies_when_normalized_keys_collide():
    """'맥스웰' → 'J. C. 맥스웰' 처럼 정규화 키가 같은 표기 변경도 적용한다 (체인 해석이 막지 않게)."""
    rules = [{"rule_type": "entity", "source_value": "제임스 클러크 맥스웰", "target_value": "맥스웰", "status": "active"},
             {"rule_type": "entity", "source_value": "맥스웰", "target_value": "J. C. 맥스웰", "status": "active"}]
    out, _ = apply_rules_to_triples([{"subject": "맥스웰", "predicate": "p", "object": "x"},
                                     {"subject": "제임스 클러크 맥스웰", "predicate": "p", "object": "y"}], rules)
    assert [t["subject"] for t in out] == ["J. C. 맥스웰", "J. C. 맥스웰"]


def test_merged_name_keeps_class_of_original():
    """병합 뒤 새 이름에 클래스 규칙이 없으면 원래 이름의 클래스를 이어받는다."""
    rules = [{"rule_type": "class", "source_value": "조머펠트", "target_value": "Person", "status": "active"},
             {"rule_type": "entity", "source_value": "조머펠트", "target_value": "아르놀드 조머펠트", "status": "active"}]
    out, _ = apply_rules_to_triples([{"subject": "조머펠트", "predicate": "지도교수_of", "object": "파울리"}], rules)
    assert out[0]["subject"] == "아르놀드 조머펠트" and out[0]["subject_type"] == "Person"
