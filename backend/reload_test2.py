import asyncio
import sys
import os

sys.path.append(os.getcwd())

from app.core.fuseki import FusekiClient
from app.services.ingestion.service import IngestionService
from app.models.document import Document
from app.core.database import SessionLocal
from sqlalchemy.future import select

KB_ID = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
DOC_ID = "8e56b10d-21a6-4743-9c0a-f3d6d1dcbce0"

async def reload_kb():
    # 1. Clear Fuseki Dataset
    print(f"Clearing Fuseki dataset for KB {KB_ID}...")
    fuseki = FusekiClient()
    # Note: create_dataset is idempotent (creates if not exists). 
    # To clear, we can drop and recreate, or update with DELETE? 
    # FusekiClient doesn't have explicit 'clear'. 
    # But delete_dataset exists.
    try:
        fuseki.delete_dataset(KB_ID)
        print("Dataset deleted.")
    except Exception as e:
        print(f"Delete failed (maybe didn't exist?): {e}")

    fuseki.create_dataset(KB_ID)
    print("Dataset recreated (empty).")

    # 2. Trigger Ingestion for the original document
    print(f"Triggering ingestion for Document {DOC_ID}...")
    ingestion_service = IngestionService()
    
    async with SessionLocal() as db:
        result = await db.execute(select(Document).filter(Document.id == DOC_ID))
        doc = result.scalars().first()
        if not doc:
            print("Document not found in DB!")
            return

        print(f"Found document: {doc.filename}")
        
        # Read file content from disk (Doc2Onto input backup)
        input_path = f"/app/doc2onto_out/{KB_ID}/{DOC_ID}/input/{DOC_ID}.txt"
        if not os.path.exists(input_path):
             # Try listing to be sure or just fail
             print(f"Input file not found at {input_path}")
             return
             
        with open(input_path, "rb") as f:
            file_content = f.read()

        try:
            # signature: process_document(self, kb_id, doc_id, filename, file_content, ...)
            await ingestion_service.process_document(
                kb_id=doc.kb_id,
                doc_id=doc.id,
                filename=doc.filename,
                file_content=file_content
            )
            print("Ingestion completed successfully.")
        except Exception as e:
            print(f"Ingestion failed: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    # Ensure Milvus connection
    from app.core.milvus import connect_milvus
    connect_milvus()
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(reload_kb())
