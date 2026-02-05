
import asyncio
import sqlite3
import json
from datetime import datetime
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

# App imports
# Note: This script assumes it's run from the backend directory or with proper PYTHONPATH
from app.core.config import settings
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document, DocumentStatus
from app.models.prompt import PromptTemplate
from app.models.triple_chunk_mapping import TripleChunkMapping

# SQLite DB Path
SQLITE_DB_PATH = Path("/app/data/rag_system.db")

async def migrate():
    print("Starting Migration: SQLite -> MongoDB")
    
    if not SQLITE_DB_PATH.exists():
        print(f"SQLite DB not found at {SQLITE_DB_PATH}")
        return

    # 1. Connect to MongoDB
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(
        database=client[settings.MONGO_DB], 
        document_models=[KnowledgeBase, Document, TripleChunkMapping, PromptTemplate]
    )
    
    # 2. Connect to SQLite
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 3. Migrate KnowledgeBases
    print("\n--- Migrating Knowledge Bases ---")
    cursor.execute("SELECT * FROM knowledge_bases")
    kb_rows = cursor.fetchall()
    
    migrated_kbs = 0
    for row in kb_rows:
        try:
            # Check if exists
            existing = await KnowledgeBase.get(row['id'])
            if existing:
                print(f"Skipping KB {row['name']} (ID: {row['id']}) - Already exists")
                continue
            
            # Parse JSON fields
            chunking_config = json.loads(row['chunking_config']) if row['chunking_config'] else {}
            promotion_metadata = json.loads(row['promotion_metadata']) if row['promotion_metadata'] else {}
            # pipeline_config: legacy DB likely doesn't have this or it's new. Handle gracefully.
            pipeline_config = {"stages": []}
            if 'pipeline_config' in row.keys() and row['pipeline_config']:
                 pipeline_config = json.loads(row['pipeline_config'])
            
            kb = KnowledgeBase(
                id=row['id'],
                name=row['name'],
                description=row['description'],
                chunking_strategy=row['chunking_strategy'],
                chunking_config=chunking_config,
                metric_type=row['metric_type'],
                enable_graph_rag=bool(row['enable_graph_rag']),
                graph_backend=row['graph_backend'],
                is_promoted=bool(row['is_promoted']),
                promotion_metadata=promotion_metadata,
                pipeline_config=pipeline_config,
                created_at=datetime.fromisoformat(row['created_at']) if isinstance(row['created_at'], str) else row['created_at'],
                updated_at=datetime.fromisoformat(row['updated_at']) if isinstance(row['updated_at'], str) else row['updated_at']
            )
            await kb.insert()
            migrated_kbs += 1
            print(f"Migrated KB: {kb.name}")
            
        except Exception as e:
            print(f"Failed to migrate KB {row.get('id')}: {e}")

    print(f"Migrated {migrated_kbs} Knowledge Bases.")

    # 4. Migrate Documents
    print("\n--- Migrating Documents ---")
    cursor.execute("SELECT * FROM documents")
    doc_rows = cursor.fetchall()
    
    migrated_docs = 0
    for row in doc_rows:
        try:
            existing = await Document.get(row['id'])
            if existing:
                continue
                
            doc = Document(
                id=row['id'],
                kb_id=row['kb_id'],
                filename=row['filename'],
                file_type=row['file_type'],
                status=row['status'],
                created_at=datetime.fromisoformat(row['created_at']) if isinstance(row['created_at'], str) else row['created_at'],
                updated_at=datetime.fromisoformat(row['updated_at']) if isinstance(row['updated_at'], str) else row['updated_at']
            )
            await doc.insert()
            migrated_docs += 1
            
        except Exception as e:
            print(f"Failed to migrate Doc {row.get('id')}: {e}")
            
    print(f"Migrated {migrated_docs} Documents.")
    
    # 5. Migrate Triple Chunk Mappings (Optional but recommended)
    print("\n--- Migrating Triple Mappings (This may take a while) ---")
    
    # Check if table exists first (it might not in very old versions)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='triple_chunk_mappings'")
    if not cursor.fetchone():
        print("Table 'triple_chunk_mappings' not found in SQLite. Skipping.")
    else:
        cursor.execute("SELECT Count(*) FROM triple_chunk_mappings")
        total_mappings = cursor.fetchone()[0]
        print(f"Total mappings to migrate: {total_mappings}")
        
        cursor.execute("SELECT * FROM triple_chunk_mappings")
        
        batch_size = 1000
        batch = []
        count = 0
        
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
                
            for row in rows:
                try:
                    # Check duplication? skipped for speed, assume empty target DB
                    mapping = TripleChunkMapping(
                        id=row['id'],
                        kb_id=row['kb_id'],
                        doc_id=row['doc_id'],
                        chunk_id=row['chunk_id'],
                        triple_hash=row['triple_hash'],
                        subject=row['subject'],
                        predicate=row['predicate'],
                        object=row['object'],
                        source_start=row['source_start'],
                        source_end=row['source_end'],
                        created_at=datetime.fromisoformat(row['created_at']) if isinstance(row['created_at'], str) else row['created_at']
                    )
                    batch.append(mapping)
                except Exception as e:
                    pass # Skip bad rows
            
            if batch:
                await TripleChunkMapping.insert_many(batch)
                count += len(batch)
                print(f"Migrated {count}/{total_mappings} mappings...", end='\r')
                batch = []
                
        print(f"\nMigrated {count} Triple Mappings.")

    conn.close()
    print("\nMigration Complete.")

if __name__ == "__main__":
    asyncio.run(migrate())
