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
        This function is designed to be idempotent; safety to run multiple times.
        """
        print(f"[Cleanup] Starting cascading deletion for doc {doc_id} in KB {kb_id}")
        
        # 1. Fuseki Cleanup (Graph)
        try:
            # Delete all triples where source matches doc_id prefix
            source_prefix = f"http://rag.local/source/{doc_id}"
            delete_query = f"""
            PREFIX rel: <http://rag.local/relation/>
            DELETE {{
                ?s ?p ?o .
                ?inv_s ?inv_p ?s . 
            }}
            WHERE {{
                ?s rel:hasSource ?src .
                FILTER(STRSTARTS(STR(?src), "{source_prefix}")) .
                ?s ?p ?o .
                OPTIONAL {{ ?inv_s ?inv_p ?s }}
            }}
            """
            success = fuseki_client.update_sparql(kb_id, delete_query)
            if success:
                print(f"[Cleanup] Fuseki cleanup complete for doc {doc_id}")
            else:
                print(f"[Cleanup] Fuseki cleanup returned failure for doc {doc_id}")
        except Exception as e:
            print(f"[Cleanup] Fuseki cleanup error for {doc_id}: {e}")

        # 1.5. Neo4j Cleanup (Graph)
        try:
            from app.core.neo4j_client import neo4j_client
            # TripleChunkMapping에서 해당 doc_id의 트리플을 찾아서 삭제
            triples_to_delete = await TripleChunkMapping.find(
                TripleChunkMapping.doc_id == doc_id
            ).to_list()
            
            if triples_to_delete:
                for mapping in triples_to_delete:
                    try:
                        # 정확히 일치하는 관계만 삭제
                        delete_query = """
                        MATCH (s:Entity {name: $subj, kb_id: $kb_id})-[r]->(o:Entity {name: $obj, kb_id: $kb_id})
                        WHERE type(r) = $pred
                        DELETE r
                        """
                        neo4j_client.execute_query(delete_query, {
                            "subj": mapping.subject,
                            "obj": mapping.object,
                            "pred": mapping.predicate,
                            "kb_id": kb_id
                        })
                    except Exception as rel_e:
                        print(f"[Cleanup] Neo4j relation delete error: {rel_e}")
                
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
        try:
            # Match doc2onto.py logic: os.path.join(os.getcwd(), "doc2onto_out", kb_id, doc_id)
            target_path = os.path.abspath(os.path.join(os.getcwd(), "doc2onto_out", kb_id, doc_id))
            if os.path.exists(target_path):
                shutil.rmtree(target_path)
                print(f"[Cleanup] Deleted filesystem artifacts for {doc_id} at {target_path}")
            else:
                print(f"[Cleanup] No artifacts found at {target_path}")
                # Try fallback for docker env if getcwd is weird
                alt_path = f"/app/doc2onto_out/{kb_id}/{doc_id}"
                if os.path.exists(alt_path):
                    shutil.rmtree(alt_path)
                    print(f"[Cleanup] Deleted artifacts at alternate path {alt_path}")
        except Exception as e:
            print(f"[Cleanup] Filesystem cleanup error: {e}")

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

cleanup_service = CleanupService()
