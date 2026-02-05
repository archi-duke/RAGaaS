"""
남아있는 고아 데이터 수동 정리
"""
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.core.fuseki import fuseki_client

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
orphan_graph = "urn:doc:manual_0dcbcb8e-be12-4050-ae24-f7520d1441fe"

print(f"Cleaning graph: {orphan_graph}")
success = fuseki_client.drop_graph(kb_id, orphan_graph)

if success:
    print("✓ Successfully dropped orphan graph.")
else:
    print("❌ Failed to drop orphan graph.")

# 전체 다시 확인
print("\nFinal Check:")
count_query = "SELECT (COUNT(*) as ?count) FROM <urn:x-arq:UnionGraph> WHERE { ?s ?p ?o }"
results = fuseki_client.query_sparql(kb_id, count_query)
count = results.get("results", {}).get("bindings", [{}])[0].get("count", {}).get("value", "0")
print(f"Total remaining triples: {count}")
