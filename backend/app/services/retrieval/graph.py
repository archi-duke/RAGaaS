from typing import List, Dict, Any, Optional, Tuple
from .base import RetrievalStrategy
from .graph_backends import GraphBackendFactory
from app.core.fuseki import fuseki_client
from app.core.neo4j_client import neo4j_client
from openai import AsyncOpenAI
import json
import logging
import re
import urllib.parse
from app.services.embedding import embedding_service as default_embedding_service
from app.services.retrieval.sparql_utils import escape_sparql_regex
import numpy as np

logger = logging.getLogger(__name__)

class GraphRetrievalStrategy(RetrievalStrategy):
    def __init__(self):
        self.namespace_entity = "http://rag.local/entity/"
        self.namespace_relation = "http://rag.local/relation/"

    async def search(self, kb_id: str, query: str, top_k: int, **kwargs) -> List[Dict[str, Any]]:
        use_raw_log = kwargs.get("use_raw_log", False)
        trace_logs = []

        # LLM / Embedding 동적 설정
        llm_model_config = kwargs.get("llm_model_config") or {}
        emb_service = kwargs.get("embedding_service", default_embedding_service)

        if not llm_model_config:
            raise ValueError("Graph search model is not configured.")
        from app.core.models_resolver import resolve_model_config
        resolved_llm = await resolve_model_config(llm_model_config)
        if not resolved_llm.get("api_key"):
            raise ValueError("Graph search API key is not configured.")
        llm_client = AsyncOpenAI(
            api_key=resolved_llm.get("api_key"),
            **({"base_url": resolved_llm["base_url"]} if resolved_llm.get("base_url") else {}),
            **({"default_headers": resolved_llm["extra_headers"]} if resolved_llm.get("extra_headers") else {}),
        )
        llm_model_name = resolved_llm.get("model", "gpt-4o-mini")
        
        import time
        from datetime import datetime
        
        start_time = time.time()
        start_dt = datetime.fromtimestamp(start_time).strftime('%Y/%m/%d %H:%M:%S')
        is_first_log = True

        def log(msg: str):
            nonlocal is_first_log
            current_time = time.time()
            elapsed_ms = int((current_time - start_time) * 1000)
            
            # Clean up existing prefix if present to standardize
            clean_msg = msg.lstrip()
            if clean_msg.startswith("DEBUG:"):
                clean_msg = clean_msg[6:].strip()
            
            # Simplified format per user request
            if is_first_log:
                formatted_msg = f"[Graph] Start Search ({start_dt}): {clean_msg}"
                is_first_log = False
            else:
                formatted_msg = f"[{elapsed_ms}ms] {clean_msg}"
            
            trace_logs.append(formatted_msg)

        log(f"🚀 Graph Search Start for query: {query}")
        
        # 1+2. Analyze query + extract entities in a SINGLE LLM call (병합: 2 호출 → 1)
        entities, query_analysis = await self._analyze_and_extract(kb_id, query, llm_client=llm_client, llm_model=llm_model_name)
        log(f"DEBUG: Query Analysis -> Type: {query_analysis.get('query_type')}, Hops: {query_analysis.get('hop_count', 1)}, Rel: {query_analysis.get('relationship_type')}, Roles: {query_analysis.get('entity_roles')}")
        log(f"DEBUG: 🔍 Extracted entities: {entities}")
        
        # 3. Expand entities - find related entities in graph (conditional)
        graph_backend_type = kwargs.get("graph_backend", "ontology")
        enable_entity_expansion = kwargs.get("enable_entity_expansion", False)
        
        # Combine with alternatives from analysis for better coverage
        alternatives = query_analysis.get("alternatives", [])
        search_entities = list(set(entities + alternatives))
        
        expanded_entities = []
        if enable_entity_expansion:
            expanded_entities = await self._expand_entities(kb_id, search_entities, backend_type=graph_backend_type)
            log(f"DEBUG: 🔗 Expanded entities: {expanded_entities}")
        else:
            log(f"DEBUG: 🔗 Entity expansion disabled")
        
        all_entities = list(set(entities + expanded_entities))
        
        if not all_entities:
            log(f"No entities found in query: {query}")
            return []

        # 4. SPARQL Search with semantic relationship understanding
        graph_hops = kwargs.get("graph_hops", 1)
        
        # Detect multi-hop: LLM hop_count 우선, 문자열매칭은 폴백
        llm_hops = query_analysis.get("hop_count")
        if isinstance(llm_hops, int) and llm_hops >= 2:
            graph_hops = max(graph_hops, llm_hops)
            log(f"DEBUG: 🔀 Multi-hop by LLM hop_count={llm_hops}, setting hops to {graph_hops}")
        elif any(keyword in query.lower() for keyword in ["의 스승의", "의 제자의", "master's master", "student's student"]):
            graph_hops = max(graph_hops, 2)
            log(f"DEBUG: 🔀 Detected multi-hop query (fallback), setting hops to {graph_hops}")
        
        log(f"DEBUG: 🔎 Searching graph with hops={graph_hops}")
        
        # Use Factory to get backend instance
        backend = GraphBackendFactory.get_backend(graph_backend_type)
        
        # Execute query via backend strategy
        graph_result = await backend.query(
            kb_id=kb_id,
            entities=all_entities,
            hops=graph_hops,
            query_type=query_analysis.get("query_type"),
            relationship_keywords=query_analysis.get("relationship_keywords", []),
            entity_roles=query_analysis.get("entity_roles", {}),
            query_text=query,
            **kwargs
        )

        # Merge backend trace logs
        if "trace_logs" in graph_result:
            trace_logs.extend(graph_result["trace_logs"])
        
        # Log triple count
        found_triples = graph_result.get("triples", [])
        log(f"DEBUG: 🕸️ Graph Query Completed. Found {len(found_triples)} triples.")
        if found_triples:
            log(f"DEBUG: Triple Samples: {found_triples[:5]}...")

        # Safely get chunk_ids allowing default empty list if key missing
        chunk_ids = graph_result.get("chunk_ids", [])
        
        # [FIX] Normalize chunk IDs: Fuseki (fallback) uses '_section_' but Milvus uses '_'
        if chunk_ids:
            chunk_ids = [str(cid).replace("_section_", "_") for cid in chunk_ids]

        if chunk_ids:
             log(f"DEBUG: ✅ Direct Graph Mapping Success: Mapped {len(chunk_ids)} chunks from graph nodes. IDs: {chunk_ids}")
        else:
             log(f"DEBUG: ⚠️ No direct chunks mapped from graph nodes.")

        # Else: Silent, as we will log Entity-Guided step below
        
        # 5. Fetch content from Milvus
        results = []
        if chunk_ids:
            results = await self._fetch_chunks(kb_id, chunk_ids, query, top_k, emb_service=emb_service)
        
        # 6. Graph-Guided Fallback: If SPARQL found entities but no chunks, or if no results at all
        # We use the entities found by SPARQL (e.g. 'Duke', 'Oh Il-nam') to guide the vector/hybrid search
        found_graph_entities = graph_result.get("found_entities", [])
        if found_graph_entities:
            log(f"DEBUG: Graph discovered new entities: {found_graph_entities}. Using for guided retrieval.")
            all_entities.extend(found_graph_entities)
            # Remove duplicates
            all_entities = list(set(all_entities))
            
        if not results or (len(results) == 1 and results[0].get("chunk_id") == "GRAPH_METADATA_ONLY"):
             # [MODIFIED] Fallback Removed as per user request
             # log(f"DEBUG: 🔄 Fallback triggered. Reason: No direct graph-to-chunk matches found.")
             # log(f"DEBUG: Executing Entity-Guided Hybrid Search with entities: {all_entities}")
             # fallback_results = await self._fallback_search(kb_id, query, all_entities, top_k)
             # if fallback_results:
             #     log(f"DEBUG: ✅ Entity-Guided Search success! Retrieved {len(fallback_results)} chunks.")
             #     results = fallback_results
             log(f"DEBUG: Strict Mode - Fallback search disabled. Returning empty/metadata-only results.")

        
        # 7. Add graph metadata
        # dead-chip 방지: 추출 엔티티 중 실제 그래프 노드로 존재하는 것만 clickable 로 표시.
        # (번역 변이 "Seong Gi-hun" 이나 일반개념어는 그래프에 노드가 없어 뷰어가 빈 화면이 됨)
        graph_triples = graph_result.get("triples", [])
        clickable_entities = self._compute_clickable_entities(entities, graph_triples)
        metadata = {
            "sparql_query": graph_result.get("sparql_query", ""),
            "extracted_entities": entities,
            "clickable_entities": clickable_entities,
            "expanded_entities": expanded_entities,
            "found_graph_entities": found_graph_entities, # Add this for debugging
            "triples": graph_triples,
            "total_chunks_found": len(results), # Use final results count (includes Entity-Guided chunks)
            "query_analysis": query_analysis,
            "trace_logs": trace_logs
        }

        if results and results[0].get("chunk_id") != "GRAPH_METADATA_ONLY":
            log(f"DEBUG: Attaching graph metadata to {len(results)} results")
            for res in results:
                res["graph_metadata"] = metadata
        else:
            # Return dummy result with metadata
            log("DEBUG: Returning metadata-only result")
            results = [{
                "chunk_id": "GRAPH_METADATA_ONLY",
                "content": "",
                "score": 0.0,
                "metadata": {"source": "graph_metadata"},
                "graph_metadata": metadata
            }]
        
        return results

    def _compute_clickable_entities(self, entities: List[str], triples: List[Dict[str, Any]]) -> List[str]:
        """추출 엔티티 중 실제 그래프 노드(트리플 subject/object)로 존재하는 것만 반환.

        그래프 뷰어는 노드가 있는 엔티티만 확장 가능하므로, 노드가 없는 번역 변이나
        일반개념어(dead-chip)를 UI 가 비활성화할 수 있도록 clickable 목록을 계산한다.
        정규화(밑줄→공백, 소문자, trim) 후 완전일치, 또는 2자 이상 양방향 부분포함으로 판정.
        """
        def _norm(s: Any) -> str:
            return str(s or "").replace("_", " ").strip().lower()

        node_texts = set()
        for t in triples or []:
            for key in ("subject", "object"):
                nt = _norm(t.get(key))
                if nt:
                    node_texts.add(nt)

        clickable = []
        for e in entities:
            ne = _norm(e)
            if not ne:
                continue
            if ne in node_texts:
                clickable.append(e)
                continue
            # 2자 이상 양방향 부분포함 (예: "장풍" ↔ "전수받은 장풍")
            if len(ne) >= 2 and any(
                (len(nt) >= 2 and (ne in nt or nt in ne)) for nt in node_texts
            ):
                clickable.append(e)
        return clickable

    async def _analyze_and_extract(self, kb_id: str, query: str, llm_client=None, llm_model: str = "gpt-4o-mini") -> Tuple[List[str], Dict[str, Any]]:
        """질의 분석 + 엔티티 추출을 단일 LLM 호출로 병합 (기존 2회 → 1회).

        See docs/design-query-analysis-merge.md.

        기존 _analyze_query + _extract_entities 두 LLM 호출을 하나로 합치고,
        엔티티별 문법 역할(subject/object/ambiguous)을 추가로 뽑는다. spaCy
        가제티어 추출은 로컬(비 LLM)이라 그대로 유지한다.

        Returns:
            (entities_list, query_analysis)
            - entities_list: 원문 엔티티 + 번역 동의어 + spaCy 가제티어 (기존 반환 호환)
            - query_analysis: query_type/relationship_keywords/alternatives/hop_count
              + entity_roles({원본토큰: role}) — 백엔드 Pattern 분류의 1차 신호
        """
        analysis: Dict[str, Any] = {
            "query_type": "simple",
            "relationship_keywords": [],
            "direction": None,
            "alternatives": [],
            "hop_count": 1,
            "entity_roles": {},
        }
        entities = set()

        # --- 키워드 기반 relationship_keywords 초안 (기존 _analyze_query 계승) ---
        relationship_patterns = {
            "master": ["스승", "선생", "master", "teacher", "mentor"],
            "student": ["제자", "학생", "student", "disciple"],
            "전수": ["전수", "전해", "배우", "가르치", "teach", "learn"],
            "관계": ["관계", "연결", "relationship", "connection"],
        }
        query_lower = query.lower()
        for rel_type, keywords in relationship_patterns.items():
            if any(kw in query_lower for kw in keywords):
                analysis["relationship_keywords"].append(rel_type)

        # --- 단일 LLM 호출: 엔티티(역할 포함) + 구조 분석 ---
        prompt = f"""
        Analyze this knowledge-graph search query and output JSON only.

        Extract:
        1. entities: key entities (subjects, objects, proper nouns) as objects with a grammatical "role".
           - role = "subject" if the entity is the actor/owner of the relationship being asked,
                    "object" if it is the target, "ambiguous" if unclear or symmetric.
           - Keep entity "name" in its ORIGINAL language as it appears in the query. Do NOT translate.
             (e.g. query "성기훈" -> name "성기훈", never "Seong Gi-hun")
        2. translated_entities: English synonyms/aliases (for recall). Separate list of plain strings.
        3. relationship_type: the relation asked (master/student/creator/etc) or null.
        4. is_multi_hop: true if it chains relations (e.g. "A's B's C").
        5. hop_count: 1, 2, or 3.
        6. alternatives: alternative entity names or related entities.

        Query: {query}

        Output format:
        {{
          "entities": [{{"name": "성기훈", "role": "subject"}}, {{"name": "오일남", "role": "object"}}],
          "translated_entities": ["Seong Gi-hun", "Oh Il-nam"],
          "relationship_type": "master",
          "is_multi_hop": false,
          "hop_count": 1,
          "alternatives": []
        }}
        """
        try:
            if llm_client is None:
                raise ValueError("Graph search model client is not configured.")
            response = await llm_client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": "You are a precise query analyzer and entity extractor for Knowledge Graphs. Output JSON only. Never translate entity names in the main 'entities' list."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)

            # 엔티티 + 역할
            for ent in data.get("entities", []):
                if isinstance(ent, dict):
                    name = ent.get("name")
                    if name:
                        entities.add(name)
                        role = ent.get("role")
                        if role in ("subject", "object", "ambiguous"):
                            analysis["entity_roles"][name] = role
                elif isinstance(ent, str) and ent:
                    entities.add(ent)
            # 번역 동의어 (recall 보강, 역할 없음)
            for e in data.get("translated_entities", []):
                if e:
                    entities.add(e)

            # 구조 분석
            if data.get("relationship_type"):
                analysis["relationship_type"] = data["relationship_type"]
            analysis["alternatives"] = data.get("alternatives", []) or []
            hop_count = data.get("hop_count")
            if isinstance(hop_count, int) and hop_count >= 1:
                analysis["hop_count"] = hop_count
            if data.get("is_multi_hop") or analysis["hop_count"] >= 2:
                analysis["query_type"] = "multi_hop"
            elif analysis["relationship_keywords"] or data.get("relationship_type"):
                analysis["query_type"] = "relationship"
        except Exception as e:
            logger.warning(f"[Graph] Merged analyze/extract LLM call failed: {e}")

        # --- spaCy 가제티어 (로컬, 비 LLM — 기존 _extract_entities 계승) ---
        try:
            from app.services.ingestion.spacy_processor import SpacyGraphProcessor
            processor = SpacyGraphProcessor(kb_id)
            doc = processor.nlp(query)
            for match_id, start, end in processor.matcher(doc):
                norm = processor._normalize_entity(doc[start:end])
                if norm:
                    entities.add(norm)
            for ent in doc.ents:
                norm = processor._normalize_entity(ent)
                if norm:
                    entities.add(norm)
        except Exception as e:
            logger.warning(f"Error extracting query entities with spaCy: {e}")

        return list(entities), analysis

    async def _expand_entities(self, kb_id: str, entities: List[str], backend_type: str = "ontology") -> List[str]:
        """Expand entities by finding related entities in the graph."""
        if not entities:
            return []
        
        # Internal debug log
        def log_debug(msg):
            print(f"[DEBUG_EXPAND] {msg}")

        log_debug(f"Input Entities: {entities}, Backend: {backend_type}, KB: {kb_id}")
        expanded = set()
        
        if backend_type == "neo4j":
            # Neo4j Expansion
            try:
                from app.core.neo4j_client import neo4j_client
                # Escape entities for regex
                safe_entities = [re.escape(e) for e in entities]
                regex_pattern = "(?i).*(" + "|".join(safe_entities) + ").*"
                
                # We search for neighbors of the given entities with more flexible matching
                # Fix: Handle nulls in label_ko safely using coalesce or separate conditions
                expand_query = """
                MATCH (n:Entity {kb_id: $kb_id})
                WHERE n.name =~ $regex_pattern OR coalesce(n.label_ko, '') =~ $regex_pattern
                MATCH (n)-[r]-(m)
                WHERE NOT (m.name IN $entities) AND NOT (coalesce(m.label_ko, '') IN $entities)
                RETURN DISTINCT coalesce(m.label_ko, m.name) AS relatedLabel
                LIMIT 50
                """
                log_debug(f"Executing Neo4j Expand Query with pattern: {regex_pattern}")
                records = neo4j_client.execute_query(expand_query, parameters={
                    "entities": entities, 
                    "regex_pattern": regex_pattern,
                    "kb_id": kb_id
                })
                log_debug(f"Neo4j Result count: {len(records)}")
                for record in records:
                    label = record.get("relatedLabel")
                    if label:
                        expanded.add(label)
            except Exception as e:
                log_debug(f"Error expanding entities in Neo4j: {e}")
        else:
            # Fuseki (SPARQL) Expansion
            # Escape entities for SPARQL Regex (avoiding re.escape which adds too many backslashes)
            safe_entities = [escape_sparql_regex(e) for e in entities]
            regex_pattern = "|".join(safe_entities)
            
            # Find entities connected to the initial entities
            expand_query = f"""
            PREFIX rel: <{self.namespace_relation}>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            
            SELECT DISTINCT ?relatedLabel
            WHERE {{
                {{
                    # Find entities with matching labels
                    ?entity rdfs:label ?entityLabel .
                    FILTER regex(?entityLabel, "({regex_pattern})", "i")
                    
                    # Get connected entities (1-hop)
                    ?entity ?pred ?related .
                    FILTER (?pred != rel:hasSource)
                    FILTER (?pred != rdfs:label)
                    
                    OPTIONAL {{ ?related rdfs:label ?relatedLabel }}
                }}
                UNION
                {{
                    # Inverse direction
                    ?related ?pred ?entity .
                    FILTER (?pred != rel:hasSource)
                    FILTER (?pred != rdfs:label)
                    
                    ?entity rdfs:label ?entityLabel .
                    FILTER regex(?entityLabel, "({regex_pattern})", "i")
                    
                    OPTIONAL {{ ?related rdfs:label ?relatedLabel }}
                }}
            }}
            LIMIT 50
            """
            log_debug(f"Executing Fuseki Expand Query with pattern: {regex_pattern}")
            
            try:
                from app.core.fuseki import fuseki_client
                results = fuseki_client.query_sparql(kb_id, expand_query)
                bindings = results.get("results", {}).get("bindings", [])
                log_debug(f"Fuseki Result bindings count: {len(bindings)}")
                for binding in bindings:
                    label = binding.get("relatedLabel", {}).get("value", "")
                    if label and label not in entities:
                        expanded.add(label)
            except Exception as e:
                log_debug(f"Error expanding entities in Fuseki: {e}")
        
        res = list(expanded)[:10]
        log_debug(f"Final Expanded Entities: {res}")
        return res

    async def _fallback_search(self, kb_id: str, query: str, entities: List[str], top_k: int) -> List[Dict[str, Any]]:
        """Fallback to hybrid vector+keyword search when graph doesn't have complete data."""
        from .vector import VectorRetrievalStrategy
        from .hybrid import HybridRetrievalStrategy
        
        # Construct enhanced query with entities
        enhanced_query = query + " " + " ".join(entities)
        
        print(f"DEBUG: Fallback search with query: {enhanced_query}")
        
        try:
            # Use hybrid search for best results
            hybrid_strategy = HybridRetrievalStrategy()
            results = await hybrid_strategy.search(
                kb_id=kb_id,
                query=enhanced_query,
                top_k=top_k,
                score_threshold=0.0,
                metric_type="COSINE"
            )
            
            # Mark these as fallback results
            for result in results:
                if "metadata" not in result:
                    result["metadata"] = {}
                result["metadata"]["source"] = "graph_fallback"
            
            return results
        except Exception as e:
            logger.error(f"Error in fallback search: {e}")
            return []

    async def _fetch_chunks(self, kb_id: str, chunk_ids: List[str], query: str, top_k: int, emb_service=None) -> List[Dict[str, Any]]:
        if emb_service is None:
            emb_service = default_embedding_service
        # Get existing collection
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        from pymilvus import Collection
        collection = Collection(collection_name)
        collection.load()
        
        # Limit to avoid huge query
        target_ids = chunk_ids[:100] # Safety limit
        
        expr = f'chunk_id in {json.dumps(target_ids)}'
        
        results = collection.query(
            expr=expr,
            output_fields=["content", "doc_id", "chunk_id", "vector"]
        )
        
        retrieved = []
        
        # Calculate cosine similarity for scoring (so we can merge with vector results)
        query_vec = (await emb_service.get_embeddings([query]))[0]
        
        for hit in results:
            chunk_vector = hit.get("vector")
            cosine_score = 0.0
            if chunk_vector:
                cosine_score = self._cosine_similarity(query_vec, chunk_vector)
            
            # BOOST: Graph-discovered chunks get a score boost
            # These were found through semantic graph relationships,
            # so they're likely more relevant than pure vector similarity suggests
            graph_boost = 1.5  # 50% boost for graph-discovered chunks
            boosted_score = min(cosine_score * graph_boost, 1.0)  # Cap at 1.0
            
            retrieved.append({
                "chunk_id": hit.get("chunk_id"),
                "content": hit.get("content"),
                "score": boosted_score,
                "metadata": {
                    "doc_id": hit.get("doc_id"),
                    "source": "graph",
                    "original_score": cosine_score,
                    "boosted": True
                }
            })
            
        retrieved.sort(key=lambda x: x["score"], reverse=True)
        return retrieved[:top_k]

    def _cosine_similarity(self, vec1, vec2) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))
