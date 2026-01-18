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
        trace_logs = []

        def log_trace(msg: str):
            trace_logs.append(msg)

        # 1. Try using SPARQLGenerator (LLM-based)
        if self.generator and query_text:
            try:
                # Determine inverse relation mode
                # Default: if not explicitly set, use 'auto'
                inv_mode = kwargs.get("inverse_extraction_mode", "auto")
                enable_inverse = kwargs.get("enable_inverse_search", False)  # 기본값 False로 변경
                
                # If user explicitly disabled inverse search, override mode
                if not enable_inverse:
                    inv_mode = "none"
                
                # [NEW] Fetch Schema Info from DB (Moved up)
                # Only fetch schema if use_schema_mode is True (default ON)
                use_schema_mode = kwargs.get("use_schema_mode", True)
                schema_info = None
                
                if use_schema_mode:
                    try:
                        from app.models.knowledge_base import KnowledgeBase
                        
                        kb = await KnowledgeBase.get(kb_id)
                        if kb and kb.is_promoted and kb.promotion_metadata:
                            schema_info = kb.promotion_metadata.get("schema_info")
                    except Exception as e_schema:
                        log_trace(f"[Fuseki] WARNING: Failed to fetch schema info: {e_schema}")
                else:
                    # Schema Mode OFF
                    pass

                # [NEW] Determine Prompt Source Priority
                # 1. Pipeline Parameter (kwargs['sparql_prompt_template']) - Highest Priority
                # 2. Knowledge Base Field (kb.sparql_prompt_template) - Default/Fallback
                
                pipeline_prompt = kwargs.get("sparql_prompt_template")
                
                # Retrieve custom_prompt (previously missed in refactor)
                custom_prompt = kwargs.get("custom_query_prompt") or ""
                
                mongo_prompt_content = None
                
                if pipeline_prompt:
                    mongo_prompt_content = pipeline_prompt
                    log_trace(f"[Fuseki] Using Prompt from Pipeline Parameters: {len(mongo_prompt_content)} chars")
                else:
                    # Fallback to KB field
                    try:
                        from app.models.knowledge_base import KnowledgeBase
                        kb = await KnowledgeBase.get(kb_id)
                        
                        if kb and kb.sparql_prompt_template:
                            mongo_prompt_content = kb.sparql_prompt_template
                            log_trace(f"[Fuseki] Using Prompt from KnowledgeBase Field: {len(mongo_prompt_content)} chars")
                        else:
                            # Final Fallback to global? (Optional, maybe safer to stick to library default if nothing provided)
                            from app.models.prompt import PromptTemplate
                            db_prompt = await PromptTemplate.find_one(PromptTemplate.name == "sparql_generation_prompt")
                            if db_prompt:
                                mongo_prompt_content = db_prompt.content
                                log_trace(f"[Fuseki] Using Prompt from Global Collection (Fallback)")
    
                    except Exception as e_prompt:
                        log_trace(f"[Fuseki] WARNING: Failed to fetch prompt: {e_prompt}")

                gen_result = self.generator.generate(
                    question=query_text,
                    context=f"Entities: {', '.join(entities)}",
                    mode="ontology",
                    inverse_relation=inv_mode,
                    custom_prompt=custom_prompt,
                    schema_info=schema_info,
                    system_prompt_override=mongo_prompt_content
                )
                
                generated_sparql = gen_result.get("sparql")
                if generated_sparql:
                    # Prepend schema usage comment for Debug Log
                    if schema_info:
                         generated_sparql = f"# [Used Promoted Ontology Schema]\n{generated_sparql}"

                    log_trace(f"[Fuseki] Generated SPARQL:\n{generated_sparql}")
                    
                    # Remove any existing PREFIX declarations from LLM-generated query
                    # to avoid conflicts with our correct prefixes
                    sparql_body = re.sub(r'PREFIX\s+\w+:\s*<[^>]+>\s*', '', generated_sparql, flags=re.IGNORECASE)
                    sparql_body = sparql_body.strip()
                    
                    # Ensure standard prefixes with correct namespaces
                    # FIX: Must match Doc2Onto's default namespaces (example.org)
                    prefixes = """
                    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    PREFIX owl: <http://www.w3.org/2002/07/owl#>
                    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    PREFIX inst: <http://rag.local/inst/> 
                    PREFIX rel: <http://rag.local/rel/> 
                    PREFIX prop: <http://rag.local/prop/>
                    PREFIX class: <http://rag.local/class/>
                    """
                    
                    
                    # Inject FROM <urn:x-arq:UnionGraph> to search across all named graphs
                    # This is crucial because Doc2Onto loads data (base.trig) into named graphs
                    if re.search(r'WHERE', sparql_body, re.IGNORECASE):
                        # Simple injection: replace the first 'WHERE' with 'FROM <urn:x-arq:UnionGraph> WHERE'
                        print("[DEBUG FUSEKI] Injecting UnionGraph...", flush=True)
                        sparql_query_content = re.sub(r'WHERE', "FROM <urn:x-arq:UnionGraph>\nWHERE", sparql_body, count=1, flags=re.IGNORECASE)
                    else:
                        print("[DEBUG FUSEKI] WHERE clause NOT found in query!", flush=True)
                        sparql_query_content = sparql_body

                    full_query = prefixes + sparql_query_content
                    
                    print(f"[DEBUG FUSEKI] Final Query:\n{full_query}", flush=True)
                    log_trace(f"[Fuseki] Executing SPARQL:\n{full_query}")
                    
                    # Execute
                    results = fuseki_client.query_sparql(kb_id, full_query)
                    bindings = results.get("results", {}).get("bindings", [])
                    
                    print(f"[DEBUG FUSEKI] Results count: {len(bindings)}", flush=True)
                    if bindings:
                         sparql_query = full_query
                         
                    if bindings:
                        # Process results from generator query
                        found_entities = set()
                        found_uris = set() # Keep track of URIs for secondary lookup
                        
                        for binding in bindings:
                             for var_name, value_dict in binding.items():
                                 val = value_dict.get("value")
                                 
                                 # Collect meaningful entities
                                 if val and (val.startswith("http") or len(val) > 1):
                                     clean_val = val.split("/")[-1] if "/" in val else val
                                     if " " not in clean_val:
                                         found_entities.add(clean_val)
                                     
                                     if val.startswith("http"):
                                         found_uris.add(val)

                        log_trace(f"[Fuseki] Found {len(found_entities)} entities from graph: {list(found_entities)[:5]}...")
                        
                        # [CRITICAL FIX] Perform Secondary Lookup to find REAL triples for these entities
                        # The LLM generated query (e.g. SELECT ?label) does not return the S-P-O structure we need for mapping.
                        # We must query the graph again to find triples connecting these found entities.
                        
                        real_triples = []
                        if found_uris:
                            # Construct a query to fetch triples involving these URIs
                            # We limit to finding relations between these entities or involving them
                            
                            print(f"[DEBUG FUSEKI] found_uris for secondary lookup: {found_uris}", flush=True)
                            # Fuseki에서 VALUES + FILTER 조합이 동작하지 않음
                            # 각 URI에 대해 간단한 쿼리를 UNION으로 결합
                            union_clauses = []
                            for uri in found_uris:
                                clause = f"""{{ BIND(<{uri}> AS ?target) . ?s ?p ?o . FILTER(?o = ?target) }}
                                UNION
                                {{ BIND(<{uri}> AS ?target) . ?s ?p ?o . FILTER(?s = ?target) }}"""
                                union_clauses.append(clause)
                            
                            union_body = " UNION ".join(union_clauses)
                            
                            secondary_query = f"""
                            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                            SELECT DISTINCT ?s ?p ?o
                            FROM <urn:x-arq:UnionGraph>
                            WHERE {{
                              {union_body}
                              FILTER(?p != rdf:type)
                              FILTER(?p != rdfs:label)
                              FILTER(?p != rdfs:comment)
                              FILTER(?p != rdf:subject)
                              FILTER(?p != rdf:object)
                              FILTER(?p != rdf:predicate)
                            }}
                            LIMIT 100
                            """


                            
                            print(f"[DEBUG FUSEKI] Secondary Query:\n{secondary_query}", flush=True)
                            log_trace(f"[Fuseki] Executing Secondary Lookup for Real Triples...")
                            sec_results = fuseki_client.query_sparql(kb_id, secondary_query)
                            sec_bindings = sec_results.get("results", {}).get("bindings", [])
                            print(f"[DEBUG FUSEKI] Secondary bindings count: {len(sec_bindings)}", flush=True)
                            if sec_bindings:
                                print(f"[DEBUG FUSEKI] First binding: {sec_bindings[0]}", flush=True)

                            
                            for b in sec_bindings:
                                s = b["s"]["value"].split("/")[-1]
                                p = b["p"]["value"].split("/")[-1]
                                o = b["o"]["value"].split("/")[-1]
                                real_triples.append({
                                    "subject": s,
                                    "predicate": p,
                                    "object": o
                                })
                            
                            log_trace(f"[Fuseki] Secondary lookup retrieved {len(real_triples)} real triples.")

                        # Use real_triples if found, otherwise fall back to dummy triples (which will fail mapping but show entity)
                        final_triples = real_triples if real_triples else triples

                        # 오프셋 정보 첨부
                        triples_with_offset, discovered_chunk_ids = await self._attach_offsets_to_triples(kb_id, final_triples)

                        return {
                            "chunk_ids": discovered_chunk_ids, # 오프셋에서 발견된 청크 ID
                            "sparql_query": generated_sparql.strip(),
                            "triples": triples_with_offset,
                            "found_entities": list(found_entities), # Pass this back!
                            "trace_logs": trace_logs
                        }
                    else:
                        # If inverse search is disabled and LLM query returned no results,
                        # don't fall back to generic search - return empty results
                        # UNLESS it is a promoted KB (schema_info exists), then we want fallback to capture anything.
                        if inv_mode == "none" and not schema_info:
                            return {
                                "chunk_ids": [],
                                "sparql_query": generated_sparql.strip(),
                                "triples": [],
                                "found_entities": [],
                                "trace_logs": trace_logs
                            }
                        
            except Exception as e:
                log_trace(f"[Fuseki] Error during SPARQL generation/execution: {e}")
                # Fallback continues below

        # Fallback / Default Logic (Original regex-based search)
        
        if not entities:
            return {"chunk_ids": [], "sparql_query": "", "triples": [], "trace_logs": trace_logs}

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

        # Enhanced SPARQL query - Search Default Graph (where Fallback data lives)
        sparql_query = f"""
        PREFIX inst: <http://rag.local/inst/>
        PREFIX rel: <http://rag.local/rel/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX class: <http://rag.local/class/>
        PREFIX prop: <http://rag.local/prop/>
        
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
        
        results = fuseki_client.query_sparql(kb_id, sparql_query)
        bindings = results.get("results", {}).get("bindings", [])

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
        
        
        # 오프셋 정보 첨부
        triples_with_offset, discovered_chunk_ids = await self._attach_offsets_to_triples(kb_id, unique_triples)
        
        # 기존 chunk_ids와 오프셋에서 발견된 chunk_ids 합치기
        all_chunk_ids = list(set(chunk_ids) | set(discovered_chunk_ids))
                
        return {
            "chunk_ids": all_chunk_ids,
            "sparql_query": sparql_query.strip(),
            "triples": triples_with_offset,
            "trace_logs": trace_logs
        }

    async def _attach_offsets_to_triples(self, kb_id: str, triples: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """MongoDB(Beanie)에서 트리플의 소스 오프셋 정보 조회하여 첨부"""
        from app.models.triple_chunk_mapping import TripleChunkMapping, compute_triple_hash
        
        discovered_chunk_ids = set()
        
        try:
            for triple in triples:
                triple_hash = compute_triple_hash(
                    triple.get("subject", ""),
                    triple.get("predicate", ""),
                    triple.get("object", "")
                )
                
                # Beanie Query
                mappings = await TripleChunkMapping.find(
                    TripleChunkMapping.kb_id == kb_id,
                    TripleChunkMapping.triple_hash == triple_hash
                ).to_list()
                
                if mappings:
                    # 오프셋은 첫 번째 매핑의 것 사용 (어차피 동일)
                    triple["source_start"] = mappings[0].source_start
                    triple["source_end"] = mappings[0].source_end
                    
                    # 관련된 청크 ID 수집
                    for m in mappings:
                        if m.chunk_id:
                            discovered_chunk_ids.add(m.chunk_id)
                else:
                    triple["source_start"] = None
                    triple["source_end"] = None
                        
        except Exception as e:
            logger.warning(f"Error attaching offsets to triples: {e}")
            import traceback
            traceback.print_exc()
            # Continue without offsets
            for triple in triples:
                triple.setdefault("source_start", None)
                triple.setdefault("source_end", None)
        
        return triples, list(discovered_chunk_ids)
