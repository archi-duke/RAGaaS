from neo4j import GraphDatabase
import os

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

def inspect_triple_sources():
    print(f"Conn: {NEO4J_URI}")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except Exception as e:
        print(f"Connection Failed: {e}")
        return

    query = """
    MATCH ()-[r]->()
    WHERE r.source_node_id IS NOT NULL
    RETURN r.source_node_id AS chunk_id, count(r) AS count
    ORDER BY count DESC
    LIMIT 20
    """
    
    with driver.session() as session:
        result = session.run(query)
        print("\n--- Triple Source Node ID Distribution ---")
        records = list(result)
        if not records:
            print("No relationships with source_node_id found.")
        
        unique_ids = set()
        for record in records:
            chunk_id = record["chunk_id"]
            count = record["count"]
            unique_ids.add(chunk_id)
            print(f"Chunk ID: {chunk_id} | Count: {count}")
            
        print(f"\nTotal Unique Chunk IDs found: {len(unique_ids)}")
        if len(unique_ids) == 1:
            print("🚨 CRITICAL: All triples are mapped to a SINGLE chunk ID!")
        else:
            print(f"✅ Triples are distributed across {len(unique_ids)} chunks.")

    driver.close()

if __name__ == "__main__":
    inspect_triple_sources()
