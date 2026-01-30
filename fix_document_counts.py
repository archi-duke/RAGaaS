#!/usr/bin/env python3
"""
Fix document counts for existing documents
"""
import asyncio
import os
import json
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from app.models.document import Document
from app.core.config import settings

async def fix_counts():
    # Initialize Beanie
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    await init_beanie(database=db, document_models=[Document])
    
    # Get all completed documents
    docs = await Document.find(Document.status == "completed").to_list()
    
    print(f"Found {len(docs)} completed documents")
    
    for doc in docs:
        print(f"\nProcessing doc {doc.id} ({doc.filename})...")
        
        # Read entity_count from .temp
        temp_dict_path = os.path.join(
            settings.SHARED_STORAGE_PATH, 
            ".temp", 
            str(doc.kb_id), 
            str(doc.id), 
            "entity_dictionary.json"
        )
        
        if os.path.exists(temp_dict_path):
            try:
                with open(temp_dict_path, 'r', encoding='utf-8') as f:
                    entity_data = json.load(f)
                    doc.entity_count = entity_data.get("entity_count", 0)
                    print(f"  ✅ entity_count: {doc.entity_count}")
            except Exception as e:
                print(f"  ❌ Failed to read entity_count: {e}")
        
        # Read chunk_count from .temp
        temp_chunks_path = os.path.join(
            settings.SHARED_STORAGE_PATH, 
            ".temp", 
            str(doc.kb_id), 
            str(doc.id), 
            "chunks.json"
        )
        
        if os.path.exists(temp_chunks_path):
            try:
                with open(temp_chunks_path, 'r', encoding='utf-8') as f:
                    chunks_data = json.load(f)
                    doc.chunk_count = chunks_data.get("chunk_count", 0)
                    print(f"  ✅ chunk_count: {doc.chunk_count}")
            except Exception as e:
                print(f"  ❌ Failed to read chunk_count: {e}")
        
        # Read triple_count from .temp
        temp_triples_path = os.path.join(
            settings.SHARED_STORAGE_PATH, 
            ".temp", 
            str(doc.kb_id), 
            str(doc.id), 
            "triples.json"
        )
        
        if os.path.exists(temp_triples_path):
            try:
                with open(temp_triples_path, 'r', encoding='utf-8') as f:
                    triples_data = json.load(f)
                    if isinstance(triples_data, list):
                        doc.triple_count = len(triples_data)
                    else:
                        doc.triple_count = triples_data.get("triple_count", 0)
                    print(f"  ✅ triple_count: {doc.triple_count}")
            except Exception as e:
                print(f"  ❌ Failed to read triple_count: {e}")
        
        await doc.save()
        print(f"  💾 Saved!")

if __name__ == "__main__":
    asyncio.run(fix_counts())
