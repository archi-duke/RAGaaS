"""
Migration script to add updated_at to existing documents
"""
import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# Use the same database URL as in your config
DATABASE_URL = "sqlite+aiosqlite:///./rag_system.db"

async def migrate():
    engine = create_async_engine(DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Add the column if it doesn't exist (SQLite doesn't have ALTER COLUMN)
        try:
            await session.execute(text(
                "ALTER TABLE documents ADD COLUMN updated_at TIMESTAMP"
            ))
            await session.commit()
            print("Added updated_at column")
        except Exception as e:
            print(f"Column might already exist: {e}")
            await session.rollback()
        
        # Update all existing documents to have updated_at = created_at
        await session.execute(text(
            "UPDATE documents SET updated_at = created_at WHERE updated_at IS NULL"
        ))
        await session.commit()
        print("Updated existing documents")
    
    await engine.dispose()
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
