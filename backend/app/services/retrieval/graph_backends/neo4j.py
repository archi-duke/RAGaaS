import logging
from typing import List, Dict, Any
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
        print(f"DEBUG: [Neo4j] Generating Cypher using Doc2Onto CypherGenerator for: {query_text}")
        
        # Import settings if not already imported at top-level to avoid circular deps if any
        # But better to import at top if possible. For now, lazy import to be safe inside method or just use it.
        from app.core.config import settings
        
        try:
            generator = CypherGenerator(api_key=settings.OPENAI_API_KEY)
            # Context can be enriched with extracted entities
            context = f"관련 엔티티 후보: {', '.join(entities)}" if entities else None
            
            custom_prompt = kwargs.get("custom_query_prompt")
            
            # Inverse/Bidirectional Logic
            inv_mode = kwargs.get("inverse_extraction_mode", "auto")
            if not kwargs.get("enable_inverse_search", True):
                inv_mode = "none"

            gen_result = generator.generate(
                query_text, 
                context=context, 
                custom_prompt=custom_prompt,
                inverse_search_mode=inv_mode
            )
            cypher_query = gen_result.get("cypher")
            thought = gen_result.get("thought")
            
            print(f"DEBUG: [Neo4j] Generated Cypher: {cypher_query}")
            print(f"DEBUG: [Neo4j] Reason: {thought}")
            
            if not cypher_query:
                return {"chunk_ids": [], "sparql_query": "Generation Failed", "triples": []}
                
            # Execute generated query
            records = neo4j_client.execute_query(cypher_query)
            
            chunk_ids = set()
            discovered_entities = set()
            
            # Parse results (handle various return formats)
            for record in records:
                for key, value in record.items():
                    # If value is a Node
                    if hasattr(value, "labels"):
                        labels = set(value.labels)
                        props = dict(value)
                        
                        if "Chunk" in labels:
                            if "id" in props:
                                chunk_ids.add(props["id"])
                        elif "Entity" in labels or "Class" in labels or "Instance" in labels:
                            # It's an entity, keep track to find chunks later
                            label_ko = props.get("label_ko") or props.get("name")
                            if label_ko:
                                discovered_entities.add(label_ko)
                    # If value is string (maybe already an ID or Text)
                    elif isinstance(value, str):
                        # Simple heuristic: if it looks like a chunk ID (has underscore), try it
                        if "_" in value and "|" not in value: # doc_id_idx format
                            # Verify if it's a chunk? Too risky to assume.
                            pass
                        else:
                            # Might be an entity name
                            discovered_entities.add(value)
                            
            print(f"DEBUG: [Neo4j] Direct chunks found: {len(chunk_ids)}")
            print(f"DEBUG: [Neo4j] Discovered entities from query result: {len(discovered_entities)}")
            
            # If we found entities but no chunks, find chunks connected to these entities
            if discovered_entities:
                # Limit to prevent explosion
                target_entities = list(discovered_entities)[:20]
                
                chunk_query = """
                MATCH (e:Entity)-[:MENTIONED_IN]->(c:Chunk)
                WHERE e.label_ko IN $entities OR e.name IN $entities
                RETURN DISTINCT c.id as chunk_id
                LIMIT 50
                """
                c_records = neo4j_client.execute_query(chunk_query, {"entities": target_entities})
                for r in c_records:
                    chunk_ids.add(r["chunk_id"])
                    
            chunk_ids_list = list(chunk_ids)
            print(f"DEBUG: [Neo4j] Final chunks found: {len(chunk_ids_list)}")
            
            triples = []
            if chunk_ids_list:
                # Pass entities AND discovered entities to focus the triple retrieval
                focus_set = set(entities)
                if discovered_entities:
                    focus_set.update(discovered_entities)
                
                triples = self._fetch_relevant_triples(chunk_ids_list, list(focus_set))

            return {
                "chunk_ids": chunk_ids_list,
                "sparql_query": cypher_query,
                "triples": triples,
                "thought": thought,
                "found_entities": list(discovered_entities)
            }

        except Exception as e:
            logger.error(f"Neo4j search failed: {e}")
            import traceback
            traceback.print_exc()
            return {"chunk_ids": [], "sparql_query": "Error", "triples": []}

    def _fetch_relevant_triples(self, chunk_ids: List[str], focus_entities: List[str] = None) -> List[Dict[str, str]]:
        """Fetch triples connected to the discovered chunks, prioritizing those related to the query entities."""
        triples = []
        try:
            # Use any relationship type (not just :RELATION) since we now use dynamic types
            # Support both Doc2Onto schema (label_ko) and legacy schema (name)
            
            # Base query structure
            triples_query = """
            MATCH (s:Entity)-[r]->(o:Entity)
            WHERE type(r) <> 'MENTIONED_IN'
              AND ((s)-[:MENTIONED_IN]->(:Chunk {id: $chunk_id}) 
                   OR (o)-[:MENTIONED_IN]->(:Chunk {id: $chunk_id}))
            """
            
            # Apply entity filter if provided to reduce noise
            params = {"chunk_id": None} # placeholder
            if focus_entities:
                # Safe matching with COALESCE to handle potential NULLs
                triples_query += """
                AND (COALESCE(s.name, '') IN $entities OR COALESCE(o.name, '') IN $entities OR COALESCE(s.label_ko, '') IN $entities OR COALESCE(o.label_ko, '') IN $entities)
                """
                params["entities"] = focus_entities
            
            triples_query += """
            RETURN DISTINCT 
                COALESCE(s.label_ko, s.name, "Node(" + elementId(s) + ")") as subj, 
                type(r) as pred, 
                COALESCE(o.label_ko, o.name, "Node(" + elementId(o) + ")") as obj
            LIMIT 20
            """
            
            print(f"DEBUG: Fetching triples with focus_entities: {focus_entities}")

            seen_triples = set()
            # If entity filter is active, we can scan more chunks
            check_chunks = chunk_ids[:30] if focus_entities else chunk_ids[:5]
            
            for chunk_id in check_chunks:

                try:
                    p = params.copy()
                    p["chunk_id"] = chunk_id
                    t_records = neo4j_client.execute_query(triples_query, p)
                    for r in t_records:
                        triple_key = (r["subj"], r["pred"], r["obj"])
                        if triple_key not in seen_triples:
                            seen_triples.add(triple_key)
                            triples.append({
                                "subject": r["subj"], 
                                "predicate": r["pred"], 
                                "object": r["obj"]
                            })
                except Exception as e:
                    logger.warning(f"Error fetching triples for chunk {chunk_id}: {e}")
            
            print(f"DEBUG: Found {len(triples)} relevant triples from discovered chunks (Focus: {focus_entities})")
        except Exception as e:
            logger.error(f"Error in _fetch_relevant_triples: {e}")
        
        return triples

