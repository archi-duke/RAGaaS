
import sys
import os
import asyncio
import logging

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

# Setup logging
logging.basicConfig(level=logging.DEBUG)

from app.services.retrieval.graph_backends.neo4j import Neo4jBackend
from app.core.config import settings

async def run_test():
    print("Initializing Neo4jBackend...")
    backend = Neo4jBackend()
    
    # KB ID for 'test' (Neo4j backend)
    kb_id = "298f7c64-5032-4f9e-930a-1e774c434759"
    
    # Question: "성기훈의 스승의 스승은 누구야?"
    query_text = "성기훈의 스승의 스승은 누구야?"
    entities = ["성기훈"] # Helper entities from NER
    
    print(f"\n--- Testing Query: {query_text} ---")
    print(f"KB UUID: {kb_id}")
    
    try:
        result = await backend.query(
            kb_id=kb_id,
            entities=entities,
            hops=2,
            query_type="relation",
            relationship_keywords=["master", "teacher", "스승"],
            query_text=query_text
        )
        
        print("\n--- Result ---")
        print(f"Cypher Query Used:\n{result.get('sparql_query')}") # Key is 'sparql_query' for compatibility
        print(f"Generated Thought: {result.get('thought')}")
        
        print(f"\nChunks Found: {len(result.get('chunk_ids', []))}")
        print(f"Triples Found: {len(result.get('triples', []))}")
        for t in result.get('triples', []):
            print(f" - {t['subject']} {t['predicate']} {t['object']}")
            
    except Exception as e:
        print(f"Error executing query: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_test())
