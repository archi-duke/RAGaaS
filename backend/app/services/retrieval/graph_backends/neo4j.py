import logging
from typing import List, Dict, Any, Tuple
from app.core.neo4j_client import neo4j_client
from .base import GraphBackend

logger = logging.getLogger(__name__)

class Neo4jBackend(GraphBackend):
    """Neo4j implementation of GraphBackend with Fast Path support."""

    async def query(
        self,
        kb_id: str,
        entities: List[str],
        hops: int,
        query_type: str,
        relationship_keywords: List[str],
        **kwargs
    ) -> Dict[str, Any]:
        """Execute graph query on Neo4j using Cypher with Fast Path optimization."""
        from app.services.retrieval.cypher_generator import CypherGenerator
        
        query_text = kwargs.get("query_text", "")
        if not query_text:
            logger.warning("[Neo4j] No query text provided. Returning empty.")
            return {"chunk_ids": [], "sparql_query": "", "triples": []}

        trace_logs = []
        def log_trace(msg: str):
            trace_logs.append(msg)

        
        try:
            # [NEW] Fast Path Logic
            found_triples = []
            found_chunk_ids = set()
            skip_llm_generation = False
            
            # [OPTION 3] Multi-hop Pattern Detection - Skip Fast Path if multi-hop detected
            is_multihop_pattern = False
            if query_text and "의" in query_text:
                count_ui = query_text.count("의")
                if count_ui >= 2:
                    is_multihop_pattern = True
                    log_trace(f"[Neo4j] 🔄 Multi-hop pattern detected (의 x{count_ui}). Skipping Fast Path, delegating to LLM.")
            
            # 1. Extract entities from question (with Josa stripping) - Skip if multi-hop
            if not is_multihop_pattern:
                question_entities = self._extract_entities_from_question(query_text, entities)
                log_trace(f"[Neo4j] Extracted entities from question: {question_entities}")
            else:
                question_entities = []
            
            # 2. Heuristic: Strip Korean particles (조사)
            if not is_multihop_pattern:
                try:
                    tokens = query_text.split()
                    for t in tokens:
                        t_clean = t.rstrip(".,?!")
                        josas = ["에게", "으로", "에서", "하고", "이나", "이다", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "와", "과", "로"]
                        for josa in josas:
                            if t_clean.endswith(josa) and len(t_clean) > len(josa):
                                t_clean = t_clean[:-len(josa)]
                                break
                        
                        if t_clean and len(t_clean) > 1 and t_clean not in question_entities:
                            question_entities.append(t_clean)
                    log_trace(f"[Neo4j] Expanded entities with heuristic: {question_entities}")
                except Exception as e_heuristic:
                    log_trace(f"[Neo4j] Heuristic entity expansion failed: {e_heuristic}")

            # 3. Resolve entities to Neo4j nodes
            resolved_entities = []
            if not is_multihop_pattern:
                for entity in question_entities:
                    exists = self._check_entity_exists(kb_id, entity)
                    if exists:
                        resolved_entities.append(entity)
                        log_trace(f"[Neo4j] Resolved '{entity}' -> exists in graph")
                    
                    if len(resolved_entities) >= 2:
                        break
            
            # 4. Pattern Classification & Fast Path Execution
            if resolved_entities and not is_multihop_pattern:
                num_entities = len(resolved_entities)
                
                if num_entities == 1:
                    entity_name = resolved_entities[0]
                    
                    # Detect Pattern 1 vs Pattern 3
                    entity_idx = query_text.find(entity_name)
                    if entity_idx != -1:
                        after_entity = query_text[entity_idx + len(entity_name):entity_idx + len(entity_name) + 2]
                        is_object_pattern = after_entity.startswith(("을", "를"))
                        is_subject_pattern = after_entity.startswith(("의", "이", "가"))
                    else:
                        is_object_pattern = False
                        is_subject_pattern = False
                    
                    if is_object_pattern:
                        # Pattern 1: ? -> P -> O (Subject unknown)
                        log_trace(f"[Neo4j] Pattern 1 detected: ? -> P -> {entity_name}")
                        
                        # Bidirectional Partial Match Cypher
                        cypher_query = """
                        MATCH (s:Entity)-[r]->(o:Entity)
                        WHERE s.kb_id = $kb_id
                          AND (toLower(o.name) CONTAINS toLower($entity_name) OR toLower($entity_name) CONTAINS toLower(o.name))
                          AND size(o.name) > 1
                          AND type(r) <> 'MENTIONED_IN'
                        RETURN DISTINCT 
                            s.name as subject, 
                            type(r) as predicate, 
                            o.name as object,
                            r.is_inverse as is_inverse,
                            r.source_node_id as source_node_id
                        UNION
                        MATCH (s:Entity)<-[r]-(o:Entity)
                        WHERE s.kb_id = $kb_id
                          AND (toLower(s.name) CONTAINS toLower($entity_name) OR toLower($entity_name) CONTAINS toLower(s.name))
                          AND type(r) <> 'MENTIONED_IN'
                        RETURN DISTINCT 
                            o.name as subject, 
                            type(r) as predicate, 
                            s.name as object,
                            r.is_inverse as is_inverse,
                            r.source_node_id as source_node_id
                        LIMIT 100
                        """
                        
                        try:
                            log_trace(f"[Neo4j] Pattern 1 Bidirectional Fast Path Cypher:\n{cypher_query}")
                            records = neo4j_client.execute_query(cypher_query, {
                                "kb_id": kb_id,
                                "entity_name": entity_name
                            })
                            
                            if records:
                                log_trace(f"[Neo4j] Pattern 1: Fast Path successful. Found {len(records)} triples.")
                                for r in records:
                                    found_triples.append({
                                        "subject": r["subject"],
                                        "predicate": r["predicate"],
                                        "object": r["object"],
                                        "is_inverse": r.get("is_inverse", False),
                                        "source_node_id": r.get("source_node_id")
                                    })
                                    if r.get("source_node_id"):
                                        found_chunk_ids.add(r["source_node_id"])
                                skip_llm_generation = True
                                log_trace(f"[Neo4j] Pattern 1: Fast Path complete. Skipping LLM.")
                        except Exception as e:
                            log_trace(f"[Neo4j] Pattern 1: Fast Path failed: {e}")
                    
                    else:
                        # Pattern 3: S -> P -> ? (Object unknown)
                        log_trace(f"[Neo4j] Pattern 3 detected: {entity_name} -> P -> ?")
                        
                        # Bidirectional Partial Match Cypher
                        cypher_query = """
                        MATCH (s:Entity)-[r]->(o:Entity)
                        WHERE s.kb_id = $kb_id
                          AND (toLower(o.name) CONTAINS toLower($entity_name) OR toLower($entity_name) CONTAINS toLower(o.name))
                          AND type(r) <> 'MENTIONED_IN'
                        RETURN DISTINCT 
                            s.name as subject, 
                            type(r) as predicate, 
                            o.name as object,
                            r.is_inverse as is_inverse,
                            r.source_node_id as source_node_id
                        UNION
                        MATCH (s:Entity)<-[r]-(o:Entity)
                        WHERE s.kb_id = $kb_id
                          AND (toLower(s.name) CONTAINS toLower($entity_name) OR toLower($entity_name) CONTAINS toLower(s.name))
                          AND size(s.name) > 1 
                          AND type(r) <> 'MENTIONED_IN'
                        RETURN DISTINCT 
                            o.name as subject, 
                            type(r) as predicate, 
                            s.name as object,
                            r.is_inverse as is_inverse,
                            r.source_node_id as source_node_id
                        LIMIT 100
                        """
                        
                        try:
                            log_trace(f"[Neo4j] Pattern 3 Bidirectional Fast Path Cypher:\n{cypher_query}")
                            records = neo4j_client.execute_query(cypher_query, {
                                "kb_id": kb_id,
                                "entity_name": entity_name
                            })
                            
                            if records:
                                log_trace(f"[Neo4j] Pattern 3: Fast Path successful. Found {len(records)} triples.")
                                for r in records:
                                    found_triples.append({
                                        "subject": r["subject"],
                                        "predicate": r["predicate"],
                                        "object": r["object"],
                                        "is_inverse": r.get("is_inverse", False),
                                        "source_node_id": r.get("source_node_id")
                                    })
                                    if r.get("source_node_id"):
                                        found_chunk_ids.add(r["source_node_id"])
                                skip_llm_generation = True
                                log_trace(f"[Neo4j] Pattern 3: Fast Path complete. Skipping LLM.")
                        except Exception as e:
                            log_trace(f"[Neo4j] Pattern 3: Fast Path failed: {e}")
                
                elif num_entities >= 2:
                    # Pattern 2: S -> ? -> O (Relation unknown)
                    entity1_name = resolved_entities[0]
                    entity2_name = resolved_entities[1]
                    
                    log_trace(f"[Neo4j] Pattern 2 detected: {entity1_name} -> ? -> {entity2_name}")
                    
                    # Direct Path Cypher (Bidirectional with Partial Match)
                    cypher_query = """
                    MATCH (s:Entity)-[r]->(o:Entity)
                    WHERE s.kb_id = $kb_id
                      AND (toLower(s.name) CONTAINS toLower($entity1) OR toLower($entity1) CONTAINS toLower(s.name))
                      AND (toLower(o.name) CONTAINS toLower($entity2) OR toLower($entity2) CONTAINS toLower(o.name))
                      AND size(s.name) > 1
                      AND size(o.name) > 1
                      AND type(r) <> 'MENTIONED_IN'
                    RETURN DISTINCT 
                        s.name as subject, 
                        type(r) as predicate, 
                        o.name as object,
                        r.is_inverse as is_inverse,
                        r.source_node_id as source_node_id
                    UNION
                    MATCH (s:Entity)-[r]->(o:Entity)
                    WHERE s.kb_id = $kb_id
                      AND (toLower(s.name) CONTAINS toLower($entity2) OR toLower($entity2) CONTAINS toLower(s.name))
                      AND (toLower(o.name) CONTAINS toLower($entity1) OR toLower($entity1) CONTAINS toLower(o.name))
                      AND size(s.name) > 1
                      AND size(o.name) > 1
                      AND type(r) <> 'MENTIONED_IN'
                    RETURN DISTINCT 
                        s.name as subject, 
                        type(r) as predicate, 
                        o.name as object,
                        r.is_inverse as is_inverse,
                        r.source_node_id as source_node_id
                    """
                    
                    try:
                        log_trace(f"[Neo4j] Pattern 2 Fast Path Cypher:\n{cypher_query}")
                        records = neo4j_client.execute_query(cypher_query, {
                            "kb_id": kb_id,
                            "entity1": entity1_name,
                            "entity2": entity2_name
                        })
                        
                        if records:
                            log_trace(f"[Neo4j] Pattern 2: Fast Path successful. Found {len(records)} direct triples.")
                            for r in records:
                                found_triples.append({
                                    "subject": r["subject"],
                                    "predicate": r["predicate"],
                                    "object": r["object"],
                                    "is_inverse": r.get("is_inverse", False),
                                    "source_node_id": r.get("source_node_id")
                                })
                                if r.get("source_node_id"):
                                    found_chunk_ids.add(r["source_node_id"])
                            skip_llm_generation = True
                            log_trace(f"[Neo4j] Pattern 2: Fast Path complete. Skipping LLM.")
                    except Exception as e:
                        log_trace(f"[Neo4j] Pattern 2: Fast Path failed: {e}")
            
            # [RELEVANCE CHECK]
            # Fast Path가 무차별적으로 데이터를 가져오는 것을 방지
            if skip_llm_generation and found_triples:
                # 1. 질문에서 핵심 키워드 추출 (엔티티 제외)
                # 간단한 방식: 공백 분리 후 엔티티 이름이 아닌 것들 중 명사형 추정
                query_tokens = query_text.replace("?", "").split()
                relation_keywords = []
                known_entity_names = [e for e in resolved_entities]
                
                for t in query_tokens:
                    # 조사 제거
                    t_clean = t.rstrip("은는이가을를의와과로으로에게")
                    if len(t_clean) > 1 and t_clean not in known_entity_names:
                         # 질문 어미/조사 등 불용어 필터링 (간단히)
                         if t_clean not in ["누구", "무엇", "언제", "어디", "어떻게", "관계", "사람", "것"]:
                             relation_keywords.append(t_clean)
                
                log_trace(f"[Neo4j] Relevance Check Keywords: {relation_keywords}")
                
                if relation_keywords:
                    is_relevant = False
                    for triple in found_triples:
                        p = triple["predicate"]
                        o = triple["object"]
                        # 키워드가 Predicate나 Object에 포함되는지 확인
                        for kw in relation_keywords:
                            if kw in p or kw in o:
                                is_relevant = True
                                break
                        if is_relevant:
                            break
                    
                    if not is_relevant:
                        log_trace(f"[Neo4j] ⚠️ Fast Path result seems irrelevant to keywords {relation_keywords}. Formatting Fallback to LLM.")
                        skip_llm_generation = False
                        found_triples = [] # Reset to avoid noise
                        found_chunk_ids = set()

            # If Fast Path succeeded, return immediately
            if skip_llm_generation:
                return {
                    "chunk_ids": list(found_chunk_ids),
                    "sparql_query": "Fast Path (LLM bypassed)",
                    "triples": found_triples,
                    "thought": "Fast Path optimization applied",
                    "found_entities": resolved_entities,
                    "trace_logs": trace_logs,
                    "used_fallback": False
                }
            
            # [FALLBACK] Use LLM-based CypherGenerator
            log_trace("[Neo4j] Fast Path not applicable. Falling back to LLM-based Cypher generation.")

            llm_model_config = kwargs.get("llm_model_config") or {}
            if not llm_model_config:
                raise ValueError("Graph query model is not configured.")
            from app.core.models_resolver import resolve_model_config
            resolved_llm = await resolve_model_config(llm_model_config)
            cypher_api_key = resolved_llm.get("api_key")
            if not cypher_api_key:
                raise ValueError("Graph query API key is not configured.")
            generator = CypherGenerator(api_key=cypher_api_key)
            context = f"관련 엔티티 후보: {', '.join(entities)}" if entities else None
            
            # Determine inverse relation mode
            inv_mode = kwargs.get("inverse_extraction_mode", "auto")
            enable_inverse = kwargs.get("enable_inverse_search", False)
            dynamic_schema_enabled = kwargs.get("use_dynamic_schema", False)
            
            if not enable_inverse:
                inv_mode = "none"
            
            custom_prompt = kwargs.get("custom_query_prompt") or ""
            
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
            
            # LLM 호출 (상세 로깅)
            log_trace(f"[Neo4j] Calling LLM Cypher Generator (inv_mode={inv_mode}, dynamic_schema={dynamic_schema_enabled})")
            print(f"[DEBUG] Calling CypherGenerator.generate() with inv_mode={inv_mode}, dynamic_schema={dynamic_schema_enabled}", flush=True)
            
            gen_result = generator.generate(
                query_text, 
                context=context, 
                custom_prompt=custom_prompt if custom_prompt else None,
                inverse_search_mode=inv_mode,
                kb_id=kb_id,
                use_dynamic_schema=dynamic_schema_enabled
            )
            
            print(f"[DEBUG] CypherGenerator returned: {gen_result}", flush=True)
            log_trace(f"[Neo4j] LLM returned: {gen_result}")
            
            cypher_query = gen_result.get("cypher")
            thought = gen_result.get("thought")
            
            print(f"[DEBUG] extracted cypher_query type: {type(cypher_query)}, value: {cypher_query[:200] if cypher_query else None}", flush=True)
            log_trace(f"[Neo4j] Extracted Cypher query: {cypher_query}")
            log_trace(f"[Neo4j] Generated Cypher:\n{cypher_query}")
            log_trace(f"[Neo4j] Reason: {thought}")
            
            if not cypher_query:
                log_trace("[Neo4j] No Cypher query generated. Returning empty results.")
                return {"chunk_ids": [], "sparql_query": "Generation Failed", "triples": [], "trace_logs": trace_logs}
            
            # Execute generated query
            print(f"[DEBUG] Step 1: Cypher query prepared, length={len(cypher_query)}", flush=True)
            print(f"[DEBUG] Step 2: Executing Cypher on Neo4j...", flush=True)
            log_trace(f"[Neo4j] Executing Cypher:\n{cypher_query}")
            
            records = neo4j_client.execute_query(cypher_query, {"kb_id": kb_id})
            
            print(f"[DEBUG] Step 3: Got results from Neo4j, record count: {len(records)}", flush=True)
            log_trace(f"[Neo4j] Query returned {len(records)} records")
            
            discovered_entities = set()
            
            for record in records:
                for key, value in record.items():
                    if hasattr(value, "labels"):
                        labels = set(value.labels)
                        props = dict(value)
                        
                        if "Entity" in labels or "Class" in labels or "Instance" in labels:
                            label_ko = props.get("label_ko") or props.get("name")
                            if label_ko:
                                discovered_entities.add(label_ko)
                    elif isinstance(value, str):
                        if value and len(value) > 1:
                            discovered_entities.add(value)
                            
            log_trace(f"[Neo4j] Discovered entities from query result: {len(discovered_entities)}")
            
            if inv_mode == "none" and len(discovered_entities) == 0:
                return {
                    "chunk_ids": [],
                    "sparql_query": cypher_query,
                    "triples": [],
                    "thought": thought,
                    "found_entities": [],
                    "trace_logs": trace_logs
                }
            
            # Fetch triples from graph
            triples, chunk_ids = self._fetch_triples_from_graph(kb_id, entities, list(discovered_entities), trace_logs)

            return {
                "chunk_ids": chunk_ids,
                "sparql_query": cypher_query,
                "triples": triples,
                "thought": thought,
                "found_entities": list(discovered_entities),
                "trace_logs": trace_logs,
                "used_fallback": True
            }

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            error_msg = f"Neo4j search failed: {e}"
            logger.error(error_msg)
            
            log_trace(f"[Neo4j] Error during Cypher generation/execution: {e}")
            log_trace(f"[Neo4j] Full traceback:\n{error_details}")
            print(f"[Neo4j] ERROR Details:\n{error_details}", flush=True)
            
            trace_logs.append(f"[Neo4j] Error: {str(e)}")
            trace_logs.append(f"[Neo4j] Traceback: {error_details}")
            
            return {"chunk_ids": [], "sparql_query": "Error", "triples": [], "trace_logs": trace_logs}

    def _extract_entities_from_question(self, query_text: str, fallback_entities: List[str]) -> List[str]:
        """Extract potential entity names from the question text."""
        # Simple implementation: return fallback entities
        return fallback_entities if fallback_entities else []
    
    def _check_entity_exists(self, kb_id: str, entity_name: str) -> bool:
        """Check if an entity exists in the Neo4j graph."""
        try:
            query = """
            MATCH (n:Entity)
            WHERE n.kb_id = $kb_id AND n.name = $entity_name
            RETURN count(n) as count
            """
            records = neo4j_client.execute_query(query, {"kb_id": kb_id, "entity_name": entity_name})
            return records[0]["count"] > 0 if records else False
        except Exception:
            return False

    def _fetch_triples_from_graph(self, kb_id: str, input_entities: List[str], discovered_entities: List[str], trace_logs: List[str] = None) -> Tuple[List[Dict[str, str]], List[str]]:
        """Fetch related triples from the graph (with source_node_id)."""
        triples = []
        chunk_ids = set()
        try:
            focus_entities = list(set(input_entities + discovered_entities))[:30]
            
            if not focus_entities:
                return [], []
            
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
                    if r.get("source_node_id"):
                        chunk_ids.add(r["source_node_id"])
                        
            if trace_logs is not None:
                trace_logs.append(f"[Neo4j] Fetched {len(triples)} triples, {len(chunk_ids)} unique chunk IDs from source_node_id")
                        
        except Exception as e:
            logger.error(f"Error in _fetch_triples_from_graph: {e}")
        
        return triples, list(chunk_ids)
