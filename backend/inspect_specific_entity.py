from app.core.neo4j_client import neo4j_client

KB_ID = "f47c0a51-e119-4f30-9a19-e4b2fd173010"
ENTITY_NAME = "성기훈"

print(f"Checking entity '{ENTITY_NAME}' in KB: {KB_ID}")

# 1. Check if node exists
query = """
MATCH (n:Entity {kb_id: $kb_id})
WHERE n.name CONTAINS $name
RETURN n.name as name, labels(n) as labels
"""
results = neo4j_client.execute_query(query, {"kb_id": KB_ID, "name": ENTITY_NAME})

if not results:
    print(f"❌ Entity '{ENTITY_NAME}' NOT found.")
    
    # Check what else is there
    print("\n--- Available Entities (Sample) ---")
    sample_query = "MATCH (n:Entity {kb_id: $kb_id}) RETURN n.name as name LIMIT 20"
    samples = neo4j_client.execute_query(sample_query, {"kb_id": KB_ID})
    for s in samples:
        print(s['name'])
else:
    print(f"✅ Found {len(results)} entities:")
    for r in results:
        print(f"- {r['name']}")
        
        # Check relationships
        print("  Relationships:")
        rel_q = """
        MATCH (n:Entity {name: $n_name, kb_id: $kb_id})-[r]-(m)
        RETURN type(r) as rel_type, m.name as target, r.is_inverse as is_inverse
        """
        rels = neo4j_client.execute_query(rel_q, {"kb_id": KB_ID, "n_name": r['name']})
        for rel in rels:
             dir_mark = "<-" if rel['is_inverse'] else "->"
             print(f"    -[:{rel['rel_type']}]- {rel['target']} (inverse={rel['is_inverse']})")

