"""
'장풍' 관련 트리플 데이터 상세 조회
"""
import sys
import os
import json

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.core.fuseki import fuseki_client

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

# Object나 Subject에 '장풍'이 포함된 모든 트리플 조회 (URI, 리터럴 포함)
query = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?p ?o
FROM <urn:x-arq:UnionGraph>
WHERE {
  { ?s ?p ?o . FILTER(contains(str(?o), "장풍")) }
  UNION
  { ?s ?p ?o . FILTER(contains(str(?s), "장풍")) }
}
LIMIT 50
"""

results = fuseki_client.query_sparql(kb_id, query)
bindings = results.get("results", {}).get("bindings", [])

print(f"Total found: {len(bindings)}")
for b in bindings:
    s = b.get("s", {}).get("value")
    p = b.get("p", {}).get("value")
    o = b.get("o", {}).get("value")
    o_type = b.get("o", {}).get("type")
    
    print(f"S: {s}")
    print(f"P: {p}")
    print(f"O: {o} ({o_type})")
    print("-" * 40)
