from typing import List, Dict, Any, Optional
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
        
        # 1. Analyze query for semantic understanding
        query_analysis = await self._analyze_query(query, llm_client=llm_client, llm_model=llm_model_name)
        log(f"DEBUG: Query Analysis -> Type: {query_analysis.get('query_type')}, Hops: {query_analysis.get('hops', 1)}, Rel: {query_analysis.get('relationship_type')}")
        
        # 2. Extract Entities from Query
        entities = await self._extract_entities(kb_id, query, llm_client=llm_client, llm_model=llm_model_name)
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
        
        # Detect if query asks for multi-hop relationships
        if any(keyword in query.lower() for keyword in ["의 스승의", "의 제자의", "master's master", "student's student"]):
            graph_hops = max(graph_hops, 2)
            log(f"DEBUG: 🔀 Detected multi-hop query, setting hops to {graph_hops}")
        
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
            results = await self._fetch_chunks(kb_id, chunk_ids, query, top_k)
        
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
        metadata = {
            "sparql_query": graph_result.get("sparql_query", ""),
            "extracted_entities": entities,
            "expanded_entities": expanded_entities,
            "found_graph_entities": found_graph_entities, # Add this for debugging
            "triples": graph_result.get("triples", []),
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

    async def _extract_entities(self, kb_id: str, query: str, llm_client=None, llm_model: str = "gpt-4o-mini") -> List[str]:
        """Extract main entities from the query using LLM and spaCy Gazetteer."""
        entities = set()
        
        # 1. LLM Extraction
        prompt = f"""
        Extract key entities (subjects, objects, concepts, proper nouns) from the search query.
        Include specific terms that might be nodes in a knowledge graph.
        Don't be too generic (e.g., avoid "technology" if a specific name is implied, but include "1인자" or "Master" if present).
        
        IMPORTANT: 
        - Keep entities in their ORIGINAL language as they appear in the query. 
        - Do NOT translate them (e.g., if query is "성기훈", entity must be "성기훈", not "Seong Gi-hun").
        - If needed, you can provide English synonyms in a separate list.
        
        Query: {query}
        
        Output format: {{"entities": ["성기훈", "오일남"], "translated_entities": ["Seong Gi-hun", "Oh Il-nam"]}}
        """
        try:
            if llm_client is None:
                raise ValueError("Graph search model client is not configured.")
            client = llm_client
            response = await client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": "You are a precise entity extractor for Knowledge Graphs. Output JSON only. Never translate entities in the main list."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            for e in data.get("entities", []):
                entities.add(e)
            
            # Combine translated entities for broader recall
            for e in data.get("translated_entities", []):
                entities.add(e)
                
        except Exception as e:
            logger.error(f"Error extracting query entities with LLM: {e}")

        # 2. spaCy Gazetteer Extraction (Use known entities)
        try:
            from app.services.ingestion.spacy_processor import SpacyGraphProcessor
            # Instantiate processor to access known entities map
            processor = SpacyGraphProcessor(kb_id)
            
            # Use inner nlp pipeline directly? Or add a method to processor to extract from query?
            # Re-using extract_graph_elements seems too heavy as it builds triples.
            # We just want the entities.
            
            # Let's use the processor's resources
            doc = processor.nlp(query)
            
            # Matcher
            matches = processor.matcher(doc)
            for match_id, start, end in matches:
                span = doc[start:end]
                # Apply same normalization!
                norm = processor._normalize_entity(span)
                if norm:
                    entities.add(norm)
            
            # NER (Optional: LLM usually covers this, but spaCy local might catch specific patterns)
            for ent in doc.ents:
                norm = processor._normalize_entity(ent)
                if norm:
                    entities.add(norm)
                    
        except Exception as e:
            logger.warning(f"Error extracting query entities with spaCy: {e}")
            
        return list(entities)
    
    async def _analyze_query(self, query: str, llm_client=None, llm_model: str = "gpt-4o-mini") -> Dict[str, Any]:
        """Analyze query to understand semantic intent and relationship types."""
        analysis = {
            "query_type": "simple",  # simple, relationship, multi_hop
            "relationship_keywords": [],
            "direction": None  # forward, backward, bidirectional
        }
        
        # Detect relationship queries
        relationship_patterns = {
            "master": ["스승", "선생", "master", "teacher", "mentor"],
            "student": ["제자", "학생", "student", "disciple"],
            "전수": ["전수", "전해", "배우", "가르치", "teach", "learn"],
            "관계": ["관계", "연결", "relationship", "connection"]
        }
        
        query_lower = query.lower()
        
        for rel_type, keywords in relationship_patterns.items():
            if any(kw in query_lower for kw in keywords):
                analysis["relationship_keywords"].append(rel_type)
        
        # Detect multi-hop queries
        multi_hop_patterns = ["의 스승의", "의 제자의", "'s master's", "'s student's", "누구의 누구"]
        if any(pattern in query_lower for pattern in multi_hop_patterns):
            analysis["query_type"] = "multi_hop"
            analysis["hops"] = 2  # Detect number of hops
        elif any(kw in query_lower for kw in ["스승", "제자", "master", "student", "teacher"]):
            analysis["query_type"] = "relationship"
        
        # Use LLM for better understanding
        try:
            prompt = f"""
            Analyze this search query and extract:
            1. The main subject/entity being asked about
            2. The type of relationship being queried (if any)
            3. Whether it's a multi-hop query (e.g., "A's B's C")
            4. Potential alternative entity names or aliases
            
            Query: {query}
            
            Output format:
            {{
                "subject": "main entity name",
                "relationship_type": "master/student/creator/etc or null",
                "is_multi_hop": true/false,
                "hop_count": 1 or 2 or 3,
                "alternatives": ["alternative names or related entities"]
            }}
            """
            
            if llm_client is None:
                raise ValueError("Graph search model client is not configured.")
            client = llm_client
            response = await client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": "You are a query analyzer for graph search. Be precise and output only JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            llm_analysis = json.loads(response.choices[0].message.content)
            analysis.update(llm_analysis)
            
        except Exception as e:
            logger.warning(f"Error in LLM query analysis: {e}")
        
        return analysis
    
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
            def sparql_escape(s):
                chars_to_escape = r".*+?^${}()|[]\\"
                for char in chars_to_escape:
                    s = s.replace(char, "\\" + char)
                return s

            safe_entities = [sparql_escape(e) for e in entities]
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

    async def _fetch_chunks(self, kb_id: str, chunk_ids: List[str], query: str, top_k: int) -> List[Dict[str, Any]]:
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
