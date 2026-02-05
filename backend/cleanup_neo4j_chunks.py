"""
Neo4j Chunk 노드 및 MENTIONED_IN 관계 정리 스크립트
"""
from app.core.neo4j_client import neo4j_client

def cleanup_neo4j_chunks():
    print("Cleaning up Chunk nodes and MENTIONED_IN relationships from Neo4j...")
    
    try:
        # 1. MENTIONED_IN 관계 개수 확인
        count_result = neo4j_client.execute_query(
            "MATCH ()-[r:MENTIONED_IN]->() RETURN count(r) as count"
        )
        rel_count = count_result[0]["count"] if count_result else 0
        print(f"Found {rel_count} MENTIONED_IN relationships")
        
        # 2. Chunk 노드 개수 확인
        chunk_result = neo4j_client.execute_query(
            "MATCH (c:Chunk) RETURN count(c) as count"
        )
        chunk_count = chunk_result[0]["count"] if chunk_result else 0
        print(f"Found {chunk_count} Chunk nodes")
        
        if rel_count == 0 and chunk_count == 0:
            print("Nothing to clean up. Neo4j is already in pure graph state.")
            return
        
        # 3. MENTIONED_IN 관계 삭제
        if rel_count > 0:
            neo4j_client.execute_query(
                "MATCH ()-[r:MENTIONED_IN]->() DELETE r"
            )
            print(f"Deleted {rel_count} MENTIONED_IN relationships")
        
        # 4. Chunk 노드 삭제
        if chunk_count > 0:
            neo4j_client.execute_query(
                "MATCH (c:Chunk) DETACH DELETE c"
            )
            print(f"Deleted {chunk_count} Chunk nodes")
        
        print("Cleanup complete! Neo4j now contains only Entity-Relation pure graph.")
        
    except Exception as e:
        print(f"Error during cleanup: {e}")
        raise

if __name__ == "__main__":
    cleanup_neo4j_chunks()
