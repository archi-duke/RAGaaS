
import asyncio
import os
import sys

# Add backend directory to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.core.neo4j_client import neo4j_client

async def inspect_relations():
    entity_name = "성기훈"
    
    print(f"Inspecting Relations for: {entity_name}")
    print("-" * 50)

    try:
        # Check connections
        query = """
        MATCH (n:Entity {name: $name})-[r]-(m)
        RETURN type(r) as relType, m.name as connectedNode, properties(r) as relProps
        LIMIT 20
        """
        
        records = neo4j_client.execute_query(query, parameters={"name": entity_name})
        
        print(f"Found {len(records)} connections:")
        for record in records:
            print(f" - [{record.get('relType')}] -> {record.get('connectedNode')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_relations())
