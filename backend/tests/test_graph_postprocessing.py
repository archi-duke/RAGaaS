"""
그래프 후처리 통합 테스트

Neo4j와 Fuseki 모두에 후처리가 올바르게 적용되는지 검증
"""
import pytest
from app.services.ingestion.graph_postprocessor import (
    post_process_triples,
    add_inverse_relations,
    is_noise_predicate,
    normalize_entity
)


class TestGraphPostprocessor:
    """후처리 모듈 단위 테스트"""
    
    def test_noise_filtering(self):
        """노이즈 predicate 제거 테스트"""
        triples = [
            {"subject": "A", "predicate": "관계", "object": "B"},  # 노이즈
            {"subject": "A", "predicate": "Domain", "object": "B"},  # 노이즈
            {"subject": "A", "predicate": "스승", "object": "B"}   # 정상
        ]
        filtered = post_process_triples(triples)
        
        assert len(filtered) == 1
        assert filtered[0]["predicate"] == "스승"
    
    def test_entity_normalization(self):
        """엔티티 정규화 테스트"""
        assert normalize_entity("성기훈은") == "성기훈"
        assert normalize_entity("오일남의") == "오일남"
        assert normalize_entity("강새벽과") == "강새벽"
        assert normalize_entity("  Duke  ") == "Duke"
    
    def test_pronoun_filtering(self):
        """대명사 필터링 테스트"""
        triples = [
            {"subject": "그", "predicate": "스승", "object": "오일남"},  # 대명사
            {"subject": "성기훈", "predicate": "스승", "object": "오일남"}  # 정상
        ]
        filtered = post_process_triples(triples)
        
        assert len(filtered) == 1
        assert filtered[0]["subject"] == "성기훈"
    
    def test_inverse_generation(self):
        """역관계 자동 생성 테스트"""
        triples = [
            {"subject": "성기훈", "predicate": "제자", "object": "오일남"}
        ]
        result = add_inverse_relations(triples)
        
        assert len(result) == 2
        # 원본 트리플
        assert any(
            t["subject"] == "성기훈" and 
            t["predicate"] == "제자" and 
            t["object"] == "오일남" 
            for t in result
        )
        # 역관계 트리플
        assert any(
            t["subject"] == "오일남" and 
            t["predicate"] == "스승" and 
            t["object"] == "성기훈" 
            for t in result
        )
    
    def test_deduplication(self):
        """중복 제거 테스트"""
        triples = [
            {"subject": "성기훈", "predicate": "스승", "object": "오일남"},
            {"subject": "성기훈은", "predicate": "스승", "object": "오일남의"},  # 정규화 후 중복
            {"subject": "성기훈", "predicate": "스승", "object": "오일남"}  # 완전 중복
        ]
        filtered = post_process_triples(triples, normalize=True)
        
        assert len(filtered) == 1
        assert filtered[0]["subject"] == "성기훈"
        assert filtered[0]["object"] == "오일남"


class TestIntegration:
    """통합 테스트 (실제 DB 필요)"""
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires running Neo4j instance")
    async def test_neo4j_fallback_with_postprocessing(self):
        """Neo4j Fallback 후처리 통합 테스트"""
        from app.services.ingestion.service import ingestion_service
        from app.core.neo4j_client import neo4j_client
        
        # 테스트 문서 적재
        test_content = """
        성기훈은 456번 참가자이다. 그는 이혼한 운전사다.
        오일남은 001번이다. 그는 성기훈에게 장풍을 전수했다.
        """.encode("utf-8")
        
        await ingestion_service.process_document(
            kb_id="test_kb",
            doc_id="test_doc",
            filename="test.txt",
            file_content=test_content
        )
        
        # 노이즈 관계 확인
        result = neo4j_client.execute_query("""
            MATCH (s)-[r]->(o)
            WHERE r.type IN ['관계', 'Domain', 'Relation']
            RETURN count(*) as noise_count
        """)
        assert result[0]["noise_count"] == 0
        
        # 역관계 확인
        result = neo4j_client.execute_query("""
            MATCH (s:Entity {name: '오일남'})-[r]->(o:Entity {name: '성기훈'})
            WHERE r.type = '스승'
            RETURN count(*) as count
        """)
        assert result[0]["count"] > 0
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires running Fuseki instance")
    async def test_fuseki_fallback_with_postprocessing(self):
        """Fuseki Fallback 후처리 통합 테스트"""
        from app.services.ingestion.service import ingestion_service
        from app.core.fuseki import fuseki_client
        
        # 테스트 문서 적재
        test_content = """
        성기훈은 456번 참가자이다.
        오일남은 성기훈의 스승이다.
        """.encode("utf-8")
        
        await ingestion_service.process_document(
            kb_id="test_kb_fuseki",
            doc_id="test_doc_fuseki",
            filename="test.txt",
            file_content=test_content
        )
        
        # 역관계 확인
        query = """
            PREFIX rel: <http://rag.local/relation/>
            SELECT ?s ?p ?o WHERE {
                ?s rel:제자 ?o .
            }
        """
        results = fuseki_client.execute_sparql("test_kb_fuseki", query)
        assert len(results) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
