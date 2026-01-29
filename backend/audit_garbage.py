
import asyncio
import os
import shutil
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.core.config import settings

async def audit_garbage():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(database=client[settings.MONGO_DB], document_models=[Document, KnowledgeBase])

    print("--- [GARBAGE AUDIT START] ---")
    
    # 1. Check Orphaned Documents (Docs referencing non-existent KBs)
    all_kbs = await KnowledgeBase.find_all().to_list()
    kb_ids = set(str(kb.id) for kb in all_kbs)
    
    all_docs = await Document.find_all().to_list()
    orphaned_docs = [d for d in all_docs if str(d.kb_id) not in kb_ids]
    
    print(f"Found {len(orphaned_docs)} orphaned documents in MongoDB.")
    
    if orphaned_docs:
        print("Cleaning up orphaned documents...")
        for doc in orphaned_docs:
            await doc.delete()
            print(f" - Deleted orphan doc: {doc.filename} ({doc.id})")

    # 2. Check File System Garbage
    # Look for files in shared storage that don't belong to any existing KB or Doc
    # (Simplified check: Just listing potential junk)
    
    # 3. Milvus Collections Check (This requires Milvus connection, skipping for quick audit)
    # But usually KB deletion drops collection.
    
    print("--- [GARBAGE AUDIT COMPLETE] ---")

if __name__ == "__main__":
    asyncio.run(audit_garbage())
