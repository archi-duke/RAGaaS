import logging
import asyncio
import os
import shutil
from pathlib import Path
from app.core.milvus import create_collection
from app.core.fuseki import fuseki_client
from app.models.document import Document

logger = logging.getLogger(__name__)

class CleanupService:
    async def perform_cascading_deletion(self, kb_id: str, doc_id: str):
        """
        Executes removal of all data associated with a document (Graph -> Vector -> Relational).
        Enforces transactional integrity: if Graph/Vector deletion fails, MongoDB record remains.
        """
        print(f"[Cleanup] Starting cascading deletion for doc {doc_id} in KB {kb_id}")
        
        # 0. Cancel ongoing Ingest Job if any
        try:
            from app.services.ingestion.ingest_client import ingest_client
            doc = await Document.get(doc_id)
            if doc and doc.status == "processing":
                print(f"[Cleanup] Document {doc_id} is processing. Sending cancel request...")
                await ingest_client.cancel_job(doc_id)
        except Exception as e:
            print(f"[Cleanup] Job cancel warning: {e}")

        # 1. Fuseki Cleanup (Graph) - CRITICAL
        try:
            dataset_name = f"kb_{kb_id.replace('-', '_')}"
            graph_uri = f"urn:doc:{doc_id}"
            
            # 1.1 DROP GRAPH
            fuseki_client.drop_graph(kb_id, graph_uri)
            
            # 1.2 Legacy Cleanup (Sparql Update)
            source_prefix = f"http://rag.local/source/{doc_id}"
            delete_query = f"""
            PREFIX rel: <http://rag.local/relation/>
            DELETE {{ ?s ?p ?o . ?inv_s ?inv_p ?s . }}
            WHERE {{
                ?s rel:hasSource ?src .
                FILTER(STRSTARTS(STR(?src), "{source_prefix}")) .
                ?s ?p ?o .
                OPTIONAL {{ ?inv_s ?inv_p ?s }}
            }}
            """
            fuseki_client.update_sparql(kb_id, delete_query)
            
            print(f"[Cleanup] ✅ Fuseki deletion executed for {doc_id}")
            
        except Exception as e:
            print(f"[Cleanup] ❌ Fuseki cleanup failed: {e}")
            raise RuntimeError(f"Failed to delete graph data from Fuseki: {e}")

        # 1.5. Neo4j Cleanup (Graph) - CRITICAL
        try:
            from app.core.neo4j_client import neo4j_client
            
            # Delete relationships
            delete_query = """
            MATCH ()-[r]->()
            WHERE r.doc_id = $doc_id
            DELETE r
            RETURN count(r) as deleted_count
            """
            neo4j_client.execute_query(delete_query, {"doc_id": doc_id})
            
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
            raise RuntimeError(f"Failed to delete graph data from Neo4j: {e}")

        # 2. Milvus Cleanup (Vector) - CRITICAL
        try:
            from pymilvus import utility
            collection = create_collection(kb_id)
            collection.load()
            
            expr = f'doc_id == "{doc_id}"'
            collection.delete(expr)
            collection.flush()
            
            # Verify Milvus immediately
            verify_res = collection.query(expr, output_fields=["chunk_id"], limit=1)
            if verify_res:
                raise RuntimeError("Milvus deletion failed (entities still exist)")
            
            print(f"[Cleanup] ✅ Milvus deletion verified for {doc_id}")
            
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
            error_msg = f"Cleanup verification failed. Residual data found: {garbage_info}"
            print(f"[Cleanup] ❌ {error_msg}")
            raise RuntimeError(error_msg)

        # 4. MongoDB Cleanup (Final Step)
        try:
            doc = await Document.get(doc_id)
            if doc:
                await doc.delete()
                print(f"[Cleanup] ✅ Deleted Document record for {doc_id}")
            
            # Broadcast update
            try:
                from app.core.websocket_manager import manager
                await manager.broadcast(kb_id, {
                    "type": "document_status_update", 
                    "doc_id": doc_id, 
                    "status": "deleted"
                })
            except:
                pass
                
        except Exception as e:
            print(f"[Cleanup] ❌ MongoDB cleanup error: {e}")
            raise RuntimeError(f"Failed to delete document record: {e}")


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

