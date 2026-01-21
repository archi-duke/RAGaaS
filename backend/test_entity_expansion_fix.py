
import asyncio
import os
import sys

# Add backend directory to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.core.neo4j_client import neo4j_client

async def test_expansion_fix():
    kb_id = "298f7c64-5032-4f9e-930a-1e774c434759"
    entities = ["성기훈"]
    
    import re
    safe_entities = [re.escape(e) for e in entities]
    regex_pattern = "(?i).*(" + "|".join(safe_entities) + ").*"
    
    print(f"Testing Fix with Regex: {regex_pattern}")

    # Fix: Handle nulls in logic properly
    expand_query = """
    MATCH (n:Entity {kb_id: $kb_id})
    WHERE n.name =~ $regex_pattern OR coalesce(n.label_ko, '') =~ $regex_pattern
    MATCH (n)-[r]-(m)
    WHERE NOT (m.name IN $entities) AND NOT (coalesce(m.label_ko, '') IN $entities)
    RETURN DISTINCT coalesce(m.label_ko, m.name) AS relatedLabel
    LIMIT 50
    """
    
    try:
        records = neo4j_client.execute_query(expand_query, parameters={
            "entities": entities, 
            "regex_pattern": regex_pattern,
            "kb_id": kb_id
        })
        
        print(f"Found {len(records)} related entities:")
        for record in records:
            print(f" - {record.get('relatedLabel')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_expansion_fix())
