
import asyncio
import os
import sys

# Add backend dir to path
sys.path.append(os.path.abspath("backend"))

from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings

async def main():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(database=client[settings.MONGO_DB], document_models=[KnowledgeBase, Document])

    kb = await KnowledgeBase.find_one({"name": "test jf"})
    if not kb:
        print("KB 'test jf' not found")
        return

    print(f"KB ID: {kb.id}")
    print(f"KB Graph Backend: {kb.graph_backend}")

    docs = await Document.find(Document.kb_id == str(kb.id)).to_list()
    print(f"Total documents found in MongoDB for this KB: {len(docs)}")
    for d in docs:
        print(f" - {d.filename} (ID: {d.id}, Status: {d.status})")

if __name__ == "__main__":
    asyncio.run(main())
