#!/usr/bin/env python3
import asyncio
import os
import json
import sys

sys.path.insert(0, '/Users/dukekimm/Works/RAGaaS/backend')

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie, Document as BeanieDocument
from pydantic import Field
from typing import Optional

# Load .env
from dotenv import load_dotenv
load_dotenv('/Users/dukekimm/Works/RAGaaS/backend/.env')

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB_NAME", "ragaas")
SHARED_STORAGE = "/Users/dukekimm/Works/RAGaaS/data/uploads"

class Document(BeanieDocument):
    filename: str
    kb_id: str
    status: str
    chunk_count: Optional[int] = None
    entity_count: Optional[int] = None
    triple_count: Optional[int] = None
    
    class Settings:
        name = "documents"

async def main():
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[MONGODB_DB]
    await init_beanie(database=db, document_models=[Document])
    
    docs = await Document.find(Document.status == "completed").to_list()
    print(f"Found {len(docs)} completed documents\n")
    
    for doc in docs:
        print(f"Doc {doc.id} ({doc.filename})")
        
        # Entity count
        entity_path = f"{SHARED_STORAGE}/.temp/{doc.kb_id}/{doc.id}/entity_dictionary.json"
        if os.path.exists(entity_path):
            with open(entity_path) as f:
                data = json.load(f)
                doc.entity_count = data.get("entity_count", 0)
                print(f"  entity_count: {doc.entity_count}")
        
        # Chunk count
        chunks_path = f"{SHARED_STORAGE}/.temp/{doc.kb_id}/{doc.id}/chunks.json"
        if os.path.exists(chunks_path):
            with open(chunks_path) as f:
                data = json.load(f)
                doc.chunk_count = data.get("chunk_count", 0)
                print(f"  chunk_count: {doc.chunk_count}")
        
        # Triple count
        triples_path = f"{SHARED_STORAGE}/.temp/{doc.kb_id}/{doc.id}/triples.json"
        if os.path.exists(triples_path):
            with open(triples_path) as f:
                data = json.load(f)
                if isinstance(data, list):
                    doc.triple_count = len(data)
                else:
                    doc.triple_count = data.get("triple_count", 0)
                print(f"  triple_count: {doc.triple_count}")
        
        await doc.save()
        print("  ✅ Saved!\n")

if __name__ == "__main__":
    asyncio.run(main())
