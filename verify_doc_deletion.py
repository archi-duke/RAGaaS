import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymilvus import connections, utility, Collection
from neo4j import GraphDatabase
import requests

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

async def check_doc_deletion(kb_id):
    print(f"--- Document Deletion Verification for KB: {kb_id} ---")
    
    # 1. MongoDB
    try:
        client = AsyncIOMotorClient("mongodb://root:example@localhost:27017")
        db = client.ragaas
        
        doc_count = await db.documents.count_documents({"kb_id": kb_id})
        mapping_count = await db.triple_chunk_mappings.count_documents({"kb_id": kb_id})
        print(f"[MongoDB] Documents remaining: {doc_count}")
        print(f"[MongoDB] Triple-Chunk Mappings remaining: {mapping_count}")
        
        if doc_count > 0:
            docs = await db.documents.find({"kb_id": kb_id}).to_list(None)
            for d in docs:
                print(f"  - Document: {d.get('filename')} (ID: {d.get('_id')})")
    except Exception as e:
        print(f"[MongoDB] Error: {e}")

    # 2. Milvus
    try:
        connections.connect(host="localhost", port="19530")
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        if utility.has_collection(collection_name):
            col = Collection(collection_name)
            col.flush()
            print(f"[Milvus] Collection exists. Num entities: {col.num_entities}")
        else:
            print(f"[Milvus] Collection is GONE.")
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
        dataset = f"kb_{kb_id.replace('-', '_')}"
        query = "SELECT (count(*) as ?count) WHERE { GRAPH ?g { ?s ?p ?o } }"
        response = requests.post(
            f"http://localhost:3030/{dataset}/query",
            data={"query": query},
            auth=("admin", "admin"),
            timeout=5
        )
        if response.status_code == 200:
            count = response.json()["results"]["bindings"][0]["count"]["value"]
            print(f"[Fuseki] Triples remaining in Named Graphs: {count}")
        else:
            print(f"[Fuseki] Dataset error or not found: {response.status_code}")
    except Exception as e:
        print(f"[Fuseki] Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_doc_deletion(KB_ID))
