"""
Entity Resolver (C안 — 문서 간 엔티티 동일성)

구조화 인제스트 시, 새 문서의 엔티티를 KB의 기존 인스턴스와 병합한다.

배경: 구조화 엔티티는 이미 inst/{id} 또는 inst/{label}로 URI가 정해져서
같은 id는 문서 간 자동 병합(Fuseki/Neo4j MERGE)되고 참조도 같은 URI로 연결된다.
공백은 "한 문서는 id로, 다른 문서는 이름(label)으로 같은 실체를 가리킬 때" —
URI가 달라 안 합쳐지는 경우다.

본 resolver는 **기존 KB 인스턴스를 label(rdfs:label / Neo4j name)로 조회**해
새 엔티티의 label이 정확히(대소문자 무시) 일치하면 기존 인스턴스의 식별자로
재매핑(병합)한다. 결정론적 exact-label 매칭(동명이인은 병합될 수 있음 — 구조화
데이터에서는 대개 의도된 동작; 퍼지/검토 기반 매칭은 후속 과제).
"""
from typing import Any, Dict, List

import requests

from app.core.config import settings

INST_NS = "http://rag.local/inst/"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


def _local_name(uri: str) -> str:
    return str(uri).split("/")[-1].split("#")[-1]


class EntityResolver:
    def __init__(self):
        self.base_url = settings.FUSEKI_URL
        self.auth = ("admin", "admin")

    async def existing_label_index(self, kb_id: str, graph_store: str) -> Dict[str, str]:
        """KB의 기존 인스턴스에 대해 {소문자 label: 기존 식별자(localname)} 인덱스를 만든다.

        같은 label에 여러 인스턴스가 있으면 하나로 축약된다(임의 1개 — 병합 대상).
        조회 실패/미지원 시 빈 dict(=병합 없음).
        """
        try:
            if graph_store == "fuseki":
                return self._fuseki_label_index(kb_id)
            elif graph_store == "neo4j":
                return await self._neo4j_label_index(kb_id)
        except Exception as e:
            print(f"[EntityResolver] label index failed ({graph_store}): {e}")
        return {}

    def _fuseki_label_index(self, kb_id: str) -> Dict[str, str]:
        dataset = f"kb_{kb_id.replace('-', '_')}"
        endpoint = f"{self.base_url}/{dataset}/sparql"
        # inst/ 엔티티의 rdfs:label만 (모든 named graph 합집합)
        query = (
            "SELECT ?s ?l WHERE { GRAPH ?g { ?s <%s> ?l } "
            'FILTER(STRSTARTS(STR(?s), "%s")) }' % (RDFS_LABEL, INST_NS)
        )
        r = requests.post(
            endpoint,
            data={"query": query},
            auth=self.auth,
            headers={"Accept": "application/sparql-results+json"},
            timeout=20,
        )
        if r.status_code != 200:
            return {}
        index: Dict[str, str] = {}
        for b in r.json().get("results", {}).get("bindings", []):
            label = b["l"]["value"].strip()
            local = _local_name(b["s"]["value"])
            if label:
                index.setdefault(label.lower(), local)
        return index

    async def _neo4j_label_index(self, kb_id: str) -> Dict[str, str]:
        from app.core.neo4j_connector import neo4j_connector
        neo4j_connector.connect()
        rows = neo4j_connector.execute_query(
            "MATCH (n:Entity {kb_id: $kb_id}) WHERE n.name IS NOT NULL RETURN DISTINCT n.name AS name",
            {"kb_id": kb_id},
        )
        index: Dict[str, str] = {}
        for row in rows or []:
            name = (row.get("name") or "").strip()
            if name:
                # Neo4j 식별자는 name 그 자체(MERGE 키). localname 정제와 일치시키기 위해
                # 구조화 extractor의 identity와 동일 규칙이 필요하나, Neo4j는 name 매칭이라
                # label==identity인 경우가 대부분. 소문자 키 -> 원본 name.
                index.setdefault(name.lower(), name)
        return index

    @staticmethod
    def apply_resolution(triples: List[Dict[str, Any]], label_index: Dict[str, str]) -> int:
        """새 문서의 triples에서, label이 기존 인스턴스와 일치하는 엔티티를 기존
        식별자로 재매핑(병합). in-place. 반환: 병합된 엔티티 수.

        - identity->label 은 이 문서의 label 술어 트리플에서 수집.
        - label이 기존 인덱스에 있고 기존 식별자가 현재와 다르면 remap.
        - remap을 모든 triple의 subject/object에 적용(리터럴은 remap 키가 아니므로 무영향).
        """
        if not label_index:
            return 0
        id_to_label = {
            t["subject"]: t["object"]
            for t in triples
            if t.get("predicate") == "label" and isinstance(t.get("object"), str)
        }
        remap: Dict[str, str] = {}
        for ident, label in id_to_label.items():
            existing = label_index.get(label.strip().lower())
            if existing and existing != ident:
                remap[ident] = existing
        if not remap:
            return 0
        for t in triples:
            if t.get("subject") in remap:
                t["subject"] = remap[t["subject"]]
            if t.get("object") in remap:
                t["object"] = remap[t["object"]]
        return len(remap)


entity_resolver = EntityResolver()
