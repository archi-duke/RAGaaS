
import asyncio
import os
import sqlite3
from pymongo import MongoClient
import requests
from pymilvus import connections, utility, Collection

def check_garbage_simple(kb_id: str):
    print(f"--- Checking garbage for KB: {kb_id} ---")
    
    # 1. SQLite 확인
    db_path = "rag_system.db"
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, filename, status FROM documents WHERE kb_id = ?", (kb_id,))
        docs = cursor.fetchall()
        print(f"[SQLite] Documents in 'documents' table: {len(docs)}")
        for doc in docs:
            print(f"  - Doc ID: {doc[0]}, Filename: {doc[1]}, Status: {doc[2]}")
        conn.close()

    # 2. MongoDB 확인
    mongo_client = MongoClient("mongodb://root:example@localhost:27017")
    try:
        db = mongo_client.ragaas
        mappings = list(db.triple_chunk_mapping.find({"kb_id": kb_id}))
        print(f"[MongoDB] triple_chunk_mapping entries: {len(mappings)}")
        if mappings:
            doc_ids = set(m.get("doc_id") for m in mappings)
            print(f"  - Associated Doc IDs: {doc_ids}")
    except Exception as e:
        print(f"[MongoDB] Error: {e}")
    finally:
        mongo_client.close()

    # 3. Milvus 확인
    try:
        connections.connect("default", host="localhost", port="19530")
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        if utility.has_collection(collection_name):
            col = Collection(collection_name)
            col.load()
            num_entities = col.num_entities
            print(f"[Milvus] Collection '{collection_name}' exists. Num entities: {num_entities}")
        else:
            print(f"[Milvus] Collection '{collection_name}' does not exist.")
    except Exception as e:
        print(f"[Milvus] Error: {e}")

    # 4. Fuseki 확인
    fuseki_url = f"http://localhost:3030/{kb_id}/query"
    query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }"
    try:
        resp = requests.post(fuseki_url, data={"query": query}, timeout=5)
        if resp.status_code == 200:
            count = resp.json()["results"]["bindings"][0]["count"]["value"]
            print(f"[Fuseki] Triples found: {count}")
        else:
            print(f"[Fuseki] Check failed (Status {resp.status_code})")
    except Exception as e:
        print(f"[Fuseki] Error: {e}")

if __name__ == "__main__":
    KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
    check_garbage_simple(KB_ID)
