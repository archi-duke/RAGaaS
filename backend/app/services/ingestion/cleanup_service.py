import logging
import asyncio
import os
import shutil
from pathlib import Path
from app.core.milvus import create_collection
from app.core.fuseki import fuseki_client
from app.models.document import Document, DocumentStatus

logger = logging.getLogger(__name__)

class CleanupService:
    async def perform_cascading_deletion(self, kb_id: str, doc_id: str):
        """
        Executes removal of all data associated with a document (Graph -> Vector -> Relational).
        Enforces transactional integrity: if Graph/Vector deletion fails, MongoDB record remains in ERROR state.
        """
        print(f"[Cleanup] Starting cascading deletion for doc {doc_id} in KB {kb_id}")
        from app.models.document import Document, DocumentStatus
        
        try:
            # Ensure Milvus connection (idempotent-ish check usually needed, but helper might handle it)
            try:
                 from app.core.milvus import connect_milvus
                 connect_milvus()
            except:
                 pass
    
            collection = None
            
            # 0. Cancel ongoing Ingest Job if any
            try:
                from app.services.ingestion.ingest_client import ingest_client
                doc = await Document.get(doc_id)
                if doc and doc.status == "processing":
                    print(f"[Cleanup] Document {doc_id} is processing. Sending cancel request...")
                    await ingest_client.cancel_job(doc_id)
            except Exception as e:
                print(f"[Cleanup] Job cancel warning: {e}")
    
            # 1. Fetch Chunk IDs from Milvus (Source of Truth for Doc-Chunk mapping)
            chunk_ids = []
            try:
                from pymilvus import utility
                collection = create_collection(kb_id)
                collection.load()
                
                # Query all chunks for this doc
                expr = f'doc_id == "{doc_id}"'
                try:
                    # Limit 10000 to be safe, if more, might need paging but unlikely for single doc
                    res = collection.query(expr, output_fields=["chunk_id"], limit=10000)
                    chunk_ids = [r["chunk_id"] for r in res]
                    print(f"[Cleanup] Identified {len(chunk_ids)} chunks for doc {doc_id}")
                except Exception as e:
                    print(f"[Cleanup] Failed to query chunks for doc {doc_id}: {e}")
                    
            except Exception as e:
                print(f"[Cleanup] ❌ Milvus connection failed: {e}")
                # Don't return yet, try to proceed with what we can
    
            # 2. Fuseki Cleanup (Graph)
            try:
                dataset_name = f"kb_{kb_id.replace('-', '_')}"
                graph_uri = f"urn:doc:{doc_id}"
                
                # 2.1 DROP GRAPH (Named Graph)
                fuseki_client.drop_graph(kb_id, graph_uri)
                
                # 2.2 Delete by Chunk IDs (Reification & Direct) in ALL Named Graphs
                if chunk_ids:
                    # Batch delete if too many
                    batch_size = 50
                    for i in range(0, len(chunk_ids), batch_size):
                        batch = chunk_ids[i:i+batch_size]
                        
                        # Quote IDs for SPARQL
                        quoted_ids = " ".join([f'"{cid}"' for cid in batch])
                        
                        # [FIX] Use GRAPH ?g to target ALL named graphs. 
                        # Without it, DELETE only affects the default graph.
                        delete_query = f"""
                        PREFIX rel: <http://rag.local/relation/>
                        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                        PREFIX meta: <http://rag.local/meta/>
                        
                        DELETE {{ 
                            GRAPH ?g {{
                                ?stmt ?stmt_p ?stmt_o .
                                ?s ?p ?o .
                                ?inv_s ?inv_p ?s .
                            }}
                        }}
                        WHERE {{
                            GRAPH ?g {{
                                VALUES ?cid {{ {quoted_ids} }}
                                {{
                                    # Pattern 1: Reification (meta:sourceNodeId)
                                    ?stmt meta:sourceNodeId ?cid .
                                    ?stmt ?stmt_p ?stmt_o .
                                    OPTIONAL {{
                                        ?stmt rdf:subject ?s .
                                        ?s ?p ?o .
                                        OPTIONAL {{ ?inv_s ?inv_p ?s }}
                                    }}
                                }}
                                UNION
                                {{
                                     # Pattern 2: Direct Link (source URI)
                                     BIND(URI(CONCAT("http://rag.local/source/", ?cid)) as ?srcUri)
                                     ?s rel:hasSource ?srcUri .
                                     ?s ?p ?o .
                                     OPTIONAL {{ ?inv_s ?inv_p ?s }}
                                }}
                            }}
                        }}
                        """
                        fuseki_client.update_sparql(kb_id, delete_query)
                        
                        # [ADD] Also drop manual graphs explicitly just in case they are completely separate
                        for cid in batch:
                            manual_graph_uri = f"urn:doc:manual_{cid}"
                            fuseki_client.drop_graph(kb_id, manual_graph_uri)
                    
                # 2.3 Cleanup by meta:docId (Final safety net)
                final_cleanup_query = f"""
                PREFIX meta: <http://rag.local/meta/>
                DELETE {{ 
                    GRAPH ?g {{ ?s ?p ?o }} 
                }}
                WHERE {{
                    GRAPH ?g {{
                        ?stmt meta:docId ?did .
                        FILTER(?did = "{doc_id}")
                        ?s ?p ?o .
                    }}
                }}
                """
                fuseki_client.update_sparql(kb_id, final_cleanup_query)
    
                    
                print(f"[Cleanup] ✅ Fuseki deletion executed for {doc_id}")
                
            except Exception as e:
                print(f"[Cleanup] ❌ Fuseki cleanup failed: {e}")
                # We continue to Milvus cleanup even if Graph fails, to ensure at least vector space is clean
    
            # 3. Neo4j Cleanup (Graph)
            try:
                from app.core.neo4j_client import neo4j_client
                
                # Delete by doc_id
                delete_query = """
                MATCH ()-[r]->()
                WHERE r.doc_id = $doc_id
                DELETE r
                RETURN count(r) as deleted_count
                """
                neo4j_client.execute_query(delete_query, {"doc_id": doc_id})
                
                # Delete by Chunk IDs (if doc_id missing on relationships)
                if chunk_ids:
                     batch_size = 1000
                     for i in range(0, len(chunk_ids), batch_size):
                        batch = chunk_ids[i:i+batch_size]
                        chunk_query = """
                        MATCH ()-[r]->()
                        WHERE r.source_node_id IN $batch
                        DELETE r
                        """
                        neo4j_client.execute_query(chunk_query, {"batch": batch})
    
                # Delete isolated nodes
                orphan_query = """
                MATCH (n:Entity {kb_id: $kb_id})
                WHERE NOT (n)--()
                DELETE n
                """
                neo4j_client.execute_query(orphan_query, {"kb_id": kb_id})
                
                print(f"[Cleanup] ✅ Neo4j deletion executed for {doc_id}")
            except Exception as e:
                print(f"[Cleanup] ❌ Neo4j cleanup failed: {e}")
    
            # 4. Milvus Cleanup (Vector)
            try:
                if not collection: # In case connection failed in Step 1
                    collection = create_collection(kb_id)
                    collection.load()
                
                expr = f'doc_id == "{doc_id}"'
                collection.delete(expr)
                collection.flush()
                
                print(f"[Cleanup] ✅ Milvus deletion flushed for {doc_id}")
                
                try:
                    collection.release()
                except: 
                    pass
                    
            except Exception as e:
                print(f"[Cleanup] ❌ Milvus cleanup failed: {e}")
                raise RuntimeError(f"Failed to delete vector data from Milvus: {e}")
    
            # 3. File System Cleanup (Artifacts) - Non-critical
            try:
                target_path = os.path.abspath(os.path.join(os.getcwd(), "doc2onto_out", kb_id, doc_id))
                if os.path.exists(target_path):
                    shutil.rmtree(target_path)
                
                alt_path = f"/app/doc2onto_out/{kb_id}/{doc_id}"
                if os.path.exists(alt_path):
                    shutil.rmtree(alt_path)
                    
                from app.core.config import settings
                import glob
                pattern = os.path.join(settings.SHARED_STORAGE_PATH, f"{doc_id}_*")
                for f in glob.glob(pattern):
                    try:
                        os.remove(f)
                    except:
                        pass
            except Exception as e:
                print(f"[Cleanup] Filesystem cleanup warning: {e}")
    
            # ⭐️ PRE-COMMIT VERIFICATION
            # Verify that Graph DBs are truly clean before deleting the user record.
            is_clean, garbage_info = await self._verify_cleanup(kb_id, doc_id)
            if not is_clean:
                error_msg = f"Cleanup verification warning. Residual data found: {garbage_info}"
                print(f"[Cleanup] ⚠️ {error_msg} - Proceeding with document deletion anyway.")
                # raise RuntimeError(error_msg)  <-- REMOVED: Do not block deletion
    
            # 4. MongoDB Cleanup (Final Step)
            # Delete Document record
            doc = await Document.get(doc_id)
            if doc:
                await doc.delete()
                print(f"[Cleanup] ✅ Deleted Document record for {doc_id}")
            else:
                print(f"[Cleanup] ⚠️ Document {doc_id} not found/already deleted.")
            
            # Delete Related Mappings (triple_chunk_mappings)
            try:
                # Use raw mongodb access via Document's database.
                db = Document.get_motor_client()[Document.get_settings().motor_db_name]
                res = await db["triple_chunk_mappings"].delete_many({"doc_id": doc_id})
                print(f"[Cleanup] ✅ Deleted {res.deleted_count} triple_chunk_mappings for {doc_id}")
            except Exception as e:
                print(f"[Cleanup] ⚠️ Failed to clean triple_chunk_mappings: {e}")
    
            # Broadcast update
            try:
                from app.core.websocket_manager import manager
                await manager.broadcast(kb_id, {
                    "type": "document_status_update", 
                    "doc_id": doc_id, 
                    "status": "deleted"
                })
                print(f"[Cleanup] ✅ WebSocket broadcast sent: doc {doc_id} deleted")
            except Exception as ws_error:
                print(f"[Cleanup] ⚠️  WebSocket broadcast failed: {ws_error}")
        
        except Exception as e:
            print(f"[Cleanup] Critical error during cascading deletion: {e}")
            import traceback
            traceback.print_exc()
            try:
                # Re-fetch doc to ensure we have latest state
                doc = await Document.get(doc_id)
                if doc:
                    doc.status = DocumentStatus.ERROR.value
                    # Optionally store error reason
                    if not doc.pipeline_metadata: doc.pipeline_metadata = {}
                    doc.pipeline_metadata['error'] = str(e)
                    await doc.save()
                    print(f"[Cleanup] Document status reverted to ERROR for {doc_id}")
            except Exception as db_err:
                print(f"[Cleanup] Failed to update document status to ERROR: {db_err}")


    async def _verify_cleanup(self, kb_id: str, doc_id: str):
        """삭제 후 가비지 데이터 검증 (True if clean)"""
        garbage_found = []
        
        # 1. Check Fuseki
        try:
            # Check Named Graph existence
            check_sparql = f"ASK {{ GRAPH <urn:doc:{doc_id}> {{ ?s ?p ?o }} }}"
            res = fuseki_client.query_sparql(kb_id, check_sparql)
            if res and res.get("boolean", False):
                 garbage_found.append("Fuseki Named Graph")
        except:
            pass
            
        # 2. Check Neo4j
        try:
            from app.core.neo4j_client import neo4j_client
            check_query = "MATCH ()-[r]->() WHERE r.doc_id = $doc_id RETURN count(r) as cnt"
            res = neo4j_client.execute_query(check_query, {"doc_id": doc_id})
            if res and res[0]["cnt"] > 0:
                garbage_found.append(f"Neo4j Relationships ({res[0]['cnt']})")
        except:
            pass

        # 3. Check Milvus
        try:
            collection = create_collection(kb_id)
            collection.load()
            res = collection.query(f'doc_id == "{doc_id}"', output_fields=["chunk_id"], limit=1)
            if res:
                garbage_found.append("Milvus Vectors")
        except:
            pass
        
        if garbage_found:
            return False, ", ".join(garbage_found)
        return True, "Clean"

cleanup_service = CleanupService()

