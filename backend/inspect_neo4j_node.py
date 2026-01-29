
import asyncio
import os
import sys

# Add backend directory to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.core.neo4j_client import neo4j_client

async def inspect_node():
    entity_name = "성기훈"
    
    print(f"Inspecting Node: {entity_name}")
    print("-" * 50)

    try:
        # Check node existence and properties
        query = """
        MATCH (n:Entity)
        WHERE n.name CONTAINS $name OR n.label_ko CONTAINS $name
        RETURN n, labels(n) as labels
        LIMIT 5
        """
        
        records = neo4j_client.execute_query(query, parameters={"name": entity_name})
        
        if not records:
            print("No node found matching the name.")
        
        for record in records:
            node = record.get("n")
            labels = record.get("labels")
            props = dict(node)
            print(f"Node Found: {props.get('name')}")
            print(f"Labels: {labels}")
            print(f"Properties: {props}")
            print("-" * 30)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_node())
