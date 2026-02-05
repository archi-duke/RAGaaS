
import sys
import os
import asyncio
import logging

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

# Setup logging
logging.basicConfig(level=logging.DEBUG)

from app.services.retrieval.graph_backends.fuseki import FusekiBackend
from app.core.config import settings

async def run_test():
    print("Initializing FusekiBackend...")
    backend = FusekiBackend()
    
    kb_id = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
    
    # Question: "성기훈의 스승의 스승은 누구야?"
    query_text = "성기훈의 스승의 스승은 누구야?"
    entities = ["성기훈"] # Helper entities
    
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
        print(f"SPARQL Query Used:\n{result.get('sparql_query')}")
        print(f"\nTriples Found: {len(result.get('triples', []))}")
        for t in result.get('triples', []):
            print(f" - {t['subject']} {t['predicate']} {t['object']}")
            
    except Exception as e:
        print(f"Error executing query: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_test())
