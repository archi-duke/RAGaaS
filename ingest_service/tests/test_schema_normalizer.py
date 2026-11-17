"""KB 스키마 매핑 규칙 적용(schema_normalizer) 단위 테스트 (docs/design/schema/design-schema-mismatch.md §5)."""
import copy

from app.core.schema_normalizer import apply_to_triples, compact, normalize_record, validate_rule

BASE = {
    "id": "space-based",
    "name": "Space-Based",
    "testingComplexity": "높음",
    "operational_complexity": "High",
    "tradeoffs": {"advantages": ["a1", "a2"], "pros": ["p1"], "disadvantages": ["d1"]},
    "avoid_signals": {"team_size": "소규모"},
    "summary": "처리 단위 복제로 확장성이 높음 — 문장 속 '높음'은 바뀌면 안 됨",
    "quality_attributes": [{"attribute": "x", "effect": "positive", "strength": "높음"}],
}


def _rec():
    return copy.deepcopy(BASE)


def test_compact_handles_camel_case():
    assert compact("testingComplexity") == compact("testing_complexity")


def test_key_rename_with_merge_and_nesting():
    r = _rec()
    rep = normalize_record(r, [
        {"id": "k1", "rule_type": "key", "source_path": "tradeoffs.advantages", "target_path": "tradeoffs.pros"},
        {"id": "k2", "rule_type": "key", "source_path": "avoid_signals.team_size", "target_path": "team.size"},
    ])
    assert r["tradeoffs"]["pros"] == ["p1", "a1", "a2"]          # 기존 리스트에 병합
    assert "advantages" not in r["tradeoffs"]
    assert r["team"]["size"] == "소규모" and "avoid_signals" not in r   # 이동 후 빈 부모 제거
    assert rep["merged"]


def test_key_rule_inside_array_items():
    r = _rec()
    normalize_record(r, [{"id": "k", "rule_type": "key", "source_path": "quality_attributes.strength",
                          "target_path": "quality_attributes.level"}])
    assert r["quality_attributes"][0]["level"] == "높음"


def test_value_rule_whole_value_only_and_scope():
    r = _rec()
    normalize_record(r, [{"id": "v", "rule_type": "value", "source_value": "높음", "target_value": "high",
                          "scope_paths": ["*"]}])
    assert r["testingComplexity"] == "high"
    assert r["quality_attributes"][0]["strength"] == "high"
    assert "높음" in r["summary"]                                   # 문장 속은 그대로
    r2 = _rec()
    normalize_record(r2, [{"id": "v", "rule_type": "value", "source_value": "높음", "target_value": "high",
                           "scope_paths": ["testingComplexity"]}])
    assert r2["testingComplexity"] == "high" and r2["quality_attributes"][0]["strength"] == "높음"


def test_auto_normalization_only_exact_compact_and_protects_id():
    r = _rec()
    rep = normalize_record(r, [], {"paths": ["testing_complexity", "operational_complexity", "id"],
                                   "enum_values": {"operational_complexity": ["high", "low"]}})
    assert "testing_complexity" in r and "testingComplexity" not in r
    assert r["operational_complexity"] == "high"                    # High → high
    assert r["id"] == "space-based"
    assert {"kind": "key", "source": "testingComplexity", "target": "testing_complexity"} in rep["auto"]
    # 동의어(소규모→small)는 자동 적용하지 않는다
    assert r["avoid_signals"]["team_size"] == "소규모"


def test_validate_rule_and_text_triples():
    assert validate_rule({"rule_type": "key", "source_path": "a", "target_path": "a"})
    assert validate_rule({"rule_type": "bogus"})
    assert validate_rule({"rule_type": "value", "source_value": "x", "target_value": "y"}) is None
    triples = [{"subject": "s", "predicate": "advantages", "object": "o"}]
    assert apply_to_triples(triples, [{"rule_type": "key", "source_path": "advantages", "target_path": "pros"}]) == 1
    assert triples[0]["predicate"] == "pros"


def test_apply_rules_to_triples_replay():
    from app.core.schema_normalizer import apply_rules_to_triples
    raw = [
        {"subject": "Hexagonal", "predicate": "장점은", "object": "중간이다", "source_node_id": "c1"},
        {"subject": "Hexagonal 아키텍처", "predicate": "has_advantage", "object": "x", "source_node_id": "c1"},
        {"subject": "Hexagonal", "predicate": "is", "object": "Hexagonal 아키텍처", "source_node_id": "c2"},
    ]
    rules = [
        {"rule_type": "entity", "source_value": "Hexagonal", "target_value": "Hexagonal 아키텍처"},
        {"rule_type": "key", "source_path": "장점은", "target_path": "장점"},
        {"rule_type": "key", "source_path": "has_advantage", "target_path": "장점"},
        {"rule_type": "value", "source_value": "중간이다", "target_value": "중간"},
        {"rule_type": "class", "source_value": "Hexagonal 아키텍처", "target_value": "ArchitecturePattern"},
    ]
    out, rep = apply_rules_to_triples(raw, rules)
    assert len(out) == 2                                     # 병합으로 생긴 자기 루프 제거
    assert {t["predicate"] for t in out} == {"장점"}
    assert out[0]["object"] == "중간" and out[0]["subject_type"] == "ArchitecturePattern"
    assert raw[0]["subject"] == "Hexagonal"                  # 입력 불변 → 멱등
    assert apply_rules_to_triples(raw, rules)[0] == out
