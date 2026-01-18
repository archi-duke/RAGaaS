from typing import List, Dict, Any, Optional
import logging
import os
import shutil
import uuid
import json
from pathlib import Path
from app.core.config import settings
from app.core.milvus import connect_milvus, create_collection
from app.services.embedding import embedding_service
from pymilvus import Collection
import asyncio
from functools import partial

logger = logging.getLogger(__name__)

class Doc2OntoProcessor:
    """
    Wrapper for the Doc2Onto pipeline.
    This class interfaces with the Doc2Onto logic to extract graph elements
    and load them into Fuseki or Neo4j (based on graph_backend) and Milvus (Vectors).
    """
    def __init__(self):
        self.client = None
        self.enabled = False
        
        if hasattr(settings, 'DOC2ONTO_CONFIG_PATH') and settings.DOC2ONTO_CONFIG_PATH and os.path.exists(settings.DOC2ONTO_CONFIG_PATH):
            try:
                # Add app directory to sys.path to allow 'import doc2onto'
                import sys
                app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                if app_dir not in sys.path:
                    sys.path.append(app_dir)

                from doc2onto.api import Doc2OntoClient
                self.client = Doc2OntoClient(config_path=settings.DOC2ONTO_CONFIG_PATH)
                
                # MONKEY MATCH: Force usage of OpenAIExtractor if config specifies gpt models
                # The library v0.1.0 defaults to Stub, so we must swap it manually.
                try:
                    from doc2onto.extractors.openai_extractor import OpenAIExtractor
                    config = self.client.config.extraction
                    if "gpt" in config.llm_model.lower():
                        print(f"[Doc2Onto] Swapping Extractor to OpenAIExtractor (Model: {config.llm_model})")
                        real_extractor = OpenAIExtractor(
                             confidence_threshold=config.confidence_threshold,
                             llm_endpoint=config.llm_endpoint,
                             llm_model=config.llm_model,
                             api_key=settings.OPENAI_API_KEY,
                             examples_path=config.examples_path
                        )
                        self.client._extractor = real_extractor
                except Exception as ex:
                    print(f"[Doc2Onto] Failed to swap extractor: {ex}")

                self.enabled = True
                print(f"[Doc2Onto] Initialized with config: {settings.DOC2ONTO_CONFIG_PATH}")
            except ImportError:
                print("[Doc2Onto] Library not found. Integration disabled.")
            except Exception as e:
                print(f"[Doc2Onto] Failed to initialize: {e}")
        else:
            print("[Doc2Onto] DOC2ONTO_CONFIG_PATH not set or file not found. Integration disabled.")

    async def process_document_full(
        self, 
        file_path: str, 
        kb_id: str, 
        doc_id: str,
        graph_backend: str = "ontology",
        chunking_strategy: str = "size",
        external_chunks_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process document using the full Doc2Onto pipeline.
        """
        if not self.enabled or not self.client:
            print(f"[Doc2Onto] Disabled. Skipping document {doc_id}")
            return {"status": "skipped", "reason": "disabled"}

        run_id = str(uuid.uuid4())[:8]
        output_dir = os.path.join(os.getcwd(), "doc2onto_out", kb_id, doc_id)
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            temp_input_dir = os.path.join(output_dir, "input")
            os.makedirs(temp_input_dir, exist_ok=True)
            
            dest_path = os.path.join(temp_input_dir, os.path.basename(file_path))
            shutil.copy2(file_path, dest_path)
            
            print(f"[Doc2Onto] Starting pipeline for {doc_id} (backend={graph_backend}, run_id={run_id})...")
            
            # Apply runtime config overrides
            if config and self.client and hasattr(self.client, '_extractor'):
                extractor = self.client._extractor
                
                # Check for OpenAIExtractor-specific attributes
                if hasattr(extractor, 'confidence_threshold'):
                     new_conf = float(config.get("confidence_threshold", 0.6))
                     extractor.confidence_threshold = new_conf
                     print(f"[Doc2Onto] Overriding confidence_threshold to {new_conf}")
                     
                if hasattr(extractor, 'max_candidates'): # Some extractors might use this
                     new_max = int(config.get("max_candidates_per_chunk", 20))
                     setattr(extractor, 'max_candidates', new_max) 
                     print(f"[Doc2Onto] Overriding max_candidates to {new_max}")
                     
                # Update extraction params if available in config object
                if hasattr(self.client.config, 'extraction'):
                    self.client.config.extraction.confidence_threshold = float(config.get("confidence_threshold", 0.6))
            
            # Note: Doc2Onto build might need configuration for chunking strategy if supported
            # RAGaaS Fix: Run build in executor to avoid blocking the asyncio loop
            loop = asyncio.get_running_loop()
            
            build_func = partial(
                self.client.build,
                input_dir=temp_input_dir,
                output_dir=output_dir,
                run_id=run_id,
                external_chunks=external_chunks_path
            )
            
            result = await loop.run_in_executor(None, build_func)
            print(f"[Doc2Onto] Pipeline completed. Stats: {result}")
            
            if graph_backend == "neo4j":
                await self._load_to_neo4j(output_dir, kb_id, doc_id)
                # RAGaaS: Create Entity-Chunk connections
                await self._link_entities_to_chunks_neo4j(output_dir, kb_id, doc_id)
            else:
                await self._load_to_fuseki(output_dir, kb_id)
                # RAGaaS: Create Entity-Chunk connections for Fuseki as well
                await self._link_entities_to_chunks_fuseki(output_dir, kb_id, doc_id)
            
            # RAGaaS: Always save triple-chunk mappings to MongoDB for retrieval mapping
            await self._save_triple_mappings(output_dir, kb_id, doc_id)
            
            # Note: Milvus loading in Doc2Onto is redundant when using RAGaaS hybrid approach.
            # Chunks are already indexed by RAGaaS before calling Doc2Onto.
            # chunks_path = os.path.join(output_dir, "chunks.jsonl")
            # if os.path.exists(chunks_path):
            #     await self._load_chunks_to_milvus_adapter(chunks_path, kb_id, doc_id)
                
            return {"status": "success", "result": result}

        except Exception as e:
            print(f"[Doc2Onto] Error processing document {doc_id}: {e}")
            raise e
        finally:
            if os.path.exists(output_dir):
                # shutil.rmtree(output_dir, ignore_errors=True)
                pass

    def normalize_entity_name(self, name: str) -> str:
        """
        Normalize entity name for Fuseki URI.
        Removes common prefixes like '001번', '참가자' and special chars.
        Returns the normalized name.
        """
        import re
        # 1. Remove common prefixes/suffixes (Customize as needed)
        # remove '001번 ', '101번 ' etc. (digit + 번)
        name = re.sub(r'^\d+번\s*', '', name)
        # remove '참가자 '
        name = re.sub(r'^참가자\s*', '', name)
        
        # 2. Basic cleanup (same as _sanitize_uri logic usually)
        # but here we want to keep Korean chars valid for URI generation later
        return name.strip()

    async def _load_to_fuseki(self, output_dir: str, kb_id: str):
        """Load TriG files to Fuseki using RAGaaS's fuseki_client with Normalization."""
        from app.core.fuseki import fuseki_client
        import requests
        from requests.auth import HTTPBasicAuth
        import re
        
        print(f"[Doc2Onto] Entering _load_to_fuseki with output_dir: {output_dir}", flush=True)
        
        base_trig = os.path.join(output_dir, "base.trig")
        evidence_trig = os.path.join(output_dir, "evidence.trig")
        
        print(f"[Doc2Onto] Checking for output files:", flush=True)
        if os.path.exists(output_dir):
             print(f"[Doc2Onto] Output Dir Exists. Contents: {os.listdir(output_dir)}", flush=True)
        else:
             print(f"[Doc2Onto] Output dir {output_dir} does NOT exist! Current CWD: {os.getcwd()}", flush=True)
        
        # Use RAGaaS naming convention (kb_ prefix)
        safe_name = f"kb_{kb_id.replace('-', '_')}"
        
        # Ensure dataset exists
        fuseki_client.create_dataset(kb_id)
        
        # Upload using GSP with auth
        gsp_url = f"{settings.FUSEKI_URL}/{safe_name}/data"
        auth = HTTPBasicAuth("admin", "admin")
        
        print(f"[Doc2Onto] Uploading to Fuseki dataset: {safe_name} via {gsp_url}", flush=True)
        
        for trig_path in [base_trig, evidence_trig]:
            if os.path.exists(trig_path):
                try:
                    # Check file size
                    print(f"[Doc2Onto] Found {os.path.basename(trig_path)} ({os.path.getsize(trig_path)} bytes)", flush=True)
                    
                    with open(trig_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    if not content.strip():
                        print(f"[Doc2Onto] SKIPPING {os.path.basename(trig_path)}: File is empty.", flush=True)
                        continue

                    # --- NORMALIZATION LOGIC ---
                    if os.path.basename(trig_path) == "base.trig":
                        print("[Doc2Onto] Applying Entity Normalization to base.trig...", flush=True)
                        normalized_lines = []
                        
                        # Regex to capture ANY http URI ending with a name
                        # We force standard prefix: <http://rag.local/entity/>
                        # Pattern captures: 1) The whole match (implicit) 2) The local name (last part)
                        # We ignore the original prefix and force our own.
                        uri_pattern = re.compile(r'<(http://[^>]+/[^>/]+)>')
                        
                        # Track aliases to add: {normalized_uri: {set of aliases}}
                        aliases_to_add = {}

                        standard_prefix = "http://rag.local/entity/"

                        lines = content.split('\n')
                        for line in lines:
                            # Function to replace and track
                            def replace_and_track(match):
                                original_uri = match.group(1)
                                # Extract local name (after last / or #)
                                if '#' in original_uri:
                                    original_local = original_uri.split('#')[-1]
                                else:
                                    original_local = original_uri.split('/')[-1]
                                
                                # Skip if it looks like a standard schema term (rdf, rdfs, owl, etc.)
                                # simple heuristic: if prefix is w3.org, skip
                                if "w3.org" in original_uri:
                                    return match.group(0)

                                import urllib.parse
                                decoded_name = urllib.parse.unquote(original_local)
                                
                                normalized_name = self.normalize_entity_name(decoded_name)
                                
                                # Force new URI
                                new_uri = f"{standard_prefix}{normalized_name}"
                                
                                # Add alias to 'aliases_to_add' if name was changed
                                if normalized_name != decoded_name:
                                    if new_uri not in aliases_to_add:
                                        aliases_to_add[new_uri] = set()
                                    aliases_to_add[new_uri].add(decoded_name)
                                
                                return f"<{new_uri}>"

                            new_line = uri_pattern.sub(replace_and_track, line)
                            normalized_lines.append(new_line)
                        
                        # Add Aliases (skos:altLabel)
                        if aliases_to_add:
                            print(f"[Doc2Onto] Adding {len(aliases_to_add)} normalized entities with aliases.", flush=True)
                            
                            content = '\n'.join(normalized_lines)
                        
                        # Upload normalized content
                        print(f"[Doc2Onto] Sending Request to {gsp_url}...", flush=True)
                        try:
                            response = requests.post(
                                gsp_url,
                                data=content.encode("utf-8"),
                                headers={"Content-Type": "application/trig"},
                                auth=auth,
                                timeout=60
                            )
                        except Exception as req_err:
                            print(f"[Doc2Onto] REQUEST FAILED: {req_err}", flush=True)
                            import traceback
                            traceback.print_exc()
                            continue
                        
                        if response.status_code in [200, 201, 204]:
                            print(f"[Doc2Onto] SUCCESS: Uploaded normalized base.trig", flush=True)
                            
                            # Insert Aliases via SPARQL Update
                            if aliases_to_add:
                                print(f"[Doc2Onto] Inserting aliases for normalized entities...", flush=True)
                                update_query = "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nINSERT DATA { GRAPH <urn:onto:base> {\n"
                                for uri, alias_set in aliases_to_add.items():
                                    for alias in alias_set:
                                        # Escape alias
                                        safe_alias = alias.replace('"', '\\"')
                                        update_query += f"  <{uri}> skos:altLabel \"{safe_alias}\" .\n"
                                update_query += "} }"
                                
                                update_endpoint = f"{settings.FUSEKI_URL}/{safe_name}/update"
                                try:
                                    requests.post(update_endpoint, data={"update": update_query}, auth=auth, timeout=30)
                                    print("[Doc2Onto] Aliases inserted successfully.", flush=True)
                                except Exception as e:
                                    print(f"[Doc2Onto] Failed to insert aliases: {e}", flush=True)
                                    
                        else:
                            print(f"[Doc2Onto] ERROR: Failed to upload normalized base.trig: {response.status_code} {response.text}", flush=True)

                    else:
                        # EVIDENCE TRIG (Usually metadata, no normalization needed or safer not to touch)
                        print(f"[Doc2Onto] Uploading evidence.trig to {gsp_url}...", flush=True)
                        try:
                            response = requests.post(
                                gsp_url,
                                data=content.encode("utf-8"),
                                headers={"Content-Type": "application/trig"},
                                auth=auth,
                                timeout=60
                            )
                        except Exception as req_err:
                            print(f"[Doc2Onto] REQUEST FAILED (Evidence): {req_err}", flush=True)
                            continue

                        if response.status_code in [200, 201, 204]:
                            print(f"[Doc2Onto] SUCCESS: Uploaded {os.path.basename(trig_path)}", flush=True)
                        else:
                            print(f"[Doc2Onto] ERROR: Failed to upload {os.path.basename(trig_path)}: {response.status_code}", flush=True)

                except Exception as e:
                    print(f"[Doc2Onto] EXCEPTION uploading {trig_path}: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
            else:
                print(f"[Doc2Onto] MISSING: {trig_path} not found.")

    async def _load_to_neo4j(self, output_dir: str, kb_id: str, doc_id: str):
        """
        Load extracted triples to Neo4j.
        Falling back to legacy/direct loading since CLI might have path issues in Docker.
        """
        print(f"[Doc2Onto] Loading to Neo4j (using direct adapter)...")
        await self._load_to_neo4j_legacy(output_dir, kb_id, doc_id)

    async def _link_entities_to_chunks_neo4j(self, output_dir: str, kb_id: str, doc_id: str):
        """Create Entity-Chunk connections in Neo4j (RAGaaS responsibility).
        
        Doc2Onto stores entities and triples, but RAGaaS needs to link them
        to chunks for retrieval purposes.
        """
        from app.core.neo4j_client import neo4j_client
        
        candidates_path = os.path.join(output_dir, "candidates_filtered.jsonl")
        if not os.path.exists(candidates_path):
            print(f"[RAGaaS] No candidates file for entity-chunk linking")
            return
        
        print(f"[RAGaaS] Creating Entity-Chunk connections (Neo4j)...")
        
        # Collect entities and their source chunks
        entity_chunks = {}  # entity_name -> set of chunk_ids
        
        with open(candidates_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[RAGaaS] JSON parse error in candidates file line: {e}")
                    continue
                
                # Extract entities from triples
                for triple in record.get("triples", []):
                    source_chunk_id = triple.get("source_chunk_id", "")
                    
                    # Extract chunk index from source_chunk_id
                    if isinstance(source_chunk_id, str) and '|' in source_chunk_id:
                        try:
                            chunk_idx = int(source_chunk_id.split('|')[-1])
                        except ValueError:
                            chunk_idx = 0
                    else:
                        chunk_idx = source_chunk_id if isinstance(source_chunk_id, int) else 0
                    
                    # Milvus-compatible chunk_id
                    chunk_id = f"{doc_id}_{chunk_idx}"
                    
                    # Track subject and object entities
                    for entity in [triple.get("subject", ""), triple.get("object", "")]:
                        if entity:
                            if entity not in entity_chunks:
                                entity_chunks[entity] = set()
                            entity_chunks[entity].add(chunk_id)
        
        print(f"[RAGaaS] Found {len(entity_chunks)} entities to link to chunks")
        
        # Create Chunk nodes and MENTIONED_IN relationships
        count = 0
        for entity_name, chunk_ids in entity_chunks.items():
            for chunk_id in chunk_ids:
                # Create Chunk node and MENTIONED_IN relationship
                # Match entity by multiple possible name properties
                # We remove the label constraint (e:Entity) to be safe, 
                # as Doc2Onto might assign specific class labels.
                cypher = """
                MERGE (c:Chunk {id: $chunk_id})
                ON CREATE SET c.kb_id = $kb_id
                WITH c
                MATCH (e)
                WHERE e.kb_id = $kb_id AND (
                      e.label_ko = $entity_name 
                   OR e.label_ko = $entity_name_underscore
                   OR e.name = $entity_name
                   OR e.label = $entity_name
                )
                MERGE (e)-[:MENTIONED_IN]->(c)
                """
                
                # Doc2Onto uses underscores in some cases
                entity_name_underscore = entity_name.replace(" ", "_")
                
                params = {
                    "chunk_id": chunk_id,
                    "kb_id": kb_id,
                    "entity_name": entity_name,
                    "entity_name_underscore": entity_name_underscore
                }
                
                try:
                    # Note: Without a label scan, this might be slow if there are many nodes.
                    # Ideally we should know the Label used by Doc2Onto (usually 'Entity' or 'OwlThing')
                    # Adding a hint or fallback if specific label is known would be good.
                    neo4j_client.execute_query(cypher, parameters=params)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to link entity '{entity_name}' to chunk: {e}")
        
        print(f"[RAGaaS] Created {count} Entity-Chunk connections in Neo4j")

    async def _link_entities_to_chunks_fuseki(self, output_dir: str, kb_id: str, doc_id: str):
        """Create Entity-Chunk connections in Fuseki."""
        from app.core.fuseki import fuseki_client
        
        candidates_path = os.path.join(output_dir, "candidates_filtered.jsonl")
        if not os.path.exists(candidates_path):
            return

        print(f"[RAGaaS] Creating Entity-Chunk connections (Fuseki)...")
        
        entity_chunks = {}
        with open(candidates_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                record = json.loads(line)
                for triple in record.get("triples", []):
                    source_chunk_id = triple.get("source_chunk_id", "")
                    if isinstance(source_chunk_id, str) and '|' in source_chunk_id:
                        try:
                            chunk_idx = int(source_chunk_id.split('|')[-1])
                        except:
                            chunk_idx = 0
                    else:
                        chunk_idx = source_chunk_id if isinstance(source_chunk_id, int) else 0
                    
                    chunk_id = f"{doc_id}_{chunk_idx}"
                    
                    for entity in [triple.get("subject", ""), triple.get("object", "")]:
                        if entity:
                            if entity not in entity_chunks:
                                entity_chunks[entity] = set()
                            entity_chunks[entity].add(chunk_id)
                            
        # For Fuseki, we use SPARQL Update to insert triples
        # linking the Entity URI (found by label) to the Chunk ID literal.
        # Predicate: <http://ragaas.com/schema/mentionedIn>
        
        count = 0
        for entity_name, chunk_ids in entity_chunks.items():
            for chunk_id in chunk_ids:
                # We try to find the subject ?s that has this label (ko or plain)
                sparql_update = """
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                PREFIX ragaas: <http://ragaas.com/schema/>
                
                INSERT {
                    ?s ragaas:mentionedIn ?chunk_id .
                }
                WHERE {
                    ?s rdfs:label ?label .
                    FILTER(STR(?label) = ?entity_name || STR(?label) = ?entity_name_und)
                }
                """
                
                # Replace placeholders manually as fuseki_client might not support params in update
                # Making sure to escape strings safely
                safe_name = entity_name.replace('"', '\\"')
                safe_name_und = entity_name.replace(" ", "_").replace('"', '\\"')
                
                query = sparql_update.replace("?chunk_id", f'"{chunk_id}"') \
                                     .replace("?entity_name", f'"{safe_name}"') \
                                     .replace("?entity_name_und", f'"{safe_name_und}"')
                
                try:
                    # fuseki_client.execute_sparql usually does SELECT, need UPDATE support
                    # If execute_sparql supports update, good. If not, we might need direct requests.
                    # Assuming fuseki_client has update capability or we use requests (safe choice)
                    import requests
                    from requests.auth import HTTPBasicAuth
                    
                    safe_ds_name = f"kb_{kb_id.replace('-', '_')}"
                    update_url = f"{settings.FUSEKI_URL}/{safe_ds_name}/update"
                    
                    requests.post(
                        update_url, 
                        data={"update": query},
                        auth=HTTPBasicAuth("admin", "admin"),
                        timeout=10
                    )
                    count += 1
                except Exception as e:
                    print(f"Failed to link entity '{entity_name}' in Fuseki: {e}")
                    
        print(f"[RAGaaS] Created {count} Entity-Chunk connections in Fuseki")

    async def _load_to_neo4j_legacy(self, output_dir: str, kb_id: str, doc_id: str):
        """Neo4j loading using APOC for dynamic relationship types."""
        from app.core.neo4j_client import neo4j_client
        
        candidates_path = os.path.join(output_dir, "candidates_filtered.jsonl")
        if not os.path.exists(candidates_path):
            print(f"[Doc2Onto] No candidates file found")
            return
        
        if not neo4j_client.verify_connectivity():
            print(f"[Doc2Onto] Neo4j connection failed. Check credentials.")
            return
        
        print(f"[Doc2Onto] Loading triples to Neo4j with dynamic relation types...")
        
        triples = []
        with open(candidates_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    # 각 레코드의 triples 배열에서 트리플 추출
                    for triple in record.get("triples", []):
                        if not triple.get("subject") or not triple.get("object"):
                            continue
                        if triple["subject"] == "Unknown" or triple["object"] == "Unknown":
                            continue
                            
                        triples.append({
                            "subject": triple.get("subject", ""),
                            "predicate": triple.get("predicate", ""),
                            "object": triple.get("object", ""),
                            "confidence": triple.get("confidence", 1.0),
                            "source_chunk_id": triple.get("source_chunk_id", "")
                        })
                except json.JSONDecodeError as e:
                    print(f"[Doc2Onto] JSON parse error in candidates file line: {e}")
                    continue
        
        print(f"[Doc2Onto] Raw triples from candidates: {len(triples)}")
        
        # 후처리 적용
        from app.services.ingestion.graph_postprocessor import post_process_triples, add_inverse_relations
        
        filtered_triples = post_process_triples(
            triples,
            confidence_threshold=0.6,
            normalize=True
        )
        print(f"[Doc2Onto] After filtering: {len(filtered_triples)}")
        
        final_triples = add_inverse_relations(filtered_triples)
        print(f"[Doc2Onto] With inverse relations: {len(final_triples)}")

        
        count = 0
        for triple in final_triples:
            source_chunk_id = triple['source_chunk_id']  # e.g., "debug_squid_game|v1|0000"
            
            # Extract chunk index from source_chunk_id
            # Format: "doc_name|version|chunk_idx" -> extract last part as int
            if isinstance(source_chunk_id, str) and '|' in source_chunk_id:
                try:
                    chunk_idx = int(source_chunk_id.split('|')[-1])
                except ValueError:
                    chunk_idx = 0
            else:
                chunk_idx = source_chunk_id if isinstance(source_chunk_id, int) else 0
            
            # Match Milvus chunk_id format: {doc_id}_{chunk_idx}
            chunk_id = f"{doc_id}_{chunk_idx}"
            
            # Use APOC to create dynamic relationship type
            # This allows relation types like "제자", "스승" instead of fixed "RELATION"
            cypher = """
            MERGE (s:Entity {name: $subj})
            ON CREATE SET s.kb_id = $kb_id
            MERGE (o:Entity {name: $obj})
            ON CREATE SET o.kb_id = $kb_id
            WITH s, o
            CALL apoc.create.relationship(s, $pred, {}, o) YIELD rel
            WITH s, o
            MERGE (c:Chunk {id: $chunk_id})
            ON CREATE SET c.kb_id = $kb_id
            MERGE (s)-[:MENTIONED_IN]->(c)
            MERGE (o)-[:MENTIONED_IN]->(c)
            """
            
            params = {
                "subj": triple["subject"],
                "obj": triple["object"],
                "pred": triple["predicate"],
                "chunk_id": chunk_id,
                "kb_id": kb_id
            }
            
            try:
                neo4j_client.execute_query(cypher, parameters=params)
                count += 1
            except Exception as e:
                print(f"[Doc2Onto] Failed to insert triple: {e}")

        print(f"[Doc2Onto] Inserted {count} triples to Neo4j")

    async def _save_triple_mappings(self, output_dir: str, kb_id: str, doc_id: str):
        """Save triple-chunk mappings from candidates file to MongoDB for retrieval."""
        print(f"[Doc2Onto] _save_triple_mappings called: output_dir={output_dir}, kb_id={kb_id}, doc_id={doc_id}")
        
        try:
            from app.models.triple_chunk_mapping import TripleChunkMapping, compute_triple_hash
            from pymilvus import Collection
            from app.core.milvus import connect_milvus
        except Exception as e:
            print(f"[Doc2Onto] ERROR importing dependencies: {e}")
            import traceback
            traceback.print_exc()
            return
        
        candidates_path = os.path.join(output_dir, "candidates_filtered.jsonl")
        doc2onto_chunks_path = os.path.join(output_dir, "chunks.jsonl")
        
        print(f"[Doc2Onto] Checking files: candidates={os.path.exists(candidates_path)}, chunks={os.path.exists(doc2onto_chunks_path)}")
        
        if not os.path.exists(candidates_path):
            print(f"[Doc2Onto] No candidates file for triple-chunk mapping")
            return

        # Load Doc2Onto sections (chunks)
        doc2onto_sections = {}
        if os.path.exists(doc2onto_chunks_path):
            with open(doc2onto_chunks_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        section = json.loads(line)
                        chunk_idx = section.get("chunk_idx")
                        text = section.get("text", "")
                        doc2onto_sections[chunk_idx] = text
                    except:
                        continue
            print(f"[Doc2Onto] Loaded {len(doc2onto_sections)} Doc2Onto sections")
        
        # Connect to Milvus to get RAGaaS chunks
        try:
            connect_milvus()
            collection_name = f"kb_{kb_id.replace('-', '_')}"
            collection = Collection(collection_name)
            collection.load()
            
            ragaas_chunks = collection.query(
                expr=f'doc_id == "{doc_id}"',
                output_fields=['chunk_id', 'content'],
                limit=1000
            )
            print(f"[Doc2Onto] Loaded {len(ragaas_chunks)} RAGaaS chunks from Milvus")
        except Exception as e:
            print(f"[Doc2Onto] ERROR loading Milvus collection: {e}")
            ragaas_chunks = []
        
        # Build section -> RAGaaS chunks mapping
        section_to_chunks = {}
        for section_idx, section_text in doc2onto_sections.items():
            section_to_chunks[section_idx] = []
            section_text_lower = section_text.lower().strip()
            
            for ragaas_chunk in ragaas_chunks:
                chunk_content = ragaas_chunk['content'].lower().strip()
                
                # Check if section text is contained in chunk or vice versa
                # Or check for significant overlap
                if section_text_lower in chunk_content or chunk_content in section_text_lower:
                    section_to_chunks[section_idx].append(ragaas_chunk['chunk_id'])
                elif len(section_text_lower) > 50 and len(chunk_content) > 50:
                    # Check for substring overlap (at least 50 chars)
                    common_len = 0
                    for i in range(min(len(section_text_lower), len(chunk_content))):
                        if section_text_lower[i:i+50] == chunk_content[i:i+50]:
                            common_len = 50
                            break
                    if common_len > 0:
                        section_to_chunks[section_idx].append(ragaas_chunk['chunk_id'])
        
        print(f"[Doc2Onto] Mapped {len(section_to_chunks)} sections to RAGaaS chunks")

        print(f"[Doc2Onto] Saving triple-chunk mappings to MongoDB...")
        
        count = 0
        saved_hashes = set()  # prevent duplicate triples for same doc
        
        try:
            with open(candidates_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        record = json.loads(line)
                    except:
                        continue
                        
                    triples_to_map = record.get("triples", [])
                    
                    for triple in triples_to_map:
                        subj = triple.get("subject", "")
                        pred = triple.get("predicate", "")
                        obj = triple.get("object", "")
                        
                        if not subj or not obj: continue
                        if subj == "Unknown" or obj == "Unknown": continue
                        
                        # Normalize names
                        norm_subj = self.normalize_entity_name(subj)
                        norm_obj = self.normalize_entity_name(obj)
                        
                        # Unique Identifier for this triple in this document
                        t_hash = compute_triple_hash(norm_subj, pred, norm_obj)
                        
                        # Check duplicate
                        if t_hash in saved_hashes:
                            continue
                        saved_hashes.add(t_hash)
                        
                        # Get section index from source_chunk_id
                        source_chunk_id = triple.get("source_chunk_id", "")
                        section_idx = None
                        if isinstance(source_chunk_id, str) and '|' in source_chunk_id:
                            try:
                                section_idx = int(source_chunk_id.split('|')[-1])
                            except:
                                pass
                        
                        # 1. Try Section-based Mapping
                        mapped_chunks = []
                        if section_idx is not None:
                             mapped_chunks = list(section_to_chunks.get(section_idx, []))
                        
                        # 2. Fallback: Entity-based Mapping (If section mapping failed OR yields no chunks)
                        if not mapped_chunks:
                            # Try to find chunks containing BOTH subject and object
                            for ragaas_chunk in ragaas_chunks:
                                content = ragaas_chunk['content']
                                # Normalize content for check
                                norm_content = content.lower()
                                ns_lower = norm_subj.lower()
                                no_lower = norm_obj.lower()
                                s_lower = subj.lower()
                                o_lower = obj.lower()
                                
                                has_subj = ns_lower in norm_content or s_lower in norm_content
                                has_obj = no_lower in norm_content or o_lower in norm_content
                                
                                if has_subj and has_obj:
                                    mapped_chunks.append(ragaas_chunk['chunk_id'])
                        
                        # 3. Last Resort: Subject OR Object match (if strict match failed)
                        if not mapped_chunks:
                             for ragaas_chunk in ragaas_chunks:
                                content = ragaas_chunk['content']
                                norm_content = content.lower()
                                ns_lower = norm_subj.lower()
                                s_lower = subj.lower()
                                
                                # Just Subject match is often enough for 'context'
                                if ns_lower in norm_content or s_lower in norm_content:
                                    mapped_chunks.append(ragaas_chunk['chunk_id'])

                        # Save mapping for each matching chunk
                        if mapped_chunks:
                            # Limit to top 3 relevant chunks to avoid explosion
                            for chunk_id in list(set(mapped_chunks))[:3]:
                                mapping = TripleChunkMapping(
                                    kb_id=kb_id,
                                    doc_id=doc_id,
                                    chunk_id=chunk_id,
                                    triple_hash=t_hash,
                                    subject=norm_subj,
                                    predicate=pred,
                                    object=norm_obj,
                                    source_start=0,
                                    source_end=1000
                                )
                                await mapping.insert()
                                count += 1
                        else:
                            # Fallback: use section index as chunk index (even if not in Milvus)
                            # This ensures the button at least appears, even if broken
                            cid = f"{doc_id}_{section_idx if section_idx is not None else 0}"
                            mapping = TripleChunkMapping(
                                kb_id=kb_id,
                                doc_id=doc_id,
                                chunk_id=cid,
                                triple_hash=t_hash,
                                subject=norm_subj,
                                predicate=pred,
                                object=norm_obj,
                                source_start=0,
                                source_end=1000
                            )
                            await mapping.insert()
                            count += 1

            
            print(f"[Doc2Onto] Saved {count} triple mappings to MongoDB")
        except Exception as e:
            print(f"[Doc2Onto] ERROR saving triple mappings: {e}")
            import traceback
            traceback.print_exc()


    async def _load_chunks_to_milvus_adapter(self, jsonl_path: str, kb_id: str, doc_id: str):
        print(f"[Doc2Onto] Loading chunks to Milvus for KB: {kb_id}")
        
        try:
            connect_milvus()
            collection = create_collection(kb_id)
        except Exception as e:
            print(f"[Doc2Onto] Failed to connect/create Milvus collection: {e}")
            return

        batch_texts = []
        batch_metadatas = []
        batch_chunk_ids = []
        
        with open(jsonl_path, "r", encoding="utf-8") as f:
            # First pass: read all lines to get correct IDs/metadata
            lines = f.readlines()
            
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                record = json.loads(line)
                
                text = record.get("text", "")
                if not text:
                    continue
                
                # Use provided chunk_idx or loop index
                chunk_idx = record.get("chunk_idx", i)
                chunk_id = f"{doc_id}_{chunk_idx}"
                
                metadata = {
                    "original_chunk_id": record.get("chunk_id"), # keep raw id in metadata
                    "chunk_idx": chunk_idx,
                    "section_path": record.get("section_path"),
                    "doc_ver": record.get("doc_ver"),
                    "source": "doc2onto"
                }
                
                batch_texts.append(text)
                batch_metadatas.append(metadata)
                batch_chunk_ids.append(chunk_id)

        if not batch_texts:
            print("[Doc2Onto] No chunks found to load to Milvus.")
            return

        try:
            embeddings = await embedding_service.get_embeddings(batch_texts)
        except Exception as e:
            print(f"[Doc2Onto] Failed to generate embeddings: {e}")
            return

        insert_data = [
            [doc_id] * len(batch_texts),
            batch_chunk_ids,
            batch_texts,
            batch_metadatas,
            embeddings
        ]
        
        try:
            res = collection.insert(insert_data)
            collection.flush()
            print(f"[Doc2Onto] Inserted {len(batch_texts)} chunks into Milvus")
        except Exception as e:
            print(f"[Doc2Onto] Failed to insert into Milvus: {e}")
            raise e

    async def process(self, text: str, chunk_id: str, **kwargs) -> Dict[str, Any]:
        """
        Legacy process method compatible with IngestionService's hybrid approach if needed.
        Currently returns empty to indicate Doc2Onto pipeline should be used via process_document_full.
        """
        print("[Doc2Onto] Legacy process called. returning empty.")
        return {"triples": [], "entities": []}

doc2onto_processor = Doc2OntoProcessor()
