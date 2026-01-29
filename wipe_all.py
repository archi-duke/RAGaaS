import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymilvus import connections, utility
from neo4j import GraphDatabase
import requests
import os
import shutil

async def wipe_everything():
    print("--- Starting Complete Wipe ---")
    
    # 1. MongoDB
    try:
        client = AsyncIOMotorClient("mongodb://root:example@localhost:27017")
        db = client.ragaas
        await db.knowledge_bases.delete_many({})
        await db.documents.delete_many({})
        await db.triple_chunk_mappings.delete_many({})
        print("✅ MongoDB: All collections cleared.")
    except Exception as e:
        print(f"❌ MongoDB Error: {e}")

    # 2. Milvus
    try:
        connections.connect(host="localhost", port="19530")
        for col in utility.list_collections():
            utility.drop_collection(col)
        print("✅ Milvus: All collections dropped.")
    except Exception as e:
        print(f"❌ Milvus Error: {e}")

    # 3. Neo4j
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        driver.close()
        print("✅ Neo4j: All nodes and relationships deleted.")
    except Exception as e:
        print(f"❌ Neo4j Error: {e}")

    # 4. Fuseki
    try:
        response = requests.get("http://localhost:3030/$/datasets", auth=("admin", "admin"))
        if response.status_code == 200:
            datasets = response.json().get("datasets", [])
            for ds in datasets:
                name = ds["ds.name"].lstrip("/")
                del_resp = requests.delete(f"http://localhost:3030/$/datasets/{name}", auth=("admin", "admin"))
                if del_resp.status_code == 200:
                    print(f"✅ Fuseki: Dataset '{name}' deleted.")
                else:
                    print(f"❌ Fuseki: Failed to delete '{name}' ({del_resp.status_code})")
        else:
            print(f"❌ Fuseki Error fetching datasets: {response.status_code}")
    except Exception as e:
        print(f"❌ Fuseki Error: {e}")

    # 5. Shared Storage
    upload_path = "./data/uploads"
    try:
        if os.path.exists(upload_path):
            shutil.rmtree(upload_path)
            os.makedirs(upload_path)
            print("✅ Storage: Uploaded files cleared.")
    except Exception as e:
        print(f"❌ Storage Error: {e}")

if __name__ == "__main__":
    asyncio.run(wipe_everything())
