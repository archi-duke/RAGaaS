
import asyncio
import sys
import os
import json

sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.api.graph_viewer import expand_graph
from app.core.config import settings

async def main():
    entity = "Duke"
    kb_id = "298f7c64-5032-4f9e-930a-1e774c434759" 
    
    print(f"Expanding graph for: {entity} (KB: {kb_id})")
    
    try:
        # Simulate the API call
        # Since expand_graph uses global clients, we don't need to pass them
        # BUT we need to make sure the KB_ID matches what the user used.
        # If user just wiped and re-ingested, they likely have a new KB ID or reused one.
        # We'll try to find *any* node with name="성기훈" first to get its KB ID if possible, 
        # or just run it and see if Neo4j finds it (Neo4j usually shares data unless multi-tenant strict)
        
        result = await expand_graph(kb_id=kb_id, entity=entity, backend="neo4j")
        
        print(f"\nNodes found: {len(result.nodes)}")
        print(f"Links found: {len(result.links)}")
        
        found_unknown = False
        for node in result.nodes:
            print(f"Node: ID={node.id}, Label={node.label}, Group={node.group}")
            if node.label == "Unknown" or node.id == "Unknown":
                print("!!! FOUND UNKNOWN NODE !!!")
                found_unknown = True
                
        if not found_unknown:
            print("\n✅ Verification Passed: No 'Unknown' nodes found.")
        else:
            print("\n❌ Verification Failed: 'Unknown' nodes still present.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
