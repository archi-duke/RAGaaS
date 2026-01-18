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
        
        inserted_count = 0
        
        for triple in triples:
            subject = triple.get("subject", "")
            predicate = triple.get("predicate", "")
            obj = triple.get("object", "")
            
            if not all([subject, predicate, obj]):
                continue
            
            try:
                # APOC을 사용하여 동적 관계 타입 생성
                query = """
                MERGE (s:Entity {name: $subj, kb_id: $kb_id})
                MERGE (o:Entity {name: $obj, kb_id: $kb_id})
                WITH s, o
                CALL apoc.merge.relationship(s, $pred, {}, $props, o, $props) YIELD rel
                RETURN rel
                """
                
                props = {
                    "doc_id": doc_id,
                    "is_inverse": triple.get("is_inverse", False),
                    "source_node_id": triple.get("source_node_id", ""),
                }
                
                self.execute_query(query, {
                    "subj": subject,
                    "obj": obj,
                    "pred": predicate,
                    "kb_id": kb_id,
                    "props": props,
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
                        RETURN rel
                        """
                        inverse_props = {**props, "is_inverse": True}
                        self.execute_query(inverse_query, {
                            "subj": subject,
                            "obj": obj,
                            "pred": inverse_pred,
                            "kb_id": kb_id,
                            "props": inverse_props,
                        })
                        inserted_count += 1
                
            except Exception as e:
                print(f"Error inserting triple: {e}")
                continue
        
        return inserted_count
    
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
