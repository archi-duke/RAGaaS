
import asyncio
import os
import json
import sqlite3
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie, Document
from typing import Optional

# Beanie 모델 정의 (TripleChunkMapping 확인용)
class TripleChunkMapping(Document):
    kb_id: str
    doc_id: str
    chunk_id: Optional[str]
    triple_hash: str
    subject: str
    predicate: str
    object: str
    
    class Settings:
        name = "triple_chunk_mapping"

async def check_garbage(kb_id: str):
    print(f"--- Checking garbage for KB: {kb_id} ---")
    
    # 1. SQLite 확인
    db_path = "rag_system.db"
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, filename, status FROM documents WHERE kb_id = ?", (kb_id,))
        docs = cursor.fetchall()
        print(f"[SQLite] Documents found: {len(docs)}")
        for doc in docs:
            print(f"  - Doc ID: {doc[0]}, Filename: {doc[1]}, Status: {doc[2]}")
        
        conn.close()
    else:
        print("[SQLite] db file not found")

    # 2. MongoDB 확인
    mongo_uri = "mongodb://root:example@localhost:27017"
    client = AsyncIOMotorClient(mongo_uri)
    try:
        await init_beanie(database=client.ragaas, document_models=[TripleChunkMapping])
        mappings_count = await TripleChunkMapping.find(TripleChunkMapping.kb_id == kb_id).count()
        print(f"[MongoDB] TripleChunkMapping found: {mappings_count}")
        
        if mappings_count > 0:
            distinct_docs = await TripleChunkMapping.distinct("doc_id", {"kb_id": kb_id})
            print(f"  - Linked to Doc IDs: {distinct_docs}")
    except Exception as e:
        print(f"[MongoDB] Error: {e}")
    finally:
        client.close()

    # 3. Fuseki 확인 (JF이므로 Fuseki 가능성 높음)
    import requests
    fuseki_url = "http://localhost:3030/4ba60b29-cfd3-4c04-969a-bfa64d6a46e1/query" # dataset name is kb_id
    query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }"
    try:
        resp = requests.post(fuseki_url, data={"query": query}, timeout=5)
        if resp.status_code == 200:
            count = resp.json()["results"]["bindings"][0]["count"]["value"]
            print(f"[Fuseki] Triples found in dataset '{kb_id}': {count}")
        else:
            print(f"[Fuseki] Dataset '{kb_id}' check status: {resp.status_code}")
    except Exception as e:
        print(f"[Fuseki] Error (maybe dataset name is different or fuseki is down): {e}")

if __name__ == "__main__":
    KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
    asyncio.run(check_garbage(KB_ID))
