from app.core.database import SessionLocal
from app.models.document import Document
from sqlalchemy import select
import asyncio

async def check_doc(doc_id):
    async with SessionLocal() as db:
        res = await db.execute(select(Document).filter(Document.id == doc_id))
        doc = res.scalars().first()
        if doc:
            print(f"Doc {doc_id} found. Status: {doc.status}")
        else:
            print(f"Doc {doc_id} NOT found.")

if __name__ == "__main__":
    import sys
    doc_id = "6d30fb83-e697-429f-8f55-77b022a0a5b9"
    asyncio.run(check_doc(doc_id))
