"""AI 추천 처리안 검증 (docs/design-schema-editor.md §14)."""
from app.services.schema_alignment import recommend as rc

CTX = {"spec": {"classes": [{"name": "ArchitectureStyle"}, {"name": "QualityAttribute"}, {"name": "Requirement"}],
                "properties": [{"name": "is_suitable_for", "domain": "ArchitectureStyle", "range": "Requirement", "description": "x"},
                               {"name": "관련_패턴", "domain": "ArchitectureStyle", "range": "ArchitectureStyle", "description": "y"}]},
       "problems": [{"subject": "Clean Architecture", "predicate": "is_suitable_for", "object": "Microservices",
                     "source": "c1", "doc_id": "d1", "doc": "clean.md"}],
       # 그래프에 실재하는 엔티티 (정규화 키)
       "entity_keys": {"단일책임", "개방폐쇄", "확장성", "확장성요구", "운영복잡도", "operationalcomplexity", "단순성"}}


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


def test_unknown_entities_dropped():
    ctx = {**CTX, "entity_keys": {"단순성"}, "spec": {**CTX["spec"], "member_gaps": {}, "range_violations": []}}
    out = rc.validate_actions({"actions": [
        {"type": "assign_members", "class": "QualityAttribute", "entities": ["단순성", "지어낸이름"]},
        {"type": "merge_entities", "canonical": "없는대표", "aliases": ["단순성"]}]}, ctx)
    assert out[0]["entities"] == ["단순성"] and len(out) == 1
    assert any("지어낸이름" in d for d in ctx["dropped"])


def test_memory_filters_rejected_and_decided():
    mem = {"rejected": [{"sig": s} for s in (rc.rejection_sigs({"type": "assign_members", "class": "QualityAttribute", "entities": ["traffic control"]})
                                           + rc.rejection_sigs({"type": "delete_triples", "triples": [CTX["problems"][0]]}))],
           "decided": {"range:is_suitable_for": {"value": "Requirement"}}}
    ctx = {**CTX, "memory": mem, "entity_keys": CTX["entity_keys"] | {"trafficcontrol"}}
    out = rc.validate_actions({"actions": [
        {"type": "assign_members", "class": "QualityAttribute", "entities": ["traffic control", "단순성"]},
        {"type": "set_range", "property": "is_suitable_for", "range": "QualityAttribute"},
        {"type": "set_range", "property": "is_suitable_for", "range": "Requirement"},
        {"type": "delete_triples", "triples": ["T0"]}]}, ctx)
    assert [a["type"] for a in out] == ["assign_members", "set_range"]
    assert out[0]["entities"] == ["단순성"] and out[1]["range"] == "Requirement"
    assert any("확정한 결정 번복" in d for d in ctx["dropped"])


def test_prompt_includes_memory_block():
    ctx = {**CTX, "memory": {"rejected": [{"sig": "x", "text": "traffic control 를 QualityAttribute 멤버로", "reason": ""}],
                             "decided": {"range:consistency_model": {"value": "QualityAttribute"}}},
           "spec": {**CTX["spec"], "member_gaps": {}, "range_violations": [], "out_of_schema": []}}
    msg = rc.build_messages(ctx)[1]["content"]
    assert "거절한 안" in msg and "traffic control" in msg and "consistency_model 의 range = QualityAttribute" in msg


def test_rejected_delete_also_blocks_move_of_same_triple():
    sig = rc.rejection_sigs({"type": "delete_triples", "triples": [CTX["problems"][0]]})
    ctx = {**CTX, "memory": {"rejected": [{"sig": s} for s in sig], "decided": {}}}
    out = rc.validate_actions({"actions": [{"type": "move_triples", "triples": ["T0"], "target_property": "관련_패턴"}]}, ctx)
    assert out == []


def test_rejected_move_blocks_only_same_target():
    sig = rc.rejection_sigs({"type": "move_triples", "triples": [CTX["problems"][0]], "target_property": "관련_패턴"})
    ctx = {**CTX, "memory": {"rejected": [{"sig": s} for s in sig], "decided": {}}}
    out = rc.validate_actions({"actions": [{"type": "move_triples", "triples": ["T0"], "target_property": "관련_패턴"},
                                           {"type": "move_triples", "triples": ["T0"], "target_property": "is_suitable_for"}]}, ctx)
    assert [a["target_property"] for a in out] == ["is_suitable_for"]
