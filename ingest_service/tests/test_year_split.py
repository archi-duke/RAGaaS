"""연도 분리 (D4 Y1) — 결정적 규칙."""
from app.core.schema_normalizer import split_year, apply_rules_to_triples


def test_paren_year():
    assert split_year("노벨 물리학상 (1933년)") == ("노벨 물리학상", 1933, "1933년")
    assert split_year("루스벨트 대통령에게 핵분열 경고 편지 (1939)") == ("루스벨트 대통령에게 핵분열 경고 편지", 1939, "1939")
    assert split_year("『새로운 두 과학』 (1638년 출간)") == ("『새로운 두 과학』", 1638, "1638년 출간")
    assert split_year("프린시페섬(1919년 일식)") == ("프린시페섬", 1919, "1919년 일식")


def test_lead_and_comma_year():
    assert split_year("1908년 쾰른 강연") == ("쾰른 강연", 1908, "1908년")
    assert split_year("1919년 11월 런던 왕립학회·왕립천문학회 합동 회의")[1:] == (1919, "1919년 11월")
    assert split_year("기체 분자 속도 분포, 1860년") == ("기체 분자 속도 분포", 1860, "1860년")


def test_not_split():
    for v in ["1887년", "1850년대", "1801~1803년 무렵", "1665년부터 1666년 (흑사병으로 대학 휴교)",
              "1919년 발표 이후", "1703년부터 왕립학회 회장", "기원전 384년", "패러데이의 역선을 수학적 언어로 번역하는 작업 (1850년대 중반)",
              "1642년 성탄절 (율리우스력, 그레고리력으로는 1643년 1월)", "측정 결과 1847년과 1850년", "노벨 물리학상", "1900년 10월", "1610년 초", "1900년 12월 14일", "1920년대 중반", None, 1933]:
        assert split_year(v) is None, v


def test_replay_merges_prize_and_keeps_old_triple_rule():
    raw = [
        {"subject": "피르나우", "predicate": "수상함", "object": "노벨 물리학상 (1933년)", "source_node_id": "c1"},
        {"subject": "보어", "predicate": "수상함", "object": "노벨 물리학상 (1922년)", "source_node_id": "c2"},
        {"subject": "갑", "predicate": "수상함", "object": "노벨 물리학상 (1918년)", "source_node_id": "c3"},
    ]
    rules = [{"rule_type": "triple", "pair": ["갑", "수상함", "노벨 물리학상 (1918년)"], "target_path": None}]
    out, rep = apply_rules_to_triples(raw, rules)
    assert rep["counts"]["year"] == 3 and rep["counts"]["triple_deleted"] == 1
    assert {t["object"] for t in out} == {"노벨 물리학상"}
    assert sorted(t["year"] for t in out) == [1922, 1933]
    # 입력은 그대로 (멱등)
    assert raw[0]["object"] == "노벨 물리학상 (1933년)"
    out2, _ = apply_rules_to_triples(raw, rules)
    assert out2 == out
