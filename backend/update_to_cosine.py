"""
Update all existing knowledge bases to use COSINE metric type
"""

import asyncio
from sqlalchemy import text
from app.core.database import engine

async def update_to_cosine():
    async with engine.begin() as conn:
        # Update all existing KBs to COSINE
        result = await conn.execute(text("UPDATE knowledge_bases SET metric_type = 'COSINE'"))
        print(f"Updated {result.rowcount} knowledge bases to COSINE metric type")

if __name__ == "__main__":
    asyncio.run(update_to_cosine())
