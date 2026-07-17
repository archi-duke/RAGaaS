"""
Neo4j Graph Store Connector

기존 RAGaaS의 Neo4j에 트리플을 저장합니다.
"""
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase, AsyncGraphDatabase

from app.core.config import settings


class Neo4jConnector:
    """Neo4j Graph Store Connector"""
    
    def __init__(self):
        self.uri = settings.NEO4J_URI
        self.user = settings.NEO4J_USER
        self.password = settings.NEO4J_PASSWORD
        self._driver = None
    
    def connect(self):
        """Neo4j 연결"""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
    
    def close(self):
        """연결 닫기"""
        if self._driver:
            self._driver.close()
            self._driver = None
    
    def execute_query(self, query: str, parameters: Dict[str, Any] = None):
        """Cypher 쿼리 실행"""
        self.connect()
        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
    
    async def insert_triples(
        self,
        kb_id: str,
        doc_id: str,
        triples: List[Dict[str, Any]],
        generate_inverse: bool = True
    ) -> int:
        """트리플 삽입 (APOC 사용)"""
        self.connect()
        print(f"[Neo4j] Inserting {len(triples)} triples for doc {doc_id}...")
        inserted_count = 0
        total_to_insert = len(triples)
        
        for triple in triples:
            subject = triple.get("subject", "")
            predicate = triple.get("predicate", "")
            obj = triple.get("object", "")
            
            if not all([subject, predicate, obj]):
                continue
            
            try:
                # [B안] 엔티티 타입이 있으면 동적 라벨 부여 (기본 :Entity 라벨은 유지 —
                # 검색/삭제가 :Entity 매칭에 의존). 타입이 없거나 "Entity"면 빈 리스트로
                # no-op이 되어 타이핑 비활성 시 기존 동작과 동일하다.
                subj_labels = self._type_labels(triple.get("subject_type"))
                obj_labels = self._type_labels(triple.get("object_type"))

                # APOC을 사용하여 동적 관계 타입 생성 + 동적 노드 라벨 부여
                query = """
                MERGE (s:Entity {name: $subj, kb_id: $kb_id})
                MERGE (o:Entity {name: $obj, kb_id: $kb_id})
                WITH s, o
                CALL apoc.create.addLabels(s, $subj_labels) YIELD node AS _s
                WITH _s AS s, o
                CALL apoc.create.addLabels(o, $obj_labels) YIELD node AS _o
                WITH s, _o AS o
                CALL apoc.merge.relationship(s, $pred, {}, $props, o, $props) YIELD rel
                SET rel.source_node_id = $source_node_id
                SET rel.doc_id = $doc_id
                RETURN rel
                """

                source_node_id = triple.get("source_node_id", "")
                props = {
                    "doc_id": doc_id,
                    "is_inverse": triple.get("is_inverse", False),
                    "source_node_id": source_node_id,
                }

                self.execute_query(query, {
                    "subj": subject,
                    "obj": obj,
                    "pred": predicate,
                    "kb_id": kb_id,
                    "props": props,
                    "source_node_id": source_node_id,
                    "doc_id": doc_id,
                    "subj_labels": subj_labels,
                    "obj_labels": obj_labels
                })
                inserted_count += 1
                
                # 역관계 생성
                if generate_inverse and not triple.get("is_inverse", False):
                    inverse_pred = self._get_inverse_predicate(predicate)
                    if inverse_pred:
                        inverse_query = """
                        MERGE (s:Entity {name: $subj, kb_id: $kb_id})
                        MERGE (o:Entity {name: $obj, kb_id: $kb_id})
                        WITH s, o
                        CALL apoc.merge.relationship(o, $pred, {}, $props, s, $props) YIELD rel
                        SET rel.source_node_id = $source_node_id
                        SET rel.doc_id = $doc_id
                        RETURN rel
                        """
                        inverse_props = {**props, "is_inverse": True}
                        self.execute_query(inverse_query, {
                            "subj": subject,
                            "obj": obj,
                            "pred": inverse_pred,
                            "kb_id": kb_id,
                            "props": inverse_props,
                            "source_node_id": source_node_id,
                            "doc_id": doc_id
                        })
                        inserted_count += 1
                
                if (inserted_count % 10 == 0):
                    print(f"[Neo4j] Progress: {inserted_count} relationships created...")
                
            except Exception as e:
                print(f"Error inserting triple: {e}")
                continue
        
        print(f"[Neo4j] ✅ Successfully inserted {inserted_count} relationships.")
        return inserted_count
    
    def _type_labels(self, entity_type: Optional[str]) -> List[str]:
        """엔티티 타입을 안전한 Neo4j 라벨 리스트로 변환.

        타입이 없거나 "Entity"(안전 폴백)면 빈 리스트를 반환해 addLabels가
        no-op이 되게 한다. 라벨은 영숫자/언더스코어로 정제하고, 숫자로 시작하면
        접두사를 붙인다(라벨은 숫자로 시작할 수 없음).
        """
        if not entity_type or entity_type == "Entity":
            return []
        import re
        safe = re.sub(r'[^0-9A-Za-z_가-힣]', '', str(entity_type).strip())
        if not safe:
            return []
        if safe[0].isdigit():
            safe = f"T_{safe}"
        return [safe]

    def _get_inverse_predicate(self, predicate: str) -> Optional[str]:
        """역관계 프레디케이트 생성"""
        inverse_map = {
            "스승": "제자",
            "제자": "스승",
            "부모": "자녀",
            "자녀": "부모",
            "works_for": "employs",
            "employs": "works_for",
            "has_part": "part_of",
            "part_of": "has_part",
        }
        return inverse_map.get(predicate, f"inverse_{predicate}")
    
    async def delete_by_doc_id(self, kb_id: str, doc_id: str) -> int:
        """문서 ID로 관련 트리플 삭제"""
        self.connect()
        
        query = """
        MATCH (s:Entity {kb_id: $kb_id})-[r {doc_id: $doc_id}]->(o:Entity {kb_id: $kb_id})
        DELETE r
        RETURN count(r) as deleted_count
        """
        
        result = self.execute_query(query, {"kb_id": kb_id, "doc_id": doc_id})
        return result[0].get("deleted_count", 0) if result else 0


# Singleton
neo4j_connector = Neo4jConnector()
