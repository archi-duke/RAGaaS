import logging
import asyncio
import os
import shutil
from pathlib import Path
from app.core.milvus import create_collection
from app.core.fuseki import fuseki_client
from app.models.document import Document
from app.models.triple_chunk_mapping import TripleChunkMapping

logger = logging.getLogger(__name__)

class CleanupService:
    async def perform_cascading_deletion(self, kb_id: str, doc_id: str):
        """
        Executes removal of all data associated with a document (Graph -> Vector -> Relational).
        """
        print(f"[Cleanup] Starting cascading deletion for doc {doc_id} in KB {kb_id}")
        
        # 0. Cancel ongoing Ingest Job if any
        try:
            from app.services.ingestion.ingest_client import ingest_client
            # document record가 있는지 먼저 확인
            doc = await Document.get(doc_id)
            if doc and doc.status == "processing":
                print(f"[Cleanup] Document {doc_id} is processing. Sending cancel request to Ingest Service...")
                try:
                    # Job ID는 doc_id와 동일하게 관리됨 (또는 doc.job_id 필드가 있다면 사용)
                    await ingest_client.cancel_job(doc_id)
                    print(f"[Cleanup] Cancel request sent for job {doc_id}")
                except Exception as cancel_e:
                    print(f"[Cleanup] Job cancel error (it might have finished): {cancel_e}")
        except Exception as e:
            print(f"[Cleanup] Error during job cancellation: {e}")

        # 1. Fuseki Cleanup (Graph) - Named Graph 기반 삭제
        try:
            # New LlamaIndex architecture uses Named Graphs: urn:doc:{doc_id}
            # Also support legacy triple-based cleanup for safety
            dataset_name = f"kb_{kb_id.replace('-', '_')}"
            graph_uri = f"urn:doc:{doc_id}"
            
            # 1.1 DELETE the Named Graph directly (GSP API)
            try:
                import requests
                response = requests.delete(
                    f"{fuseki_client.base_url}/{dataset_name}/data",
                    params={"graph": graph_uri},
                    auth=("admin", "admin")
                )
                if response.status_code in [200, 204]:
                    print(f"[Cleanup] Fuseki Named Graph {graph_uri} deleted")
                else:
                    print(f"[Cleanup] No Named Graph found at {graph_uri} (or error: {response.status_code})")
            except Exception as gsp_e:
                 print(f"[Cleanup] GSP delete error: {gsp_e}")

            # 1.2 Legacy fallback: SPARQL based cleanup
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
            print(f"[Cleanup] Fuseki legacy cleanup attempted for doc {doc_id}")
            
        except Exception as e:
            print(f"[Cleanup] Fuseki cleanup error for {doc_id}: {e}")

        # 1.5. Neo4j Cleanup (Graph)
        try:
            from app.core.neo4j_client import neo4j_client
            
            # Delete relationships with specific doc_id property
            # This works for both legacy and new Ingest Service as long as doc_id is stored on relationship
            delete_query = """
            MATCH ()-[r]->()
            WHERE r.doc_id = $doc_id
            DELETE r
            RETURN count(r) as deleted_count
            """
            
            results = neo4j_client.execute_query(delete_query, {"doc_id": doc_id})
            deleted_count = 0
            if results and len(results) > 0:
                deleted_count = results[0].get("deleted_count", 0)
            
            print(f"[Cleanup] Deleted {deleted_count} relationships in Neo4j for doc {doc_id}")
                
            # 고아 노드 정리 (관계가 없는 노드 삭제)
            orphan_query = """
            MATCH (n:Entity {kb_id: $kb_id})
            WHERE NOT (n)--()
            DELETE n
            """
            neo4j_client.execute_query(orphan_query, {"kb_id": kb_id})
            
            print(f"[Cleanup] Neo4j cleanup complete for doc {doc_id}")
        except Exception as e:
            print(f"[Cleanup] Neo4j cleanup error for {doc_id}: {e}")

        # 2. Milvus Cleanup (Vector)
        try:
            collection = create_collection(kb_id)
            collection.load()
            expr = f'doc_id == "{doc_id}"'
            res = collection.delete(expr)
            
            # CRITICAL: Flush to ensure deletion is committed
            collection.flush()
            
            print(f"[Cleanup] Milvus cleanup complete for doc {doc_id}. Deleted: {res}")
        except Exception as e:
            print(f"[Cleanup] Milvus cleanup error for {doc_id}: {e}")


        # 3. File System Cleanup (Artifacts)
        # 3.1 Legacy doc2onto artifacts
        try:
            target_path = os.path.abspath(os.path.join(os.getcwd(), "doc2onto_out", kb_id, doc_id))
            if os.path.exists(target_path):
                shutil.rmtree(target_path)
                print(f"[Cleanup] Deleted doc2onto artifacts for {doc_id}")
            alt_path = f"/app/doc2onto_out/{kb_id}/{doc_id}"
            if os.path.exists(alt_path):
                shutil.rmtree(alt_path)
                print(f"[Cleanup] Deleted alt doc2onto artifacts for {doc_id}")
        except Exception as e:
            print(f"[Cleanup] doc2onto cleanup error: {e}")
        
        # 3.2 New Ingest Service shared storage files
        try:
            from app.core.config import settings
            import glob
            upload_path = settings.SHARED_STORAGE_PATH
            # Pattern: {doc_id}_{filename}
            pattern = os.path.join(upload_path, f"{doc_id}_*")
            files = glob.glob(pattern)
            for f in files:
                try:
                    os.remove(f)
                    print(f"[Cleanup] Deleted shared storage file: {f}")
                except Exception as file_e:
                    print(f"[Cleanup] Error deleting file {f}: {file_e}")
        except Exception as e:
            print(f"[Cleanup] Shared storage cleanup error: {e}")


        # 4. MongoDB Cleanup (Final Step)
        try:
            print(f"[Cleanup] Deleting TripleChunkMappings for {doc_id}...")
            # 관련 TripleChunkMapping 삭제
            await TripleChunkMapping.find(TripleChunkMapping.doc_id == doc_id).delete()
            print(f"[Cleanup] Deleted TripleChunkMappings for {doc_id}")
            
            # 문서 레코드 삭제
            doc = await Document.get(doc_id)
            if doc:
                await doc.delete()
                print(f"[Cleanup] Deleted Document record for {doc_id}")
            else:
                print(f"[Cleanup] Document record not found for {doc_id}")
            
            # WebSocket Broadcast (삭제 완료 알림)
            try:
                from app.core.websocket_manager import manager
                print(f"[Cleanup] Broadcasting delete event for {doc_id}...")
                await manager.broadcast(kb_id, {
                    "type": "document_status_update",
                    "doc_id": doc_id,
                    "status": "deleted"
                })
                print(f"[Cleanup] Broadcast sent for {doc_id}")
            except Exception as ws_e:
                 print(f"[Cleanup] WebSocket broadcast error: {ws_e}")
            
            print(f"[Cleanup] Document and mappings deleted from MongoDB for {doc_id}")
        except Exception as e:
            print(f"[Cleanup] MongoDB cleanup error: {e}")
            import traceback
            traceback.print_exc()

        # 5. Garbage Verification (삭제 후 검증)
        await self._verify_cleanup(kb_id, doc_id)

    async def _verify_cleanup(self, kb_id: str, doc_id: str):
        """삭제 후 가비지 데이터 검증"""
        garbage_found = []
        
        # Check Milvus
        try:
            collection = create_collection(kb_id)
            collection.load()
            expr = f'doc_id == "{doc_id}"'
            results = collection.query(expr=expr, output_fields=["chunk_id"], limit=1)
            if results:
                garbage_found.append(f"Milvus: {len(results)} chunks")
        except Exception:
            pass
        
        # Check Neo4j (via TripleChunkMapping)
        try:
            remaining = await TripleChunkMapping.find(
                TripleChunkMapping.doc_id == doc_id
            ).count()
            if remaining > 0:
                garbage_found.append(f"TripleChunkMapping: {remaining} entries")
        except Exception:
            pass
        
        # Check shared storage files
        try:
            from app.core.config import settings
            import glob
            pattern = os.path.join(settings.SHARED_STORAGE_PATH, f"{doc_id}_*")
            files = glob.glob(pattern)
            if files:
                garbage_found.append(f"Storage: {len(files)} files")
        except Exception:
            pass
        
        if garbage_found:
            print(f"[Cleanup] ⚠️ GARBAGE DETECTED for {doc_id}: {', '.join(garbage_found)}")
        else:
            print(f"[Cleanup] ✅ Verification passed - no garbage for {doc_id}")

cleanup_service = CleanupService()

