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
            async with SessionLocal() as db:
                await db.execute(delete(Document).where(Document.id == doc_id))
                await db.commit()
                logger.info(f"Document record deleted from SQLite for {doc_id}")
        except Exception as e:
            logger.error(f"SQLite cleanup error for {doc_id}: {e}")

cleanup_service = CleanupService()
