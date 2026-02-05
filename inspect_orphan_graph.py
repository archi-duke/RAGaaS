"""
고아 그래프의 메타데이터 확인
"""
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.core.fuseki import fuseki_client

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
graph_uri = "urn:doc:manual_0dcbcb8e-be12-4050-ae24-f7520d1441fe"

query = f"""
SELECT ?s ?p ?o
FROM <{graph_uri}>
WHERE {{
  ?s ?p ?o .
}}
LIMIT 20
"""

results = fuseki_client.query_sparql(kb_id, query)
bindings = results.get("results", {}).get("bindings", [])

print(f"Graph: {graph_uri}")
for b in bindings:
    s = b.get("s", {}).get("value")
    p = b.get("p", {}).get("value")
    o = b.get("o", {}).get("value")
    print(f"  {s} {p} {o}")
