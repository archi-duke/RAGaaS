import re
import urllib.parse
import logging
from typing import List, Dict, Any, Tuple
from .base import GraphBackend
from app.core.fuseki import fuseki_client

logger = logging.getLogger(__name__)

class FusekiBackend(GraphBackend):
    """Fuseki (Ontology) implementation of GraphBackend."""

    def __init__(self):
        self.namespace_relation = "http://rag.local/relation/"
        self.generator = None
        try:
            from app.doc2onto.qa.sparql_generator import SPARQLGenerator
            from app.core.config import settings
            self.generator = SPARQLGenerator(api_key=settings.OPENAI_API_KEY)
            print("DEBUG: [Fuseki] Doc2Onto SPARQLGenerator initialized successfully")
        except ImportError as e:
            print(f"WARNING: [Fuseki] Could not import Doc2Onto SPARQLGenerator: {e}. Using fallback logic.")
        except Exception as e:
            print(f"WARNING: [Fuseki] Failed to initialize SPARQLGenerator: {e}")

    async def query(
        self,
        kb_id: str,
        entities: List[str],
        hops: int,
        query_type: str,
        relationship_keywords: List[str],
        query_text: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Execute graph query on Fuseki using SPARQL."""
        
        chunk_ids = []
        triples = []
        sparql_query = ""

        # 1. Try using SPARQLGenerator (LLM-based)
        if self.generator and query_text:
            print(f"DEBUG: [Fuseki] Generating SPARQL for: {query_text} (inverse_relation='auto')")
            try:
                # Use the new 'inverse_relation' parameter
                inv_mode = kwargs.get("inverse_extraction_mode", "auto")
                if not kwargs.get("enable_inverse_search", True):
                    inv_mode = "none"
                    
                gen_result = self.generator.generate(
                    question=query_text,
                    context=f"Entities: {', '.join(entities)}",
                    mode="ontology",
                    inverse_relation=inv_mode,
                    custom_prompt=kwargs.get("custom_query_prompt")
                )
                
                generated_sparql = gen_result.get("sparql")
                if generated_sparql:
                    print(f"DEBUG: [Fuseki] Generated SPARQL:\n{generated_sparql}")
                    
                    # Ensure standard prefixes are present
                    prefixes = """
                    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    PREFIX owl: <http://www.w3.org/2002/07/owl#>
                    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    PREFIX inst: <http://rag.local/entity/> 
                    PREFIX rel: <http://rag.local/relation/> 
                    PREFIX prop: <http://rag.local/property/>

                    """
                    
                    
                    # Inject FROM <urn:x-arq:UnionGraph> to search across all named graphs
                    # This is crucial because Doc2Onto loads data (base.trig) into named graphs
                    if "WHERE" in generated_sparql:
                        # Simple injection: replace the first 'WHERE' with 'FROM <urn:x-arq:UnionGraph> WHERE'
                        # This ensures we search across all named graphs where Doc2Onto puts the data
                        sparql_query_content = generated_sparql.replace("WHERE", "FROM <urn:x-arq:UnionGraph>\nWHERE", 1)
                    else:
                        sparql_query_content = generated_sparql

                    full_query = prefixes + sparql_query_content
                    
                    # Execute
                    results = fuseki_client.query_sparql(kb_id, full_query)
                    bindings = results.get("results", {}).get("bindings", [])
                    
                    if bindings:
                         print(f"DEBUG: [Fuseki] Generator query returned {len(bindings)} results")
                         sparql_query = full_query
                         
                    if bindings:
                        # Process results from generator query
                        found_entities = set()
                        for binding in bindings:
                            # 1. Extract triples for display
                             for var_name, value_dict in binding.items():
                                 val = value_dict.get("value")
                                 triples.append({
                                     "subject": "Found Entity",
                                     "predicate": var_name,
                                     "object": val.split("/")[-1] if "/" in val else val
                                 })
                                 
                                 # 2. Collect entities for Entity-Guided Chunk Retrieval
                                 if val and (val.startswith("http") or len(val) > 1):
                                     # Simple heuristic: if it's a URI or a meaningful string, treat as entity
                                     clean_val = val.split("/")[-1] if "/" in val else val
                                     if " " not in clean_val: # Only single word entities usually
                                         found_entities.add(clean_val)
                        
                        print(f"DEBUG: [Fuseki] Found {len(found_entities)} entities from graph for chunk retrieval: {found_entities}")

                        # 오프셋 정보 첨부
                        triples_with_offset, discovered_chunk_ids = await self._attach_offsets_to_triples(kb_id, triples)

                        return {
                            "chunk_ids": discovered_chunk_ids, # 오프셋에서 발견된 청크 ID
                            "sparql_query": sparql_query,
                            "triples": triples_with_offset,
                            "found_entities": list(found_entities) # Pass this back!
                        }
                    else:
                        print("DEBUG: [Fuseki] Generator query returned no results. Falling back to default logic.")
                        
            except Exception as e:
                print(f"WARNING: [Fuseki] Error during SPARQL generation/execution: {e}")
                # Fallback continues below

        # Fallback / Default Logic (Original regex-based search)
        
        if not entities:
            return {"chunk_ids": [], "sparql_query": "", "triples": []}

        # Escape entities for SPARQL regex
        # Replace '\ ' with ' ' because SPARQL regex doesn't support escaped spaces like Python does
        safe_entities = [re.escape(e).replace(r"\ ", " ") for e in entities]
        regex_pattern = "|".join(safe_entities)
        
        # Build relationship filter based on keywords
        relationship_filter = ""
        use_rel_filter = kwargs.get("use_relation_filter", True)
        
        if use_rel_filter and relationship_keywords:
            rel_patterns = []
            for kw in relationship_keywords:
                if kw == "master":
                    rel_patterns.extend(["master", "스승", "teacher", "mentor"])
                elif kw == "student":
                    rel_patterns.extend(["student", "제자", "학생", "disciple"])
                elif kw == "전수":
                    rel_patterns.extend(["전수", "teach", "learn", "inherit"])
            
            if rel_patterns:
                # specific handling for spaces in SPARQL regex
                rel_regex = "|".join([re.escape(p).replace(r"\ ", " ") for p in rel_patterns])
                relationship_filter = f'|| regex(str(?pred), "({rel_regex})", "i") || regex(?predLabel, "({rel_regex})", "i")'
        
        # Build entity filter clauses for SPARQL
        # For each entity, we want to check if it's in the label or in the URI
        entity_filters = []
        for entity in entities:
            if not entity: continue
            # Use CONTAINS which is often more reliable than REGEX for basic substring match
            entity_filters.append(f'CONTAINS(LCASE(STR(?sLabel)), LCASE("{entity}"))')
            entity_filters.append(f'CONTAINS(LCASE(STR(?oLabel)), LCASE("{entity}"))')
            entity_filters.append(f'CONTAINS(LCASE(STR(?s)), LCASE("{entity}"))')
            entity_filters.append(f'CONTAINS(LCASE(STR(?o)), LCASE("{entity}"))')
        
        filter_clause = " || ".join(entity_filters) if entity_filters else "1=1"

        # DEBUG: Print exact filter clause and entities
        print(f"DEBUG: [Fuseki] Search Entities: {entities}")
        print(f"DEBUG: [Fuseki] Filter Clause: {filter_clause}")

        # Enhanced SPARQL query - Search Default Graph (where Fallback data lives)
        sparql_query = f"""
        PREFIX rel: <{self.namespace_relation}>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX onto: <http://example.org/onto/>
        PREFIX ns1: <http://example.org/onto/rel/>
        PREFIX inst: <http://example.org/onto/inst/>
        
        SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel ?chunkUri
        WHERE {{
            # Search triples matching filters
            ?s ?p ?o .
            
            # Optional labels
            OPTIONAL {{ ?s rdfs:label ?sLabel }}
            OPTIONAL {{ ?o rdfs:label ?oLabel }}
            
            # Filter Logic
            FILTER (
                # Exclude internal types if needed, but keep it broad for now
                ?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> &&
                ({filter_clause})
            )
            
            # Try to find source chunks linked to Subject or Object via hasSource
            OPTIONAL {{ ?s <http://rag.local/relation/hasSource> ?chunkUri }}
            OPTIONAL {{ ?o <http://rag.local/relation/hasSource> ?chunkUri2 }}
        }}
        LIMIT 100
        """
        
        print(f"DEBUG: [Fuseki] SPARQL Query (Fallback):\n{sparql_query}")
        results = fuseki_client.query_sparql(kb_id, sparql_query)
        bindings = results.get("results", {}).get("bindings", [])
        
        if bindings:
             print(f"DEBUG: [Fuseki] Sample binding: {bindings[0]}")

        chunk_ids = []
        triples = []
        for binding in bindings:
            uri = binding.get("chunkUri", {}).get("value", "")
            
            # Handle different chunk URI formats
            if uri.startswith("http://rag.local/source/"):
                chunk_ids.append(uri.split("/")[-1])
            elif uri.startswith("urn:ragchunk:"):
                # Extract info from urn:ragchunk:DOC_ID:v1:INDEX
                # Example: urn:ragchunk:8e04471c-612b-4afb-a8fe-2e23c369378f:v1:0000
                parts = uri.replace("urn:ragchunk:", "").split(":")
                # print(f"DEBUG: [Fuseki] Found urn:ragchunk URI: {uri}, parts: {parts}")
                if len(parts) >= 3:
                    doc_id = parts[0]
                    try:
                        chunk_idx = int(parts[2])
                        cid = f"{doc_id}_{chunk_idx}"
                        chunk_ids.append(cid)
                        # print(f"DEBUG: [Fuseki] Mapped to chunk_id: {cid}")
                    except ValueError:
                        chunk_ids.append(doc_id)
                elif len(parts) > 0:
                    chunk_ids.append(parts[0])
            
            # Also extract triples from results
            s_uri = binding.get("s", {}).get("value", "")
            p_uri = binding.get("p", {}).get("value", "")
            o_val = binding.get("o", {}).get("value", "")
            s_label = binding.get("sLabel", {}).get("value", "")
            o_label = binding.get("oLabel", {}).get("value", "")
            
            # Skip metadata predicates (RDF schema, provenance, etc.)
            if any(noise in p_uri for noise in [
                "rdf-syntax-ns#",      # rdf:type 등
                "rdf-schema#",         # rdfs:label, rdfs:comment 등
                "prov#",               # provenance 정보
                "evidence/",           # 증거 메타데이터
                "owl#",                # OWL 온톨로지 메타데이터
                "hasSource",           # 소스 링크 (내부용)
            ]):
                continue
            
            s_display = s_label if s_label else (urllib.parse.unquote(s_uri.split("/")[-1]).replace("_", " ") if s_uri else "[Unknown URI]")
            o_display = o_label if o_label else (urllib.parse.unquote(o_val.split("/")[-1]).replace("_", " ") if o_val.startswith("http") else o_val) or "[Unknown Value]"

            p_display = urllib.parse.unquote(p_uri.split("/")[-1].replace("_", " "))
            
            if s_display and p_display and o_display:
                triples.append({
                    "subject": s_display,
                    "predicate": p_display,
                    "object": o_display
                })
        
        # Note: triples are already extracted in the main query loop above
        # Deduplicate triples
        seen = set()
        unique_triples = []
        for t in triples:
            key = (t["subject"], t["predicate"], t["object"])
            if key not in seen:
                seen.add(key)
                unique_triples.append(t)
        
        print(f"DEBUG: Found {len(chunk_ids)} chunk_ids and {len(unique_triples)} triples from graph (Fallback)")
        
        # 오프셋 정보 첨부
        triples_with_offset, discovered_chunk_ids = await self._attach_offsets_to_triples(kb_id, unique_triples)
        
        # 기존 chunk_ids와 오프셋에서 발견된 chunk_ids 합치기
        all_chunk_ids = list(set(chunk_ids) | set(discovered_chunk_ids))
                
        return {
            "chunk_ids": all_chunk_ids,
            "sparql_query": sparql_query.strip(),
            "triples": triples_with_offset
        }

    async def _attach_offsets_to_triples(self, kb_id: str, triples: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """SQLite에서 트리플의 소스 오프셋 정보 조회하여 첨부 (Neo4j 백엔드와 동일 로직)"""
        from app.models.triple_chunk_mapping import compute_triple_hash
        from app.core.database import SessionLocal
        from sqlalchemy.future import select
        from app.models.triple_chunk_mapping import TripleChunkMapping
        
        discovered_chunk_ids = set()
        
        try:
            async with SessionLocal() as db:
                for triple in triples:
                    triple_hash = compute_triple_hash(
                        triple.get("subject", ""),
                        triple.get("predicate", ""),
                        triple.get("object", "")
                    )
                    
                    result = await db.execute(
                        select(TripleChunkMapping)
                        .filter(TripleChunkMapping.kb_id == kb_id)
                        .filter(TripleChunkMapping.triple_hash == triple_hash)
                    )
                    mappings = result.scalars().all()
                    
                    if mappings:
                        # 오프셋은 첫 번째 매핑의 것 사용 (어차피 동일)
                        triple["source_start"] = mappings[0].source_start
                        triple["source_end"] = mappings[0].source_end
                        
                        # 관련된 청크 ID 수집
                        for m in mappings:
                            if m.chunk_id:
                                discovered_chunk_ids.add(m.chunk_id)
                    else:
                        # 매핑이 없으면 오프셋 없음
                        triple["source_start"] = None
                        triple["source_end"] = None
                        
        except Exception as e:
            logger.warning(f"Error attaching offsets to triples: {e}")
            # Continue without offsets
            for triple in triples:
                triple["source_start"] = None
                triple["source_end"] = None
        
        return triples, list(discovered_chunk_ids)
