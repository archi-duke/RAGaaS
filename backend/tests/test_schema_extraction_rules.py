"""스키마 추출 개선 (docs/design/schema/design-schema-editor.md §10) — 1글자 키, 계열 키, 유도 range·정의 채택."""
from collections import Counter

from app.services.retrieval.entity_linking import _compact
from app.services.schema_alignment import induction as ind
from app.services.schema_alignment import schema_editor as se


def test_compact_one_char_names_do_not_collide():
    assert _compact("줄") == "줄"
    assert _compact("암") == "암"
    assert _compact("줄") != _compact("빛")
    assert _compact("micro-service") == "microservice"
    assert _compact("") == ""


def test_family_key_strips_polarity_strength():
    k = se.family_key("has_positive_effect_on")
    assert k == se.family_key("has_moderate_negative_effect_on") == se.family_key("has_strong_negative_effect_on")
    assert k == "has_effect_on"
    assert se.family_key("requires") == "requires"


def test_usable_object_filters_noise():
    assert se._usable_object("단순성")
    assert not se._usable_object("-3점")
    assert not se._usable_object("규율이 흔들리면 효익이 소실된다는 점이 문제가 된다.")
    assert not se._usable_object("")


def _prof():
    return {"subj_preds": {"Microservices": Counter({"has_positive_effect_on": 2})},
            "obj_count": Counter({"확장성": 2, "단순성": 1}),
            "pred_count": Counter({"has_positive_effect_on": 2, "has_negative_effect_on": 1}),
            "pred_examples": {"has_positive_effect_on": ["Microservices → 확장성"]}}


def test_validate_induction_accepts_llm_range_and_description():
    data = {"classes": [{"name": "ArchitectureStyle", "description": "스타일", "members": ["Microservices"]},
                        {"name": "QualityAttribute", "description": "품질 속성", "members": ["확장성", "단순성"]}],
            "properties": [{"name": "has_positive_effect_on", "members": [], "domain": "ArchitectureStyle",
                            "range": "Quality Attribute", "description": "ArchitectureStyle | has_positive_effect_on | QualityAttribute"},
                           {"name": "has_negative_effect_on", "members": [], "domain": "ArchitectureStyle",
                            "range": "NoSuchClass", "description": "x"}]}
    r = ind.validate_induction(data, _prof())
    by = {p["name"]: p for p in r["properties"]}
    assert by["has_positive_effect_on"]["range"] == "QualityAttribute"     # 채택된 클래스명으로 정규화
    assert by["has_positive_effect_on"]["range_source"] == "llm"
    assert by["has_positive_effect_on"]["description"].startswith("ArchitectureStyle |")
    assert by["has_negative_effect_on"]["range"] == ""                   # 없는 클래스는 버림
    qa = next(c for c in r["classes"] if c["name"] == "QualityAttribute")
    assert set(qa["members"]) == {"확장성", "단순성"}                       # 목적어 엔티티도 멤버


def test_validate_induction_seed_range_not_overwritten():
    seed = {"classes": [{"name": "ArchitectureStyle", "description": "s"}, {"name": "QualityAttribute", "description": "q"}],
            "properties": [{"name": "has_positive_effect_on", "description": "시드 정의", "domain": "ArchitectureStyle",
                            "range": "QualityAttribute"}]}
    data = {"classes": [], "properties": [{"name": "has_positive_effect_on", "members": [], "range": "ArchitectureStyle",
                                           "description": "LLM 정의"}]}
    r = ind.validate_induction(data, _prof(), seed)
    p = next(p for p in r["properties"] if p["name"] == "has_positive_effect_on")
    assert p["range"] == "QualityAttribute" and p["description"] == "시드 정의"


def test_range_check_family_pooling_and_decisions(monkeypatch):
    import asyncio
    from app.services.retrieval.entity_linking import _compact
    qa = ["변경 용이성", "테스트 용이성", "관측성", "보안", "확장성"]
    objs = {
        "has_positive_effect_on": {x: 2 for x in qa} | {"-3점": 1},
        "has_negative_effect_on": {"단순성": 1, "일관성": 1, "operational complexity": 1, "관측성": 1, "보안": 1},
        "requires": {"규율": 1, "팀": 1, "도구": 1, "문서": 1, "테스트": 1, "변경 용이성": 1},
    }

    async def fake_cls(kb_id):
        return {_compact(x): "QualityAttribute" for x in qa}

    monkeypatch.setattr(se, "_class_index", fake_cls)
    monkeypatch.setattr(se, "_objects_of", lambda kb, names: objs.get(names[0], {}))
    props = [{"name": "has_positive_effect_on", "range": "", "members": []},
             {"name": "has_negative_effect_on", "range": "", "members": []},
             {"name": "requires", "range": "QualityAttribute", "range_source": "llm", "members": []}]
    chk = asyncio.run(se.range_check("kb", props))
    # 계열 합산: negative 단독이면 2/5=40% 지만 positive 와 합쳐 판정 → 같은 range
    assert chk["has_negative_effect_on"]["range"] == "QualityAttribute"
    assert chk["has_negative_effect_on"]["family"]
    gaps = {g["name"] for g in chk["has_negative_effect_on"]["gaps"]}
    assert {"단순성", "일관성", "operational complexity"} <= gaps
    assert "-3점" not in {g["name"] for g in chk["has_positive_effect_on"]["gaps"]}   # 수치 잡음 제외
    # LLM 선언 range 가 데이터 일치 1/6 < 0.3 → 비움
    assert chk["requires"]["decision"] == "dropped" and chk["requires"]["range"] == ""


def test_validate_induction_does_not_merge_family_relations():
    prof = _prof()
    prof["pred_count"] = Counter({"has_negative_effect_on": 3, "has_strong_negative_effect_on": 2, "부정_효과": 1})
    data = {"classes": [{"name": "QualityAttribute", "members": ["확장성"]}],
            "properties": [{"name": "has_negative_effect_on", "range": "QualityAttribute", "description": "X | has_negative_effect_on | Y",
                            "members": ["has_negative_effect_on", "has_strong_negative_effect_on", "부정_효과"]}]}
    r = ind.validate_induction(data, prof)
    by = {p["name"]: p for p in r["properties"]}
    assert "has_strong_negative_effect_on" not in by["has_negative_effect_on"]["members"]
    assert "부정_효과" in by["has_negative_effect_on"]["members"]                  # 같은 의미 별칭은 그대로
    assert by["has_strong_negative_effect_on"]["range"] == "QualityAttribute"     # 분리 후 같은 range
