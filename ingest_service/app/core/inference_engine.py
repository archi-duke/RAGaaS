"""
Inference Engine Module

적재 이후 규칙 기반 추론을 통해 새로운 관계를 생성합니다.
예: A-스승->B, B-스승->C => A-사조->C
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from app.core.config import settings

logger = logging.getLogger(__name__)


class InferenceRule:
    """추론 규칙 정의"""
    
    def __init__(
        self,
        name: str,
        pattern: List[str],  # ["스승", "스승"]
        inferred_relation: str,  # "사조"
        description: str = ""
    ):
        self.name = name
        self.pattern = pattern
        self.inferred_relation = inferred_relation
        self.description = description


class InferenceEngine:
    """규칙 기반 관계 추론 엔진"""
    
    # 기본 추론 규칙
    DEFAULT_RULES = [
        InferenceRule(
            name="master_of_master",
            pattern=["스승", "스승"],
            inferred_relation="사조",
            description="스승의 스승 = 사조"
        ),
        InferenceRule(
            name="parent_of_parent",
            pattern=["부모", "부모"],
            inferred_relation="조부모",
            description="부모의 부모 = 조부모"
        ),
        InferenceRule(
            name="child_of_child",
            pattern=["자녀", "자녀"],
            inferred_relation="손자녀",
            description="자녀의 자녀 = 손자녀"
        ),
        InferenceRule(
            name="teacher_of_teacher",
            pattern=["teacher", "teacher"],
            inferred_relation="grand_teacher",
            description="teacher's teacher = grand_teacher"
        ),
    ]
    
    def __init__(self, rules: Optional[List[InferenceRule]] = None):
        self.rules = rules or self.DEFAULT_RULES
        self._driver = None
    
    def _get_driver(self):
        """Neo4j 드라이버 가져오기"""
        if self._driver is None:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            )
        return self._driver
    
    async def run_inference(
        self,
        kb_id: str,
        doc_id: Optional[str] = None
    ) -> int:
        """
        추론 규칙을 실행하여 새로운 관계를 생성합니다.
        
        Args:
            kb_id: Knowledge Base ID
            doc_id: (선택) 특정 문서에 대해서만 실행
            
        Returns:
            생성된 관계 수
        """
        total_created = 0
        
        for rule in self.rules:
            try:
                count = await self._apply_rule(kb_id, doc_id, rule)
                if count > 0:
                    logger.info(f"[Inference] Rule '{rule.name}': Created {count} relations")
                    total_created += count
            except Exception as e:
                logger.error(f"[Inference] Rule '{rule.name}' failed: {e}")
        
        return total_created
    
    async def _apply_rule(
        self,
        kb_id: str,
        doc_id: Optional[str],
        rule: InferenceRule
    ) -> int:
        """단일 규칙 적용"""
        
        if len(rule.pattern) != 2:
            # 현재는 2-hop 패턴만 지원
            return 0
        
        rel1, rel2 = rule.pattern
        inferred = rule.inferred_relation
        
        # Cypher 쿼리: 패턴 매칭 후 새 관계 생성
        query = f"""
        MATCH (a:Entity {{kb_id: $kb_id}})-[r1:`{rel1}`]->(b:Entity {{kb_id: $kb_id}})-[r2:`{rel2}`]->(c:Entity {{kb_id: $kb_id}})
        WHERE a <> c
        AND NOT EXISTS {{ (a)-[:`{inferred}`]->(c) }}
        MERGE (a)-[r:`{inferred}` {{
            inferred: true,
            rule: $rule_name,
            kb_id: $kb_id
        }}]->(c)
        RETURN count(r) as created
        """
        
        params = {
            "kb_id": kb_id,
            "rule_name": rule.name
        }
        
        if doc_id:
            # 특정 문서 관련 노드로 제한
            query = f"""
            MATCH (a:Entity {{kb_id: $kb_id}})-[r1:`{rel1}`]->(b:Entity {{kb_id: $kb_id}})-[r2:`{rel2}`]->(c:Entity {{kb_id: $kb_id}})
            WHERE a <> c
            AND (r1.doc_id = $doc_id OR r2.doc_id = $doc_id)
            AND NOT EXISTS {{ (a)-[:`{inferred}`]->(c) }}
            MERGE (a)-[r:`{inferred}` {{
                inferred: true,
                rule: $rule_name,
                kb_id: $kb_id,
                doc_id: $doc_id
            }}]->(c)
            RETURN count(r) as created
            """
            params["doc_id"] = doc_id
        
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(query, params)
            record = result.single()
            return record["created"] if record else 0
    
    def add_rule(self, rule: InferenceRule):
        """규칙 추가"""
        self.rules.append(rule)
    
    def get_rules(self) -> List[Dict[str, Any]]:
        """등록된 규칙 목록 반환"""
        return [
            {
                "name": r.name,
                "pattern": r.pattern,
                "inferred_relation": r.inferred_relation,
                "description": r.description
            }
            for r in self.rules
        ]


# Singleton instance
inference_engine = InferenceEngine()
