import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymilvus import connections, utility
from neo4j import GraphDatabase
import requests
import os
import glob

async def check_garbage():
    print("--- Garbage Check Report ---")
    
    # 1. MongoDB
    try:
        client = AsyncIOMotorClient("mongodb://root:example@localhost:27017")
        db = client.ragaas
        kb_count = await db.knowledge_bases.count_documents({})
        doc_count = await db.documents.count_documents({})
        mapping_count = await db.triple_chunk_mappings.count_documents({})
        print(f"[MongoDB] KBs: {kb_count}, Documents: {doc_count}, Mappings: {mapping_count}")
    except Exception as e:
        print(f"[MongoDB] Error: {e}")

    # 2. Milvus
    try:
        connections.connect(host="localhost", port="19530")
        collections = utility.list_collections()
        print(f"[Milvus] Collections: {collections}")
    except Exception as e:
        print(f"[Milvus] Error: {e}")

    # 3. Neo4j
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        with driver.session() as session:
            node_count = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]
        driver.close()
        print(f"[Neo4j] Nodes: {node_count}, Relationships: {rel_count}")
    except Exception as e:
        print(f"[Neo4j] Error: {e}")

    # 4. Fuseki
    try:
        response = requests.get("http://localhost:3030/$/datasets", auth=("admin", "admin"))
        if response.status_code == 200:
            datasets = [ds["ds.name"] for ds in response.json()["datasets"]]
            print(f"[Fuseki] Datasets: {datasets}")
        else:
            print(f"[Fuseki] Error status: {response.status_code}")
    except Exception as e:
        print(f"[Fuseki] Error: {e}")

    # 5. Shared Storage (Files)
    upload_path = "./data/uploads"
    if os.path.exists(upload_path):
        files = glob.glob(f"{upload_path}/**/*", recursive=True)
        files = [f for f in files if os.path.isfile(f)]
        print(f"[Storage] Uploaded files count: {len(files)}")
        if len(files) > 0:
            print(f"  First 5 files: {files[:5]}")
    else:
        print(f"[Storage] Upload path {upload_path} does not exist.")

if __name__ == "__main__":
    asyncio.run(check_garbage())
