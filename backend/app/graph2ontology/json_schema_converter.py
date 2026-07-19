"""JSON Schema → OWL TBox 변환기 (C안 Phase 3, design-structured-json-yaml-ontology.md §7/§9)

JSON Schema 문서(definitions/$defs + properties)를 결정론적으로 owl:Class /
owl:ObjectProperty / owl:DatatypeProperty로 매핑한다. LLM을 사용하지 않으며,
URI 스킴은 `ontology_promoter.py`(A안 승격 경로)와 동일하게 맞춰
(`http://example.org/onto/class/{Name}`, `http://example.org/onto/prop/{name}`)
스키마 기반 TBox와 승격 기반 TBox가 서로 정합적으로 병합/참조될 수 있게 한다.
"""

import re
from typing import Any, Optional
from urllib.parse import quote

from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, XSD


CLASS_NS = "http://example.org/onto/class/"
PROP_NS = "http://example.org/onto/prop/"

_SCALAR_TYPE_TO_XSD = {
    "string": XSD.string,
    "integer": XSD.integer,
    "number": XSD.double,
    "boolean": XSD.boolean,
}


def is_json_schema(data: Any) -> bool:
    """`data`가 JSON Schema 문서(데이터 인스턴스가 아님)인지 보수적으로 판정한다."""
    if not isinstance(data, dict):
        return False
    if "$schema" in data:
        return True
    if "$defs" in data:
        return True
    if "definitions" in data:
        return True
    if data.get("type") == "object" and isinstance(data.get("properties"), dict):
        return True
    return False


def _sanitize_class_name(name: str) -> str:
    """클래스명을 PascalCase-호환 형태로 정제(영숫자/언더스코어만 유지, 첫 글자 대문자)."""
    if not isinstance(name, str) or not name:
        return "Unnamed"
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "", name)
    if not cleaned:
        return "Unnamed"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned[0].upper() + cleaned[1:]


def _sanitize_prop_name(name: str) -> str:
    """속성명을 정제(영숫자/언더스코어만 유지). 대소문자는 원형 유지."""
    if not isinstance(name, str) or not name:
        return "unnamed"
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "", name)
    if not cleaned:
        return "unnamed"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _class_uri(name: str) -> URIRef:
    return URIRef(f"{CLASS_NS}{quote(name)}")


def _prop_uri(name: str) -> URIRef:
    return URIRef(f"{PROP_NS}{quote(name)}")


def _ref_target_name(ref: str) -> Optional[str]:
    """`$ref` 문자열(e.g. "#/definitions/Foo", "#/$defs/Foo")에서 대상 클래스명을 추출."""
    if not isinstance(ref, str) or not ref:
        return None
    tail = ref.rsplit("/", 1)[-1]
    if not tail or tail == ref and "/" not in ref:
        # ref가 fragment 없이 단순 이름 하나뿐인 경우도 방어적으로 허용
        tail = ref.lstrip("#/")
    return tail or None


def _collect_named_classes(schema: dict) -> dict:
    """definitions/$defs 아래의 named class 스키마 + (있다면) 루트 클래스를 수집.

    반환: {sanitized_class_name: class_schema_dict}
    """
    classes: dict = {}

    for container_key in ("definitions", "$defs"):
        container = schema.get(container_key)
        if not isinstance(container, dict):
            continue
        for raw_name, node in container.items():
            if not isinstance(node, dict):
                continue
            name = _sanitize_class_name(raw_name)
            classes[name] = node

    # 루트 자체가 type:object + title이면 루트도 클래스로 취급
    if schema.get("type") == "object" and isinstance(schema.get("title"), str) and schema.get("title"):
        root_name = _sanitize_class_name(schema["title"])
        classes.setdefault(root_name, schema)

    return classes


def _resolve_scalar_range(value_schema: dict):
    """스칼라 값 스키마 → xsd 타입"""
    if not isinstance(value_schema, dict):
        return XSD.string
    fmt = value_schema.get("format")
    if isinstance(fmt, str) and fmt == "date-time":
        return XSD.dateTime
    vtype = value_schema.get("type")
    if isinstance(vtype, str) and vtype in _SCALAR_TYPE_TO_XSD:
        return _SCALAR_TYPE_TO_XSD[vtype]
    return XSD.string


def convert_json_schema_to_tbox(schema: dict) -> tuple[Graph, dict]:
    """JSON Schema → (rdflib.Graph TBox, summary) 결정론적 변환.

    summary = {"classes": [localname...], "properties": [localname...]} (정렬된 고유 목록)
    """
    g = Graph()
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)

    class_names: set = set()
    prop_names: set = set()

    if not isinstance(schema, dict):
        return g, {"classes": [], "properties": []}

    try:
        named_classes = _collect_named_classes(schema)
    except Exception:
        named_classes = {}

    # 클래스 선언 + 라벨
    for cls_name in named_classes.keys():
        try:
            cls_uri = _class_uri(cls_name)
            g.add((cls_uri, RDF.type, OWL.Class))
            g.add((cls_uri, RDFS.label, Literal(cls_name)))
            class_names.add(cls_name)
        except Exception:
            continue

    # 속성(도메인=클래스) + allOf/$ref → subClassOf
    for cls_name, node in named_classes.items():
        if not isinstance(node, dict):
            continue
        cls_uri = _class_uri(cls_name)

        # allOf 내 $ref → rdfs:subClassOf
        all_of = node.get("allOf")
        if isinstance(all_of, list):
            for item in all_of:
                if not isinstance(item, dict):
                    continue
                ref = item.get("$ref")
                parent_name = _ref_target_name(ref) if ref else None
                if parent_name:
                    parent_name = _sanitize_class_name(parent_name)
                    if parent_name in named_classes:
                        try:
                            g.add((cls_uri, RDFS.subClassOf, _class_uri(parent_name)))
                        except Exception:
                            pass

        properties = node.get("properties")
        if not isinstance(properties, dict):
            continue

        for raw_pname, value_schema in properties.items():
            try:
                if not isinstance(value_schema, dict):
                    continue
                pname = _sanitize_prop_name(raw_pname)
                prop_uri = _prop_uri(pname)

                target_schema = value_schema
                # array → items를 값 스키마로 사용(다중값, MVP에서는 카디널리티 미부여)
                if target_schema.get("type") == "array":
                    items = target_schema.get("items")
                    if isinstance(items, dict):
                        target_schema = items
                    else:
                        # items가 없거나 형식이 다르면 defensive하게 스칼라로 취급
                        target_schema = {}

                ref = target_schema.get("$ref") if isinstance(target_schema, dict) else None
                is_object_ref = bool(ref)
                is_inline_object = (
                    isinstance(target_schema, dict)
                    and target_schema.get("type") == "object"
                    and isinstance(target_schema.get("title"), str)
                    and target_schema.get("title")
                )

                if is_object_ref or is_inline_object:
                    g.add((prop_uri, RDF.type, OWL.ObjectProperty))
                    g.add((prop_uri, RDFS.domain, cls_uri))
                    prop_names.add(pname)

                    range_name = None
                    if is_object_ref:
                        range_name = _ref_target_name(ref)
                    elif is_inline_object:
                        range_name = target_schema.get("title")

                    if range_name:
                        range_name = _sanitize_class_name(range_name)
                        # 참조 대상 클래스가 (아직) 없어도 range URI 자체는 결정론적으로 생성 가능하게
                        # named_classes에 있으면 그 URI, 없어도 동일 네이밍 스킴으로 range를 건다.
                        try:
                            g.add((prop_uri, RDFS.range, _class_uri(range_name)))
                        except Exception:
                            pass
                else:
                    g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
                    g.add((prop_uri, RDFS.domain, cls_uri))
                    g.add((prop_uri, RDFS.range, _resolve_scalar_range(target_schema)))
                    prop_names.add(pname)
            except Exception:
                # 개별 속성 처리 실패는 전체 변환을 막지 않는다(방어적 처리)
                continue

    summary = {
        "classes": sorted(class_names),
        "properties": sorted(prop_names),
    }
    return g, summary
