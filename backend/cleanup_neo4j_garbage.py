"""
Neo4j Garbage Cleanup Script
Removes all orphaned Chunk and Entity nodes from Neo4j
"""
import os
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

def cleanup_neo4j():
    print(f"\n[Neo4j Cleanup] Connecting to {NEO4J_URI}...")
    driver = None
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        
        with driver.session() as session:
            # Check current state
            result = session.run("MATCH (n) RETURN count(n) as count")
            initial_count = result.single()["count"]
            print(f"  - Initial node count: {initial_count}")
            
            if initial_count == 0:
                print("  - ✅ Neo4j is already clean.")
                return
            
            # Show labels
            result = session.run("CALL db.labels() YIELD label RETURN label")
            labels = [record["label"] for record in result]
            print(f"  - Labels found: {labels}")
            
            # Step 1: Delete all relationships first
            result = session.run("""
                MATCH ()-[r]->()
                DELETE r
                RETURN count(r) as deleted
            """)
            rel_deleted = result.single()["deleted"]
            print(f"  - Deleted {rel_deleted} relationships")
            
            # Step 2: Delete all Chunk nodes
            result = session.run("""
                MATCH (c:Chunk)
                DELETE c
                RETURN count(c) as deleted
            """)
            chunk_deleted = result.single()["deleted"]
            print(f"  - Deleted {chunk_deleted} Chunk nodes")
            
            # Step 3: Delete all Entity nodes
            result = session.run("""
                MATCH (e:Entity)
                DELETE e
                RETURN count(e) as deleted
            """)
            entity_deleted = result.single()["deleted"]
            print(f"  - Deleted {entity_deleted} Entity nodes")
            
            # Step 4: Delete any remaining nodes (catch-all)
            result = session.run("""
                MATCH (n)
                DELETE n
                RETURN count(n) as deleted
            """)
            other_deleted = result.single()["deleted"]
            if other_deleted > 0:
                print(f"  - Deleted {other_deleted} other nodes")
            
            # Verify cleanup
            result = session.run("MATCH (n) RETURN count(n) as count")
            final_count = result.single()["count"]
            
            if final_count == 0:
                print(f"\n  - ✅ Neo4j cleanup complete! All {initial_count} nodes removed.")
            else:
                print(f"\n  - ⚠️  Warning: {final_count} nodes still remain.")
                
    except Exception as e:
        print(f"  - ❌ Failed to cleanup Neo4j: {e}")
    finally:
        if driver:
            driver.close()

if __name__ == "__main__":
    print("=== Neo4j Garbage Cleanup ===")
    cleanup_neo4j()
    print("\nCleanup complete.")
