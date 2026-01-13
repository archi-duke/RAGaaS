import logging
import asyncio
from app.core.milvus import create_collection
from app.core.fuseki import fuseki_client
from app.core.database import SessionLocal
from app.models.document import Document
from sqlalchemy import delete

logger = logging.getLogger(__name__)

class CleanupService:
    async def perform_cascading_deletion(self, kb_id: str, doc_id: str):
        """
        Executes removal of all data associated with a document (Graph -> Vector -> Relational).
        This function is designed to be idempotent; safety to run multiple times.
        """
        logger.info(f"Starting cascading deletion for doc {doc_id} in KB {kb_id}")
        
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
                logger.info(f"Fuseki cleanup complete for doc {doc_id}")
            else:
                logger.warning(f"Fuseki cleanup returned failure for doc {doc_id}")
        except Exception as e:
            logger.error(f"Fuseki cleanup error for {doc_id}: {e}")

        # 1.5. Neo4j Cleanup (Graph)
        try:
            from app.core.neo4j_client import neo4j_client
            # Neo4j는 doc_id 기반 삭제가 어려우므로 (트리플에 doc_id 없음)
            # TripleChunkMapping에서 해당 doc_id의 트리플을 찾아서 삭제
            from app.models.triple_chunk_mapping import TripleChunkMapping
            async with SessionLocal() as db:
                from sqlalchemy import select
                result = await db.execute(
                    select(TripleChunkMapping.subject, TripleChunkMapping.predicate, TripleChunkMapping.object)
                    .filter(TripleChunkMapping.doc_id == doc_id)
                    .distinct()
                )
                triples_to_delete = result.fetchall()
                
                if triples_to_delete:
                    for subj, pred, obj in triples_to_delete:
                        try:
                            # 정확히 일치하는 관계만 삭제
                            delete_query = """
                            MATCH (s:Entity {name: $subj, kb_id: $kb_id})-[r]->(o:Entity {name: $obj, kb_id: $kb_id})
                            WHERE type(r) = $pred
                            DELETE r
                            """
                            neo4j_client.execute_query(delete_query, {
                                "subj": subj,
                                "obj": obj,
                                "pred": pred,
                                "kb_id": kb_id
                            })
                        except Exception as rel_e:
                            logger.warning(f"Neo4j relation delete error: {rel_e}")
                    
                    # 고아 노드 정리 (관계가 없는 노드 삭제)
                    orphan_query = """
                    MATCH (n:Entity {kb_id: $kb_id})
                    WHERE NOT (n)--()
                    DELETE n
                    """
                    neo4j_client.execute_query(orphan_query, {"kb_id": kb_id})
                    
                    logger.info(f"Neo4j cleanup complete for doc {doc_id}: deleted {len(triples_to_delete)} relations")
        except Exception as e:
            logger.error(f"Neo4j cleanup error for {doc_id}: {e}")

        # 2. Milvus Cleanup (Vector)
        try:
            collection = create_collection(kb_id)
            collection.load()
            expr = f'doc_id == "{doc_id}"'
            collection.delete(expr)
            collection.flush()
            logger.info(f"Milvus cleanup complete for doc {doc_id}")
        except Exception as e:
            logger.error(f"Milvus cleanup error for {doc_id}: {e}")

        # 3. SQLite Cleanup (Final Step)
        try:
            from app.models.triple_chunk_mapping import TripleChunkMapping  # Lazy import
            async with SessionLocal() as db:
                # 관련 TripleChunkMapping 삭제
                await db.execute(delete(TripleChunkMapping).where(TripleChunkMapping.doc_id == doc_id))
                
                # 문서 레코드 삭제
                await db.execute(delete(Document).where(Document.id == doc_id))
                
                await db.commit()
                logger.info(f"Document record and triple mappings deleted from SQLite for {doc_id}")
        except Exception as e:
            logger.error(f"SQLite cleanup error for {doc_id}: {e}")

cleanup_service = CleanupService()
