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
