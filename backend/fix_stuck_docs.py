
import asyncio
import os
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.core.config import settings

async def fix_stuck_documents():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(database=client[settings.MONGO_DB], document_models=[Document, KnowledgeBase])

    # Find documents stuck in DELETING
    stuck_docs = await Document.find(Document.status == "deleting").to_list()
    
    if not stuck_docs:
        print("No documents stuck in 'deleting' state found.")
        return

    print(f"Found {len(stuck_docs)} documents stuck in DELETING.")
    
    for doc in stuck_docs:
        print(f"Resetting status for doc {doc.id} ({doc.filename})...")
        doc.status = DocumentStatus.ERROR.value
        doc.pipeline_metadata = doc.pipeline_metadata or {}
        doc.pipeline_metadata['error'] = "Force reset from stuck deleting state"
        await doc.save()
        print(f" -> Set to ERROR.")

    print("Done.")

if __name__ == "__main__":
    asyncio.run(fix_stuck_documents())
