from typing import List, Dict, Any
from .base import RetrievalStrategy
from .graph_backends import GraphBackendFactory
from app.core.fuseki import fuseki_client
from app.core.neo4j_client import neo4j_client
from app.core.config import settings
from app.core.milvus import create_collection
from openai import AsyncOpenAI
import json
import logging
import re
import urllib.parse
from app.services.embedding import embedding_service
import numpy as np

logger = logging.getLogger(__name__)

class GraphRetrievalStrategy(RetrievalStrategy):
    def __init__(self):
        self.namespace_entity = "http://rag.local/entity/"
        self.namespace_relation = "http://rag.local/relation/"
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def search(self, kb_id: str, query: str, top_k: int, **kwargs) -> List[Dict[str, Any]]:
        use_raw_log = kwargs.get("use_raw_log", False)
        trace_logs = []
        
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
            
            if is_first_log:
                PREFIX = f"DEBUG: {start_dt} -"
                is_first_log = False
                formatted_msg = f"{PREFIX} {clean_msg}"
            else:
                formatted_msg = f"DEBUG [{elapsed_ms} ms] : {clean_msg}"
            
            print(formatted_msg)
            if use_raw_log:
                trace_logs.append(formatted_msg)

        log(f"🚀 Graph Search Start for query: {query}")
        
        # 1. Analyze query for semantic understanding
        query_analysis = await self._analyze_query(query)
        log(f"DEBUG: Query Analysis -> Type: {query_analysis.get('query_type')}, Hops: {query_analysis.get('hops', 1)}, Rel: {query_analysis.get('relationship_type')}")
        
        # 2. Extract Entities from Query
        entities = await self._extract_entities(kb_id, query)
        log(f"DEBUG: 🔍 Extracted entities: {entities}")
        
        # 3. Expand entities - find related entities in graph
        expanded_entities = await self._expand_entities(kb_id, entities)
        log(f"DEBUG: 🔗 Expanded entities: {expanded_entities}")
        
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
        graph_backend_type = kwargs.get("graph_backend", "ontology")
        
        # Use Factory to get backend instance
        backend = GraphBackendFactory.get_backend(graph_backend_type)
        
        # Execute query via backend strategy
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
        
        # Log triple count
        found_triples = graph_result.get("triples", [])
        log(f"DEBUG: 🕸️ Graph Query Completed. Found {len(found_triples)} triples.")

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
            log(f"DEBUG: 🔄 Fallback triggered. Reason: No direct graph-to-chunk matches found.")
            log(f"DEBUG: Executing Entity-Guided Hybrid Search with entities: {all_entities}")
            fallback_results = await self._fallback_search(kb_id, query, all_entities, top_k)
            if fallback_results:
                log(f"DEBUG: ✅ Entity-Guided Search success! Retrieved {len(fallback_results)} chunks.")
                results = fallback_results
        
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

    async def _extract_entities(self, kb_id: str, query: str) -> List[str]:
        """Extract main entities from the query using LLM and spaCy Gazetteer."""
        entities = set()
        
        # 1. LLM Extraction
        prompt = f"""
        Extract key entities (subjects, objects, concepts, proper nouns) from the search query.
        Include specific terms that might be nodes in a knowledge graph.
        Don't be too generic (e.g., avoid "technology" if a specific name is implied, but include "1인자" or "Master" if present).
        
        Query: {query}
        
        Output format: {{"entities": ["Elon Musk", "SpaceX", "CEO"]}}
        """
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini", # Use smarter model for extraction
                messages=[
                    {"role": "system", "content": "You are a precise entity extractor for Knowledge Graphs. Output JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            for e in data.get("entities", []):
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
    
    async def _analyze_query(self, query: str) -> Dict[str, Any]:
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
            
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
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
    
    async def _expand_entities(self, kb_id: str, entities: List[str]) -> List[str]:
        """Expand entities by finding related entities in the graph."""
        if not entities:
            return []
        
        expanded = set()
        
        # Escape entities for SPARQL
        safe_entities = [re.escape(e) for e in entities]
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
        
        try:
            results = fuseki_client.query_sparql(kb_id, expand_query)
            for binding in results.get("results", {}).get("bindings", []):
                label = binding.get("relatedLabel", {}).get("value", "")
                if label and label not in entities:
                    expanded.add(label)
        except Exception as e:
            logger.warning(f"Error expanding entities: {e}")
        
        return list(expanded)[:10]  # Limit to prevent explosion

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
        collection = create_collection(kb_id)
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
        query_vec = (await embedding_service.get_embeddings([query]))[0]
        
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
