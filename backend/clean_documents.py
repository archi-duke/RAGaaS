"""
Clean all documents from database to allow fresh start
"""

import asyncio
from sqlalchemy import text
from app.core.database import engine

async def clean_documents():
    async with engine.begin() as conn:
        # Delete all documents
        result = await conn.execute(text("DELETE FROM documents"))
        print(f"Deleted {result.rowcount} documents from database")

if __name__ == "__main__":
    asyncio.run(clean_documents())
