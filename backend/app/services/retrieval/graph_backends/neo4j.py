import logging
from typing import List, Dict, Any, Optional, Tuple
from app.core.neo4j_client import neo4j_client
from app.services.retrieval.query_gen_loop import QueryGenerationLoop
from app.services.retrieval.query_gen_attempt_logger import log_attempts
from app.services.retrieval.query_gen_example_memory import ExampleMemory
from app.services.embedding import embedding_service as default_embedding_service
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
                    # 1차: LLM 이 판별한 엔티티 역할(entity_roles) 사용, 없으면 조사(Josa) 폴백
                    entity_roles = kwargs.get("entity_roles") or {}
                    role = entity_roles.get(entity_name)
                    if role == "object":
                        is_object_pattern, is_subject_pattern = True, False
                        log_trace(f"[Neo4j] Role by LLM: '{entity_name}' = object → Pattern 1")
                    elif role == "subject":
                        is_object_pattern, is_subject_pattern = False, True
                        log_trace(f"[Neo4j] Role by LLM: '{entity_name}' = subject → Pattern 3")
                    else:
                        # 폴백: 조사 휴리스틱 (기존 동작 불변)
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
                relation_keywords = self._extract_relevance_keywords(query_text, resolved_entities)
                log_trace(f"[Neo4j] Relevance Check Keywords: {relation_keywords}")

                is_relevant = self._check_relevance(query_text, resolved_entities, found_triples, relation_keywords)
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
            cypher_base_url = resolved_llm.get("base_url")
            cypher_endpoint = f"{cypher_base_url.rstrip('/')}/chat/completions" if cypher_base_url else None
            generator = CypherGenerator(
                api_key=cypher_api_key,
                llm_endpoint=cypher_endpoint,
                llm_model=resolved_llm.get("model") or "gpt-4o",
            )
            context = f"관련 엔티티 후보: {', '.join(entities)}" if entities else None
            
            # Determine inverse relation mode
            inv_mode = kwargs.get("inverse_extraction_mode", "auto")
            enable_inverse = kwargs.get("enable_inverse_search", False)
            dynamic_schema_enabled = kwargs.get("use_dynamic_schema", True)
            
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
            
            # [Query Generation Loop] Few-shot lookup (best-effort; never blocks the search)
            emb_service = kwargs.get("embedding_service", default_embedding_service)
            few_shot: List[Dict[str, Any]] = []
            few_shot_ids: List[str] = []
            try:
                few_shot = await ExampleMemory().search(kb_id, "neo4j", query_text, emb_service)
                few_shot_ids = [ex["id"] for ex in few_shot if ex.get("id")]
                log_trace(f"[Neo4j] Few-shot examples retrieved: {len(few_shot)}")
            except Exception as e_fewshot:
                log_trace(f"[Neo4j] Few-shot lookup failed (non-fatal): {e_fewshot}")

            # generate_fn/execute_fn close over `generator`, `context`, `inv_mode`,
            # `dynamic_schema_enabled`, `custom_prompt`, `few_shot`, `kb_id` established above.
            # `last_raw_gen` preserves the last generate_fn() JSON payload (e.g. "thought") since
            # QueryGenerationLoop.attempts only tracks {query, error, result_count, ...}.
            last_raw_gen: Dict[str, Any] = {}

            async def generate_fn(question: str, retry_context: Optional[str]) -> Dict[str, Any]:
                nonlocal last_raw_gen
                combined_prompt = custom_prompt if custom_prompt else None
                if retry_context:
                    combined_prompt = f"{custom_prompt}\n\n{retry_context}" if custom_prompt else retry_context

                log_trace(f"[Neo4j] Calling LLM Cypher Generator (inv_mode={inv_mode}, dynamic_schema={dynamic_schema_enabled}, retry={'yes' if retry_context else 'no'})")
                print(f"[DEBUG] Calling CypherGenerator.generate() with inv_mode={inv_mode}, dynamic_schema={dynamic_schema_enabled}", flush=True)

                gen = generator.generate(
                    question,
                    context=context,
                    custom_prompt=combined_prompt,
                    inverse_search_mode=inv_mode,
                    kb_id=kb_id,
                    use_dynamic_schema=dynamic_schema_enabled,
                    few_shot_examples=few_shot or None,
                )
                print(f"[DEBUG] CypherGenerator returned: {gen}", flush=True)
                log_trace(f"[Neo4j] LLM returned: {gen}")
                last_raw_gen = gen or {}
                return {"query": (gen or {}).get("cypher"), "raw": gen}

            async def execute_fn(cypher_text: str) -> List[Any]:
                print(f"[DEBUG] Executing Cypher on Neo4j...", flush=True)
                log_trace(f"[Neo4j] Executing Cypher:\n{cypher_text}")
                return neo4j_client.execute_query(cypher_text, {"kb_id": kb_id})

            # 스키마 검증 힌트: 실패한 Cypher 가 그래프에 없는 관계 타입을 참조하면
            # 재시도 프롬프트에 "없는 관계 + 사용 가능 목록"을 주입한다 (실행 차단 아님).
            allowed_rel_types: List[str] = []
            try:
                live_schema = generator._fetch_neo4j_schema(kb_id) or {}
                allowed_rel_types = live_schema.get("relationship_types", []) or []
            except Exception as e_schema:
                log_trace(f"[Neo4j] WARNING: schema fetch for validation failed: {e_schema}")

            def schema_hint_fn(failed_query: str):
                from app.services.retrieval.query_validation import cypher_schema_hint
                return cypher_schema_hint(failed_query, allowed_rel_types)

            loop = QueryGenerationLoop(max_retries=2)
            loop_result = await loop.run(query_text, generate_fn, execute_fn, schema_hint_fn=schema_hint_fn)

            try:
                model_name = getattr(generator, "llm_model", "") or ""
                await log_attempts(
                    kb_id,
                    "neo4j",
                    query_text,
                    loop_result["attempts"],
                    model=model_name,
                    few_shot_used=few_shot_ids,
                )
            except Exception as e_log:
                log_trace(f"[Neo4j] Attempt logging failed (non-fatal): {e_log}")

            cypher_query = loop_result["query"]
            records = loop_result["results"] or []
            thought = last_raw_gen.get("thought")

            print(f"[DEBUG] QueryGenerationLoop finished: succeeded={loop_result['succeeded']}, attempts={len(loop_result['attempts'])}, record_count={len(records)}", flush=True)
            log_trace(f"[Neo4j] Query Generation Loop finished: succeeded={loop_result['succeeded']}, attempts={len(loop_result['attempts'])}")
            log_trace(f"[Neo4j] Final Cypher:\n{cypher_query}")
            log_trace(f"[Neo4j] Reason: {thought}")

            if not cypher_query:
                log_trace("[Neo4j] No Cypher query generated. Returning empty results.")
                return {"chunk_ids": [], "sparql_query": "Generation Failed", "triples": [], "trace_logs": trace_logs}

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

            # [FIX] 쿼리 결과에서 깨끗한 체인 트리플을 직접 추출(Fuseki와 동일 전략).
            # 멀티홉 관계 체인에서, 발견 엔티티 전체를 broad 재조회하면 노이즈가 답변을
            # 오염시킨다. LLM 쿼리 결과 record가 곧 정답 경로이므로 이를 우선 사용한다.
            result_triples = self._extract_triples_from_records(records)
            if result_triples:
                log_trace(f"[Neo4j] Extracted {len(result_triples)} triples directly from query result")

            # Fetch triples from graph (broad — chunk 매핑 및 보조 컨텍스트용)
            fetched_triples, chunk_ids = self._fetch_triples_from_graph(kb_id, entities, list(discovered_entities), trace_logs)

            # 정답 경로(result_triples)를 앞에 두고 보조 트리플을 뒤에 dedup 병합.
            if result_triples:
                seen_rt = {(t["subject"], t["predicate"], t["object"]) for t in result_triples}
                triples = result_triples + [t for t in fetched_triples if (t["subject"], t["predicate"], t["object"]) not in seen_rt]
            else:
                triples = fetched_triples

            # [Query Generation Loop] Store successful, relevant examples for future few-shot use.
            # This gate only controls what gets persisted to ExampleMemory -- it must never filter
            # the triples/results returned to the caller.
            if loop_result["succeeded"]:
                try:
                    # 저장 게이트는 엔티티를 키워드에서 제외하지 않는다(빈 리스트 전달):
                    # 질문의 어떤 내용어든(엔티티 포함) 트리플 s/p/o 에 있으면 저장.
                    is_relevant_for_storage = self._check_relevance(query_text, [], triples, include_subject=True)
                    if is_relevant_for_storage:
                        await ExampleMemory().store(kb_id, "neo4j", query_text, cypher_query, emb_service)
                        log_trace("[Neo4j] Stored successful query as few-shot example.")
                    else:
                        log_trace("[Neo4j] Successful query did not pass relevance gate; not stored as example.")
                except Exception as e_store:
                    log_trace(f"[Neo4j] Example memory store failed (non-fatal): {e_store}")

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

    def _extract_relevance_keywords(self, query_text: str, known_entity_names: List[str]) -> List[str]:
        """Extract candidate relation/object keywords from the question, excluding known entities.

        Extracted verbatim from the original Fast Path relevance-check block so both the Fast
        Path and the LLM fallback path can reuse the exact same heuristic.
        """
        query_tokens = query_text.replace("?", "").split()
        relation_keywords = []
        # 불용어 접두 매칭: 굴절형("누구랑","누구야","관계있어","관계는")도 걸러낸다.
        # exact-match 만 하면 필러 단어가 살아남아 정상 트리플까지 무관 판정으로 폐기됨.
        stopword_roots = ("누구", "무엇", "언제", "어디", "어떻게", "왜", "관계", "관련", "연결", "사람", "것", "무슨", "어떤")
        for t in query_tokens:
            # 조사 제거
            t_clean = t.rstrip("은는이가을를의와과로으로에게랑")
            if len(t_clean) > 1 and t_clean not in known_entity_names:
                # 질문 어미/조사 등 불용어 필터링 (접두 매칭)
                if not any(t_clean.startswith(sw) for sw in stopword_roots):
                    relation_keywords.append(t_clean)
        return relation_keywords

    def _check_relevance(
        self,
        query_text: str,
        known_entity_names: List[str],
        triples: List[Dict[str, Any]],
        relation_keywords: Optional[List[str]] = None,
        include_subject: bool = False,
    ) -> bool:
        """Check whether the given triples are relevant to the question.

        Same semantics as the original Fast Path relevance check: if no relation keywords can
        be extracted from the question, triples are considered relevant by default (no filter
        possible). Otherwise, at least one keyword must appear in a triple's predicate or object.

        include_subject=True adds the subject to the match targets. Used only by the
        ExampleMemory storage gate: when entity resolution fails, the entity token becomes a
        "keyword" and only ever appears in triple subjects, so a p/o-only check would wrongly
        reject good examples. The Fast Path fallback decision keeps the default (False).
        """
        if relation_keywords is None:
            relation_keywords = self._extract_relevance_keywords(query_text, known_entity_names)

        if not relation_keywords:
            return True

        for triple in triples:
            p = triple.get("predicate", "") or ""
            o = triple.get("object", "") or ""
            s = (triple.get("subject", "") or "") if include_subject else ""
            for kw in relation_keywords:
                if kw in p or kw in o or (include_subject and kw in s):
                    return True
        return False

    def _check_entity_exists(self, kb_id: str, entity_name: str) -> bool:
        """Check if an entity exists in the Neo4j graph.

        완전일치뿐 아니라 대소문자 무시 양방향 부분매칭까지 허용한다. 완전일치만
        보면 표기 변이("Seong Gi-hun")나 조사 잔존 토큰이 게이트에서 탈락해 Fast
        Path 자체가 스킵되는 문제가 있었다. 실제 Fast Path Cypher 들은 이미
        bidirectional CONTAINS 로 매칭하므로, 게이트도 같은 기준으로 맞춘다.
        """
        try:
            query = """
            MATCH (n:Entity)
            WHERE n.kb_id = $kb_id
              AND (
                n.name = $entity_name
                OR toLower(n.name) CONTAINS toLower($entity_name)
                OR toLower($entity_name) CONTAINS toLower(n.name)
              )
            RETURN count(n) as count
            """
            records = neo4j_client.execute_query(query, {"kb_id": kb_id, "entity_name": entity_name})
            return records[0]["count"] > 0 if records else False
        except Exception:
            return False

    def _extract_triples_from_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """LLM Cypher 쿼리 결과 record에서 정답 경로 트리플을 직접 재구성한다.

        관계-체인 템플릿의 RETURN 컬럼 관례(start/rel1/mid/rel2/end 및 generic
        subject/predicate/object)를 인식해 s-p-o 트리플로 변환한다. Fuseki의
        '쿼리 결과에서 트리플 직접 추출'과 동일한 목적.
        """
        triples: List[Dict[str, str]] = []
        seen = set()

        def add(s, p, o):
            if not (isinstance(s, str) and isinstance(p, str) and isinstance(o, str)):
                return
            s, p, o = s.strip(), p.strip(), o.strip()
            if not (s and p and o):
                return
            key = (s, p, o)
            if key in seen:
                return
            seen.add(key)
            triples.append({"subject": s, "predicate": p, "object": o,
                            "is_inverse": False, "source_node_id": None})

        for r in records or []:
            # neo4j.Record → dict 정규화 (execute_query는 neo4j.Record를 반환)
            try:
                r = dict(r)
            except Exception:
                continue
            # 의미 라벨 2-hop 컬럼(s1/p1/o1, s2/p2/o2) — predicate가 질문 관계로 relabel됨
            if r.get("s1") and r.get("p1") and r.get("o1"):
                add(r.get("s1"), r.get("p1"), r.get("o1"))
            if r.get("s2") and r.get("p2") and r.get("o2"):
                add(r.get("s2"), r.get("p2"), r.get("o2"))
            # 2-hop 체인 컬럼: start -[rel1]-> mid -[rel2]-> end
            if r.get("start") and r.get("rel1") and r.get("mid"):
                add(r.get("start"), r.get("rel1"), r.get("mid"))
            if r.get("mid") and r.get("rel2") and r.get("end"):
                add(r.get("mid"), r.get("rel2"), r.get("end"))
            # 1-hop / generic s-p-o 컬럼
            if r.get("subject") and r.get("predicate") and r.get("object"):
                add(r.get("subject"), r.get("predicate"), r.get("object"))

        return triples

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
