
import asyncio
import os
import sys

# Add backend directory to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.core.neo4j_client import neo4j_client

async def test_expansion():
    kb_id = "298f7c64-5032-4f9e-930a-1e774c434759"
    entities = ["성기훈"]
    
    print(f"Testing Entity Expansion for: {entities}")
    print(f"Target KB: {kb_id}")
    print("-" * 50)

    # Logic from GraphRetrievalStrategy._expand_entities (Neo4j part)
    try:
        # Regex pattern construction (same as in graph.py)
        import re
        safe_entities = [re.escape(e) for e in entities]
        regex_pattern = "(?i).*(" + "|".join(safe_entities) + ").*"
        
        print(f"Regex Pattern: {regex_pattern}")

        expand_query = """
        MATCH (n:Entity {kb_id: $kb_id})
        WHERE n.name =~ $regex_pattern OR n.label_ko =~ $regex_pattern
        MATCH (n)-[r]-(m)
        WHERE NOT (m.name IN $entities OR m.label_ko IN $entities)
        RETURN DISTINCT coalesce(m.label_ko, m.name) AS relatedLabel, type(r) as relType
        LIMIT 50
        """
        
        print(f"Executing Cypher Query...")
        records = neo4j_client.execute_query(expand_query, parameters={
            "entities": entities, 
            "regex_pattern": regex_pattern,
            "kb_id": kb_id
        })
        
        print(f"Found {len(records)} related entities:")
        for record in records:
            label = record.get("relatedLabel")
            rel_type = record.get("relType")
            print(f" - {label} (via {rel_type})")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_expansion())
