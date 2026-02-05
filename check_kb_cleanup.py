import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymilvus import connections, utility
from neo4j import GraphDatabase
import requests
import os
import glob

KB_ID = "49d09a72-3aac-457b-8340-c15983dd8f98"

async def check_kb_cleanup(kb_id):
    print(f"--- Cleanup Check for KB: {kb_id} ---")
    
    # 1. MongoDB
    try:
        client = AsyncIOMotorClient("mongodb://root:example@localhost:27017")
        db = client.ragaas
        kb = await db.knowledge_bases.find_one({"_id": kb_id})
        if kb:
            print(f"[MongoDB] KB record STILL EXISTS. Name: {kb.get('name')}")
        else:
            print("[MongoDB] KB record is GONE.")
            
        doc_count = await db.documents.count_documents({"kb_id": kb_id})
        mapping_count = await db.triple_chunk_mappings.count_documents({"kb_id": kb_id})
        print(f"[MongoDB] Associated Documents: {doc_count}, Mappings: {mapping_count}")
    except Exception as e:
        print(f"[MongoDB] Error: {e}")

    # 2. Milvus
    try:
        connections.connect(host="localhost", port="19530")
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        if utility.has_collection(collection_name):
            print(f"[Milvus] Collection {collection_name} STILL EXISTS.")
        else:
            print(f"[Milvus] Collection {collection_name} is GONE.")
    except Exception as e:
        print(f"[Milvus] Error: {e}")

    # 3. Neo4j
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        with driver.session() as session:
            node_count = session.run("MATCH (n {kb_id: $kb_id}) RETURN count(n) as count", {"kb_id": kb_id}).single()["count"]
            rel_count = session.run("MATCH ()-[r {kb_id: $kb_id}]->() RETURN count(r) as count", {"kb_id": kb_id}).single()["count"]
        driver.close()
        print(f"[Neo4j] Associated Nodes: {node_count}, Relationships: {rel_count}")
    except Exception as e:
        print(f"[Neo4j] Error: {e}")

    # 4. Fuseki
    try:
        # Fuseki uses Named Graphs with ID
        response = requests.get("http://localhost:3030/$/datasets", auth=("admin", "admin"))
        if response.status_code == 200:
            datasets = response.json()["datasets"]
            print(f"[Fuseki] Datasets found: {[ds['ds.name'] for ds in datasets]}")
            # Check specifically for data in onto dataset
            # (Requires SPARQL query to be sure, but let's check dataset existence first)
        else:
            print(f"[Fuseki] Error status: {response.status_code}")
    except Exception as e:
        print(f"[Fuseki] Error: {e}")

    # 5. Shared Storage (Files)
    kb_path = f"./data/uploads/{kb_id}"
    if os.path.exists(kb_path):
        files = glob.glob(f"{kb_path}/**/*", recursive=True)
        files = [f for f in files if os.path.isfile(f)]
        print(f"[Storage] Folder {kb_path} STILL EXISTS with {len(files)} files.")
    else:
        print(f"[Storage] Folder {kb_path} is GONE.")

if __name__ == "__main__":
    asyncio.run(check_kb_cleanup(KB_ID))
