import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymilvus import connections, utility, Collection
from neo4j import GraphDatabase

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

async def verify_ingestion(kb_id):
    print(f"--- Ingestion Verification for KB: {kb_id} ---")
    
    # 1. MongoDB - Documents & Status
    try:
        client = AsyncIOMotorClient("mongodb://root:example@localhost:27017")
        db = client.ragaas
        
        kb = await db.knowledge_bases.find_one({"_id": kb_id})
        print(f"[MongoDB] KB Name: {kb.get('name')} (Backend: {kb.get('graph_backend')})")
        
        docs = await db.documents.find({"kb_id": kb_id}).to_list(None)
        print(f"[MongoDB] Found {len(docs)} documents:")
        for d in docs:
            print(f"  - {d.get('filename')}: Status={d.get('status')}, ID={d.get('_id')}")
            
        mapping_count = await db.triple_chunk_mappings.count_documents({"kb_id": kb_id})
        print(f"[MongoDB] Triple-Chunk Mappings: {mapping_count}")
    except Exception as e:
        print(f"[MongoDB] Error: {e}")

    # 2. Milvus - Vector Chunks
    try:
        connections.connect(host="localhost", port="19530")
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        if utility.has_collection(collection_name):
            col = Collection(collection_name)
            col.flush()
            print(f"[Milvus] Collection {collection_name} exists. Entity count: {col.num_entities}")
        else:
            print(f"[Milvus] Collection {collection_name} DOES NOT exist.")
    except Exception as e:
        print(f"[Milvus] Error: {e}")

    # 3. Neo4j - Graph Data
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        with driver.session() as session:
            node_count = session.run("MATCH (n {kb_id: $kb_id}) RETURN count(n) as count", {"kb_id": kb_id}).single()["count"]
            rel_count = session.run("MATCH ()-[r {kb_id: $kb_id}]->() RETURN count(r) as count", {"kb_id": kb_id}).single()["count"]
            
            # Check for cleaned names (no numbering)
            example_nodes = session.run("MATCH (n:Entity {kb_id: $kb_id}) RETURN n.name as name LIMIT 5", {"kb_id": kb_id}).data()
            print(f"[Neo4j] Nodes: {node_count}, Relationships: {rel_count}")
            if example_nodes:
                print(f"  Example node names: {[n['name'] for n in example_nodes]}")
                
            # Check for inferred relationships
            inferred_count = session.run("MATCH ()-[r {kb_id: $kb_id, inferred: true}]->() RETURN count(r) as count", {"kb_id": kb_id}).single()["count"]
            print(f"  Inferred relationships: {inferred_count}")
        driver.close()
    except Exception as e:
        print(f"[Neo4j] Error: {e}")

if __name__ == "__main__":
    asyncio.run(verify_ingestion(KB_ID))
