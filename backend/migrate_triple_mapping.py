"""
Migration script to create triple_chunk_mappings table.
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os

# Use the same database URL pattern
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/rag_system.db")

async def migrate():
    print(f"Connecting to {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Create triple_chunk_mappings table
        try:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS triple_chunk_mappings (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    doc_id TEXT,
                    chunk_id TEXT,
                    triple_hash TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    source_start INTEGER NOT NULL,
                    source_end INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await session.commit()
            print("Created triple_chunk_mappings table")
        except Exception as e:
            print(f"Error creating table: {e}")
            await session.rollback()
        
        # Create indexes
        try:
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_triple_kb_id ON triple_chunk_mappings(kb_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_triple_doc_id ON triple_chunk_mappings(doc_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_triple_chunk_id ON triple_chunk_mappings(chunk_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_triple_hash ON triple_chunk_mappings(triple_hash)"
            ))
            await session.commit()
            print("Created indexes")
        except Exception as e:
            print(f"Error creating indexes: {e}")
            await session.rollback()
        
    await engine.dispose()
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
