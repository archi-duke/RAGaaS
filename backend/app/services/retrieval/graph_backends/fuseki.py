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
            from app.services.retrieval.sparql_generator import SPARQLGenerator
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
                enable_inverse = kwargs.get("enable_inverse_search", True)  # 기본 ON으로 변경
                
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
                        # Now also fetch sourceNodeId from Reification for direct chunk mapping.
                        
                        real_triples = []
                        discovered_chunk_ids = set()
                        
                        if found_uris:
                            # Construct a query to fetch triples involving these URIs + Reification sourceNodeId
                            print(f"[DEBUG FUSEKI] found_uris for secondary lookup: {found_uris}", flush=True)
                            
                            union_clauses = []
                            for uri in found_uris:
                                clause = f"""{{ BIND(<{uri}> AS ?target) . ?s ?p ?o . FILTER(?o = ?target) }}
                                UNION
                                {{ BIND(<{uri}> AS ?target) . ?s ?p ?o . FILTER(?s = ?target) }}"""
                                union_clauses.append(clause)
                            
                            union_body = " UNION ".join(union_clauses)
                            
                            # Step 1: Get triples
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
                            
                            # Step 2: Query Reification for sourceNodeId
                            # Find Statement nodes that match our triples
                            if real_triples:
                                reification_query = f"""
                                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                                PREFIX meta: <http://rag.local/meta/>
                                SELECT ?sourceNodeId
                                FROM <urn:x-arq:UnionGraph>
                                WHERE {{
                                  ?stmt rdf:type rdf:Statement ;
                                        meta:sourceNodeId ?sourceNodeId .
                                }}
                                LIMIT 100
                                """
                                
                                print(f"[DEBUG FUSEKI] Reification Query for sourceNodeId...", flush=True)
                                reif_results = fuseki_client.query_sparql(kb_id, reification_query)
                                reif_bindings = reif_results.get("results", {}).get("bindings", [])
                                
                                for rb in reif_bindings:
                                    if "sourceNodeId" in rb:
                                        node_id = rb["sourceNodeId"]["value"]
                                        if node_id:
                                            discovered_chunk_ids.add(node_id)
                                
                                log_trace(f"[Fuseki] Found {len(discovered_chunk_ids)} unique sourceNodeIds from Reification")

                        # Use real_triples if found, otherwise fall back to dummy triples (which will fail mapping but show entity)
                        final_triples = real_triples if real_triples else triples

                        return {
                            "chunk_ids": list(discovered_chunk_ids),  # Fuseki Reification에서 직접 추출
                            "sparql_query": generated_sparql.strip(),
                            "triples": final_triples,
                            "found_entities": list(found_entities),
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
        
        # [MODIFIED] Fallback Logic Removed
        # If we reached here, it means LLM failed or returned no results (and fallback is requested but we disabled regex fallback)
        
        log_trace("[Fuseki] Strict Mode: No fallback search performed.")
        return {
            "chunk_ids": [], 
            "sparql_query": sparql_query.strip() if sparql_query else "No Results / Generation Failed", 
            "triples": [], 
            "found_entities": [],
            "trace_logs": trace_logs
        }

