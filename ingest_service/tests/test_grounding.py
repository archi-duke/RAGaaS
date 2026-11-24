"""트리플 근거 검사·부호 보존 테스트 (2026-11-24)."""
from app.core.grounding import (build_alias_index, filter_ungrounded, is_grade_value,
                                object_grounded)


def test_grade_values_skip_check():
    text = "확장성 요구가 높으면 +3점."
    for v in ("높다", "높음", "낮다", "중간"):
        assert is_grade_value(v)
        assert object_grounded(v, text)
    assert not is_grade_value("Availability")
    assert not is_grade_value("감사 가능성")


def test_alias_from_rules_and_dictionary():
    idx = build_alias_index(
        [{"rule_type": "value", "source_value": "가용성", "target_value": "Availability"},
         {"rule_type": "key", "source_path": "a", "target_path": "b"}],
        {"사이드카 프록시": {"variants": ["sidecar proxy"]}})
    assert object_grounded("Availability", "가용성에는 중간 정도의 긍정 효과", idx)
    assert not object_grounded("Availability", "감사 가능성에는 긍정 효과", idx)
    assert object_grounded("사이드카 프록시", "sidecar proxy 를 붙인다", idx)


def test_filter_keeps_unknown_chunks_and_drops_ungrounded():
    triples = [
        {"subject": "뉴턴", "predicate": "저술함", "object": "『광학』", "source_node_id": "a"},
        {"subject": "뉴턴", "predicate": "저술함", "object": "『광학』", "source_node_id": "b"},
        {"subject": "뉴턴", "predicate": "저술함", "object": "『프린키피아』", "source_node_id": "z"},
    ]
    kept, dropped = filter_ungrounded(triples, {"a": "뉴턴은 『광학』을 펴냈다.", "b": "앤더슨은 양전자를 발견했다."})
    assert [t["source_node_id"] for t in kept] == ["a", "z"]     # z: 원문을 모르면 통과
    assert [t["source_node_id"] for t in dropped] == ["b"]


def test_sign_is_kept_in_uri():
    from app.core.fuseki_connector import FusekiConnector
    from app.core.structured_extractor import _sanitize_uri
    c = FusekiConnector()
    assert c._sanitize_uri("+3점") == "plus3점"
    assert c._sanitize_uri("-3점") == "minus3점"
    assert c._sanitize_uri("+3점") != c._sanitize_uri("-3점")
    assert c._sanitize_uri("강한 일관성 요구가 높으면 -2점") == "강한_일관성_요구가_높으면_minus2점"
    assert c._sanitize_uri("3-5년") == "3_5년"            # 범위의 '-' 는 부호가 아니다
    assert c._sanitize_uri("Micro-Frontend") == "Micro_Frontend"
    assert _sanitize_uri("-3점") == c._sanitize_uri("-3점")  # 구조화 추출과 같은 규칙
