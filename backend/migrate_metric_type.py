"""
Migration script to add metric_type column to knowledge_bases table.
Run this script once to update existing database.
"""

import asyncio
from sqlalchemy import text
from app.core.database import engine

async def migrate():
    async with engine.begin() as conn:
        # Check if column exists
        result = await conn.execute(text("PRAGMA table_info(knowledge_bases)"))
        columns = [row[1] for row in result]
        
        if 'metric_type' not in columns:
            print("Adding metric_type column...")
            await conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN metric_type VARCHAR DEFAULT 'IP'"))
            print("Migration completed successfully!")
        else:
            print("Column metric_type already exists. Skipping migration.")

if __name__ == "__main__":
    asyncio.run(migrate())
