from app.core.neo4j_client import neo4j_client

# KB ID for 'test n4'
KB_ID = "f47c0a51-e119-4f30-9a19-e4b2fd173010"

print(f"Inspecting Neo4j data for KB: {KB_ID}")

# 1. Check Node Properties
node_query = """
MATCH (n)
WHERE n.kb_id = $kb_id
RETURN labels(n) as labels, keys(n) as properties, n.name as name, n.id as id
LIMIT 5
"""
print("\n--- NODES ---")
try:
    results = neo4j_client.execute_query(node_query, {"kb_id": KB_ID})
    if not results:
        print("No nodes found for this KB.")
    for r in results:
        print(f"Labels: {r['labels']}")
        print(f"Properties keys: {r['properties']}")
        print(f"n.name: {r['name']}")
        print(f"n.id: {r['id']}")
        print("-" * 20)
except Exception as e:
    print(f"Error querying nodes: {e}")

# 2. Check Relationships
rel_query = """
MATCH (n)-[r]->(m)
WHERE n.kb_id = $kb_id
RETURN n.name as subj, type(r) as pred, m.name as obj, keys(r) as r_props
LIMIT 10
"""
print("\n--- RELATIONSHIPS ---")
try:
    results = neo4j_client.execute_query(rel_query, {"kb_id": KB_ID})
    if not results:
        print("No relationships found for this KB.")
    for r in results:
        print(f"({r['subj']}) -[:{r['pred']}]-> ({r['obj']})")
        print(f"Rel properties: {r['r_props']}")
except Exception as e:
    print(f"Error querying relationships: {e}")
