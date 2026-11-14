"""스키마 동치 감지기 단위 테스트 (docs/design-schema-mismatch.md §3)."""
from app.services.schema_alignment.equivalence import (
    catalog_signature,
    detect_path_groups,
    group_value_equivalents,
    path_similarity,
    value_canonical,
)


def _p(key, members, typ="enum", values=()):
    return {"key": key, "segments": key.split("."), "type": typ, "member_ids": set(members),
            "values": [{"uri": f"u:{v}", "label": v, "members": 1} for v in values]}


ALL = {f"s{i}" for i in range(10)}


def test_path_similarity_bases():
    assert path_similarity(["testingComplexity"], ["testing_complexity"]) == "normalized"
    assert path_similarity(["tradeoffs", "advantages"], ["tradeoffs", "pros"]) == "lexicon"
    assert path_similarity(["pros"], ["tradeoffs", "pros"]) == "nesting"
    # 공통 접두 4자만으로는 묶지 않는다
    assert path_similarity(["testingComplexity"], ["fit_signals", "testability"]) is None
    assert path_similarity(["testability"], ["testing_complexity"]) is None


def test_gate_member_overlap_and_prefix_coexistence():
    paths = [
        _p("observability_requirement", ALL),
        _p("fit_signals.observability_requirement", {"s1", "s2"}),
        _p("avoid_signals.team_size", {"s1", "s2"}),
        _p("fit_signals.team_size", {"s3"}),
        _p("avoid_signals.other", {"s3"}),     # avoid_signals·fit_signals 접두가 s3 에 공존
    ]
    assert detect_path_groups(paths) == []


def test_complementary_renamed_keys_grouped():
    paths = [
        _p("tradeoffs.pros", ALL - {"x"}, "text"),
        _p("tradeoffs.advantages", {"x"}, "text"),
        _p("testing_complexity", ALL, values=["high", "low"]),
        _p("testingComplexity", {"x"}, values=["높음"]),
    ]
    groups = {tuple(sorted(g["keys"])): g for g in detect_path_groups(paths)}
    assert ("tradeoffs.advantages", "tradeoffs.pros") in groups
    assert groups[("tradeoffs.advantages", "tradeoffs.pros")]["rep"] == "tradeoffs.pros"   # 커버리지 큰 쪽
    assert ("testingComplexity", "testing_complexity") in groups


def test_ignore_suppresses_and_rule_overrides_gate():
    paths = [_p("tradeoffs.pros", ALL - {"x"}), _p("tradeoffs.advantages", {"x"})]
    assert detect_path_groups(paths, ignore_pairs=[("tradeoffs.pros", "tradeoffs.advantages")]) == []
    both = [_p("a", ALL), _p("b", ALL)]   # 게이트 탈락이지만 사용자 규칙이면 인정
    assert detect_path_groups(both, rule_pairs=[("a", "b")])


def test_number_values_not_merged_and_synonym_values_merged():
    assert value_canonical("-3") != value_canonical("3")
    buckets = group_value_equivalents([_p("x", ALL, values=["high", "높음", "low", "-3", "3"])])
    labels = sorted(sorted(v["label"] for v in b) for b in buckets)
    assert labels == [["high", "높음"]]


def test_llm_value_groups_and_signature():
    buckets = group_value_equivalents([_p("x", ALL, values=["fast", "빠름"])], llm_value_groups=[["fast", "빠름"]])
    assert len(buckets) == 1
    a = [_p("x", ALL, values=["high"])]
    b = [_p("x", ALL | {"new"}, values=["high"])]
    assert catalog_signature(a) == catalog_signature(b)            # 문서 수 증가엔 불변
    assert catalog_signature(a) != catalog_signature(a + [_p("y", {"s1"})])
