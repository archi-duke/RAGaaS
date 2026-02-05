import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os

DATABASE_URL = "sqlite+aiosqlite:///backend/data/rag_system.db"
if not os.path.exists("backend/data/rag_system.db"):
    DATABASE_URL = "sqlite+aiosqlite:///data/rag_system.db"
    if not os.path.exists("data/rag_system.db"):
         DATABASE_URL = "sqlite+aiosqlite:///rag_system.db"

async def migrate():
    print(f"Connecting to {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        try:
            await session.execute(text(
                "ALTER TABLE knowledge_bases ADD COLUMN promotion_metadata JSON DEFAULT '{}'"
            ))
            await session.commit()
            print("Added promotion_metadata column to knowledge_bases")
        except Exception as e:
            print(f"Column might already exist or error: {e}")
            await session.rollback()
        
    await engine.dispose()
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
