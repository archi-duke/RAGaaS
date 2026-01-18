"""
Fuseki Inference Engine Module

Jena+Fuseki 환경에서 규칙 기반 추론을 통해 새로운 관계를 생성합니다.
SPARQL INSERT 구문을 사용합니다.
예: A-스승->B, B-스승->C => A-사조->C
"""
import logging
from typing import List, Dict, Any, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class FusekiInferenceRule:
    """Fuseki 추론 규칙 정의"""
    
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


class FusekiInferenceEngine:
    """Fuseki/SPARQL 기반 규칙 추론 엔진"""
    
    NAMESPACE_REL = "http://rag.local/rel/"
    
    # 기본 추론 규칙
    DEFAULT_RULES = [
        FusekiInferenceRule(
            name="master_of_master",
            pattern=["스승", "스승"],
            inferred_relation="사조",
            description="스승의 스승 = 사조"
        ),
        FusekiInferenceRule(
            name="parent_of_parent",
            pattern=["부모", "부모"],
            inferred_relation="조부모",
            description="부모의 부모 = 조부모"
        ),
        FusekiInferenceRule(
            name="child_of_child",
            pattern=["자녀", "자녀"],
            inferred_relation="손자녀",
            description="자녀의 자녀 = 손자녀"
        ),
        FusekiInferenceRule(
            name="teacher_of_teacher",
            pattern=["teacher", "teacher"],
            inferred_relation="grand_teacher",
            description="teacher's teacher = grand_teacher"
        ),
    ]
    
    def __init__(self, rules: Optional[List[FusekiInferenceRule]] = None):
        self.rules = rules or self.DEFAULT_RULES
        self.base_url = settings.FUSEKI_URL  # e.g., http://fuseki:3030
    
    async def run_inference(
        self,
        kb_id: str,
        doc_id: Optional[str] = None
    ) -> int:
        """
        추론 규칙을 실행하여 새로운 관계를 생성합니다.
        
        Args:
            kb_id: Knowledge Base ID
            doc_id: (선택) 특정 문서 그래프에 대해서만 실행
            
        Returns:
            적용된 규칙 수 (생성 성공한 규칙 개수)
        """
        dataset = f"kb_{kb_id.replace('-', '_')}"
        total_applied = 0
        
        for rule in self.rules:
            try:
                success = await self._apply_rule(dataset, doc_id, rule)
                if success:
                    logger.info(f"[FusekiInference] Rule '{rule.name}' applied successfully")
                    print(f"[FusekiInference] Rule '{rule.name}' applied successfully")
                    total_applied += 1
            except Exception as e:
                logger.error(f"[FusekiInference] Rule '{rule.name}' failed: {e}")
                print(f"[FusekiInference] Rule '{rule.name}' failed: {e}")
        
        return total_applied
    
    async def _apply_rule(
        self,
        dataset: str,
        doc_id: Optional[str],
        rule: FusekiInferenceRule
    ) -> bool:
        """단일 규칙 적용"""
        
        if len(rule.pattern) != 2:
            # 현재는 2-hop 패턴만 지원
            return False
        
        rel1, rel2 = rule.pattern
        inferred = rule.inferred_relation
        
        rel1_uri = f"{self.NAMESPACE_REL}{rel1}"
        rel2_uri = f"{self.NAMESPACE_REL}{rel2}"
        inferred_uri = f"{self.NAMESPACE_REL}{inferred}"
        
        # SPARQL INSERT 쿼리
        # 특정 문서 그래프(doc_id) 또는 전체 그래프에서 패턴 매칭 후 추론
        if doc_id:
            graph_uri = f"urn:doc:{doc_id}"
            sparql = f"""
            PREFIX rel: <{self.NAMESPACE_REL}>
            
            INSERT {{
                GRAPH <{graph_uri}> {{
                    ?a <{inferred_uri}> ?c .
                }}
            }}
            WHERE {{
                GRAPH <{graph_uri}> {{
                    ?a <{rel1_uri}> ?b .
                    ?b <{rel2_uri}> ?c .
                    FILTER(?a != ?c)
                    FILTER NOT EXISTS {{ ?a <{inferred_uri}> ?c }}
                }}
            }}
            """
        else:
            # 전체 그래프에서 수행
            sparql = f"""
            PREFIX rel: <{self.NAMESPACE_REL}>
            
            INSERT {{
                GRAPH ?g {{
                    ?a <{inferred_uri}> ?c .
                }}
            }}
            WHERE {{
                GRAPH ?g {{
                    ?a <{rel1_uri}> ?b .
                    ?b <{rel2_uri}> ?c .
                    FILTER(?a != ?c)
                    FILTER NOT EXISTS {{ ?a <{inferred_uri}> ?c }}
                }}
            }}
            """
        
        # Fuseki Update 엔드포인트 호출
        update_url = f"{self.base_url}/{dataset}/update"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                update_url,
                data={"update": sparql},
                auth=("admin", "admin"),
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code in [200, 204]:
                return True
            else:
                logger.warning(f"[FusekiInference] Update failed: {response.status_code} - {response.text}")
                return False
    
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
fuseki_inference_engine = FusekiInferenceEngine()
