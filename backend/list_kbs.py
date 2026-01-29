
import asyncio
from app.models.knowledge_base import KnowledgeBase
from app.core.database import init_db

async def list_kbs():
    await init_db()
    kbs = await KnowledgeBase.find_all().to_list()
    print("Available Knowledge Bases:")
    for kb in kbs:
        print(f"- Name: '{kb.name}', ID: {kb.id}, Backend: {kb.graph_backend}")

if __name__ == "__main__":
    asyncio.run(list_kbs())
