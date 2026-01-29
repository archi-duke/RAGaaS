from app.core.neo4j_client import neo4j_client
import json

kb_id = "298f7c64-5032-4f9e-930a-1e774c434759"
print(f"Cleaning check for KB: {kb_id}")

try:
    # 1. Total entities for this KB
    res = neo4j_client.execute_query("MATCH (n:Entity) WHERE n.kb_id = $kb_id RETURN count(n) as count", {"kb_id": kb_id})
    print(f"Entities: {res[0]['count']}")

    # 2. Relationship types
    res = neo4j_client.execute_query("MATCH (n:Entity)-[r]->() WHERE n.kb_id = $kb_id RETURN DISTINCT r.type as type", {"kb_id": kb_id})
    print(f"Rel Types: {[r['type'] for r in res]}")

    # 3. Noisy nodes for THIS KB
    res = neo4j_client.execute_query(
        "MATCH (n) WHERE n.kb_id = $kb_id AND (n.name IN ['Domain', 'Relation', 'Unknown'] OR labels(n) = []) RETURN n.name as name, labels(n) as labels, count(*) as count",
        {"kb_id": kb_id}
    )
    print(f"Noisy nodes in KB: {res}")

    # 4. Orphaned nodes globally (no kb_id)
    res = neo4j_client.execute_query("MATCH (n) WHERE n.kb_id IS NULL RETURN count(n) as count")
    print(f"Nodes without kb_id: {res[0]['count']}")

    # 5. Untyped relationships globally
    res = neo4j_client.execute_query("MATCH ()-[r]->() WHERE r.type IS NULL RETURN count(r) as count")
    print(f"Untyped rels: {res[0]['count']}")


except Exception as e:
    print(f"Error: {e}")
