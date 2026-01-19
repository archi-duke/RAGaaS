import logging
from typing import List, Dict, Any, Tuple
from app.core.neo4j_client import neo4j_client
from .base import GraphBackend

logger = logging.getLogger(__name__)

class Neo4jBackend(GraphBackend):
    """Neo4j implementation of GraphBackend."""

    async def query(
        self,
        kb_id: str,
        entities: List[str],
        hops: int,
        query_type: str,
        relationship_keywords: List[str],
        **kwargs
    ) -> Dict[str, Any]:
        """Execute graph query on Neo4j using Cypher.
        Now uses Doc2Onto's CypherGenerator for LLM-based query generation.
        """
        from app.services.retrieval.cypher_generator import CypherGenerator
        
        query_text = kwargs.get("query_text", "")
        if not query_text:
            logger.warning("[Neo4j] No query text provided for Cypher Generation. Returning empty.")
            return {"chunk_ids": [], "sparql_query": "", "triples": []}

        # Use Doc2Onto CypherGenerator
        
        trace_logs = []
        def log_trace(msg: str):
            trace_logs.append(msg)

        from app.core.config import settings
        
        try:
            generator = CypherGenerator(api_key=settings.OPENAI_API_KEY)
            context = f"관련 엔티티 후보: {', '.join(entities)}" if entities else None
            
            # Determine inverse relation mode
            inv_mode = kwargs.get("inverse_extraction_mode", "auto")
            enable_inverse = kwargs.get("enable_inverse_search", False)  # 기본값 False로 변경
            
            # If user explicitly disabled inverse search, override mode
            if not enable_inverse:
                inv_mode = "none"
            
            # Build custom prompt with inverse relation instruction
            custom_prompt = kwargs.get("custom_query_prompt") or ""
            
            # Add strict instruction when inverse search is disabled
            if inv_mode == "none":
                no_inverse_instruction = """
[중요 제약사항 - 반드시 준수]
- 역방향 관계 패턴을 절대 사용하지 마세요.
- | 연산자로 정방향/역방향 관계를 조합하지 마세요.
- 예시: `-[:스승|제자]-` 형태 사용 금지!
- 관계 방향을 명시하세요: `-[:스승]->` (반드시 화살표 포함!)
- 무방향 패턴 `-[:스승]-` 금지! (이는 양방향 검색이 됨)
- 오직 DB에 저장된 방향으로만 검색하세요.
"""
                custom_prompt = no_inverse_instruction + custom_prompt

            # Get use_dynamic_schema from kwargs
            use_dynamic_schema = kwargs.get("use_dynamic_schema", False)
            
            gen_result = generator.generate(
                query_text, 
                context=context, 
                custom_prompt=custom_prompt if custom_prompt else None,
                inverse_search_mode=inv_mode,
                kb_id=kb_id,
                use_dynamic_schema=use_dynamic_schema
            )
            cypher_query = gen_result.get("cypher")
            thought = gen_result.get("thought")
            
            log_trace(f"[Neo4j] Generated Cypher: {cypher_query}")
            log_trace(f"[Neo4j] Reason: {thought}")
            
            if not cypher_query:
                return {"chunk_ids": [], "sparql_query": "Generation Failed", "triples": [], "trace_logs": trace_logs}
                
            # Execute generated query with kb_id parameter
            records = neo4j_client.execute_query(cypher_query, {"kb_id": kb_id})
            
            discovered_entities = set()
            
            # Parse results (handle various return formats)
            for record in records:
                for key, value in record.items():
                    # If value is a Node
                    if hasattr(value, "labels"):
                        labels = set(value.labels)
                        props = dict(value)
                        
                        if "Entity" in labels or "Class" in labels or "Instance" in labels:
                            label_ko = props.get("label_ko") or props.get("name")
                            if label_ko:
                                discovered_entities.add(label_ko)
                    elif isinstance(value, str):
                        # Might be an entity name
                        if value and len(value) > 1:
                            discovered_entities.add(value)
                            
            log_trace(f"[Neo4j] Discovered entities from query result: {len(discovered_entities)}")
            
            # If inverse search is disabled and no entities were found, skip fallback
            if inv_mode == "none" and len(discovered_entities) == 0:
                return {
                    "chunk_ids": [],
                    "sparql_query": cypher_query,
                    "triples": [],
                    "thought": thought,
                    "found_entities": [],
                    "trace_logs": trace_logs
                }
            
            # 순수 그래프에서 트리플 조회 (source_node_id 포함)
            triples, chunk_ids = self._fetch_triples_from_graph(kb_id, entities, list(discovered_entities), trace_logs)

            return {
                "chunk_ids": chunk_ids,  # Neo4j에서 직접 추출한 source_node_id 목록
                "sparql_query": cypher_query,
                "triples": triples,
                "thought": thought,
                "found_entities": list(discovered_entities),
                "trace_logs": trace_logs
            }

        except Exception as e:
            logger.error(f"Neo4j search failed: {e}")
            import traceback
            traceback.print_exc()
            trace_logs.append(f"[Neo4j] Error: {str(e)}")
            return {"chunk_ids": [], "sparql_query": "Error", "triples": [], "trace_logs": trace_logs}

    def _fetch_triples_from_graph(self, kb_id: str, input_entities: List[str], discovered_entities: List[str], trace_logs: List[str] = None) -> Tuple[List[Dict[str, str]], List[str]]:
        """순수 그래프에서 관련 트리플 조회 (source_node_id 포함)
        
        Returns:
            Tuple[List[Dict], List[str]]: (트리플 목록, 청크 ID 목록)
        """
        triples = []
        chunk_ids = set()
        try:
            # Combine entities for focus
            focus_entities = list(set(input_entities + discovered_entities))[:30]
            
            if not focus_entities:
                return [], []
            
            # 순수 Entity-Relation 그래프에서 트리플 조회 (source_node_id 포함)
            triples_query = """
            MATCH (s:Entity)-[r]->(o:Entity)
            WHERE s.kb_id = $kb_id
              AND type(r) <> 'MENTIONED_IN'
              AND (s.name IN $entities OR o.name IN $entities)
            RETURN DISTINCT 
                s.name as subj, 
                type(r) as pred, 
                o.name as obj,
                r.is_inverse as is_inverse,
                r.source_node_id as source_node_id
            LIMIT 30
            """
            
            t_records = neo4j_client.execute_query(triples_query, {
                "kb_id": kb_id,
                "entities": focus_entities
            })
            
            seen = set()
            for r in t_records:
                key = (r["subj"], r["pred"], r["obj"])
                if key not in seen:
                    seen.add(key)
                    triples.append({
                        "subject": r["subj"], 
                        "predicate": r["pred"], 
                        "object": r["obj"],
                        "is_inverse": r.get("is_inverse", False),
                        "source_node_id": r.get("source_node_id")
                    })
                    # source_node_id가 있으면 청크 ID로 수집
                    if r.get("source_node_id"):
                        chunk_ids.add(r["source_node_id"])
                        
            if trace_logs is not None:
                trace_logs.append(f"[Neo4j] Fetched {len(triples)} triples, {len(chunk_ids)} unique chunk IDs from source_node_id")
                        
        except Exception as e:
            logger.error(f"Error in _fetch_triples_from_graph: {e}")
        
        return triples, list(chunk_ids)

