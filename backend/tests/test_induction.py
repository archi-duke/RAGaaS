"""스키마 유도(승격 S2) 단위 테스트 (docs/design-graph-promotion.md §3(a))."""
from collections import Counter, defaultdict

from app.services.schema_alignment.induction import build_tbox_turtle, validate_induction


def _prof():
    return {
        "triples": [],
        "pred_count": Counter({"장점": 5, "장점은": 2, "has_advantage": 1, "단점": 3}),
        "pred_examples": defaultdict(list),
        "subj_preds": {"Micro-Frontend": Counter({"장점": 2}), "CQRS": Counter({"단점": 1}),
                       "Hexagonal 아키텍처": Counter({"장점": 1}), "Hexagonal": Counter({"장점": 1})},
        "obj_count": Counter({"중간": 2, "중간이다": 1, "high": 1}),
    }


def test_invented_names_dropped_and_representative_from_list():
    data = {
        "classes": [{"name": "architecture style", "members": ["Micro-Frontend", "CQRS", "없는엔티티"]},
                    {"name": "Dup", "members": ["CQRS"]}],          # 한 엔티티는 한 클래스에만
        "entity_merges": [{"canonical": "Hexagonal 아키텍처", "aliases": ["Hexagonal", "모르는것"]}],
        "properties": [{"name": "장점", "members": ["장점은", "has_advantage", "invented_prop"]},
                       {"name": "hasPros", "members": ["장점"]}],    # 새로 지은 대표 → 버림
        "value_groups": [{"canonical": "중간", "aliases": ["중간이다"]}],
    }
    r = validate_induction(data, _prof())
    assert r["classes"][0]["name"] == "ArchitectureStyle"
    assert r["classes"][0]["members"] == ["Micro-Frontend", "CQRS"]
    assert all(c["name"] != "Dup" for c in r["classes"])
    assert r["entity_merges"] == [{"canonical": "Hexagonal 아키텍처", "aliases": ["Hexagonal"]}]
    assert [p["name"] for p in r["properties"]] == ["장점"]
    assert r["properties"][0]["members"] == ["장점", "장점은", "has_advantage"]
    assert any("hasPros" in d for d in r["dropped"])
    assert r["value_groups"] == [{"canonical": "중간", "aliases": ["중간이다"]}]


def test_empty_response():
    assert validate_induction(None, _prof())["classes"] == []


def test_tbox_uses_data_uris():
    ttl = build_tbox_turtle([{"name": "ArchitectureStyle", "description": "스타일"}],
                            [{"name": "장점", "members": ["장점", "has_advantage"], "domain": "ArchitectureStyle"}])
    assert "<http://rag.local/class/ArchitectureStyle> a owl:Class" in ttl
    assert "<http://rag.local/rel/장점> a owl:ObjectProperty" in ttl
    assert 'skos:altLabel "has_advantage"' in ttl
    assert "example.org" not in ttl


SEED = {
    "classes": [{"name": "architecture style", "description": "아키텍처 스타일"}, {"name": "Person"}],
    "properties": {"장점_있음": "스타일 → 장점", "지도교수 of": "스승 → 제자"},
}


def test_seed_normalized_and_names_allowed():
    from app.services.schema_alignment.induction import build_induction_messages, normalize_seed
    seed = normalize_seed(SEED)
    assert [c["name"] for c in seed["classes"]] == ["ArchitectureStyle", "Person"]
    assert [p["name"] for p in seed["properties"]] == ["장점_있음", "지도교수_of"]   # 공백 → _
    data = {
        "classes": [{"name": "ArchitectureStyle", "members": ["Micro-Frontend", "CQRS"]}],
        "properties": [{"name": "장점_있음", "members": ["장점", "장점은", "없는관계"]},
                       {"name": "장점", "members": ["has_advantage", "장점"]}],   # 어간이 같은 묶음 → 시드로 합침
    }
    r = validate_induction(data, _prof(), seed)
    by = {p["name"]: p for p in r["properties"]}
    assert by["장점_있음"]["members"] == ["장점_있음", "장점", "장점은", "has_advantage"] and by["장점_있음"]["seed"]
    assert "장점" not in by
    assert by["지도교수_of"]["members"] == ["지도교수_of"] and by["지도교수_of"]["description"] == "스승 → 제자"
    names = [c["name"] for c in r["classes"]]
    assert names == ["ArchitectureStyle", "Person"]                                # 응답에 없던 시드 클래스도 포함
    assert r["classes"][0]["description"] == "아키텍처 스타일"
    msgs = build_induction_messages(_prof(), seed)
    assert "지도교수_of: 스승 → 제자" in msgs[1]["content"] and "{seed_text}" not in msgs[1]["content"]
    assert "{seed_text}" not in build_induction_messages(_prof())[1]["content"]


def test_tbox_range_and_comment():
    ttl = build_tbox_turtle([{"name": "Person"}],
                            [{"name": "지도교수_of", "members": ["지도교수_of"], "domain": "Person",
                              "range": "Person", "description": "스승 → 제자"}])
    assert "rdfs:range <http://rag.local/class/Person>" in ttl
    assert 'rdfs:comment "스승 → 제자"' in ttl


def test_existing_name_group_folds_into_seed():
    from app.services.schema_alignment.induction import normalize_seed, seed_target_for
    seed = normalize_seed({"properties": ["지도교수_of", "수상함", "일반화함", "계승_발전", "확인함", "소속"]})
    sp = seed["properties"]
    assert seed_target_for("지도", sp) == "지도교수_of"
    assert seed_target_for("수상", sp) == "수상함"
    assert seed_target_for("일반화한", sp) == "일반화함"
    assert seed_target_for("계승하다", sp) == "계승_발전"
    assert seed_target_for("발표", sp) is None
    prof = _prof()
    prof["pred_count"].update({"지도": 3, "지도하다": 1})
    r = validate_induction({"properties": [{"name": "지도", "members": ["지도하다"]}]}, prof, seed)
    by = {p["name"]: p for p in r["properties"]}
    assert "지도" not in by and by["지도교수_of"]["members"] == ["지도교수_of", "지도", "지도하다"]
