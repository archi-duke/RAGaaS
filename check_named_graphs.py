"""
Fuseki에 존재하는 모든 Named Graph 확인
"""
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.core.fuseki import fuseki_client

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

# 모든 Named Graph 조회
query = """
SELECT DISTINCT ?g
WHERE {
  GRAPH ?g { ?s ?p ?o }
}
ORDER BY ?g
"""

print("=" * 80)
print("Fuseki에 존재하는 Named Graph 목록")
print("=" * 80)

results = fuseki_client.query_sparql(kb_id, query)
bindings = results.get("results", {}).get("bindings", [])

print(f"\n총 {len(bindings)}개의 Named Graph 발견:\n")

for b in bindings:
    graph_uri = b.get("g", {}).get("value", "?")
    print(f"  - {graph_uri}")

# 각 Graph에서 조상우-성기훈 관계 확인
print("\n" + "=" * 80)
print("각 Graph별 조상우-성기훈 관계 확인")
print("=" * 80)

for b in bindings:
    graph_uri = b.get("g", {}).get("value", "?")
    
    relation_query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?p
    FROM <{graph_uri}>
    WHERE {{
      {{
        ?s rdfs:label "조상우" .
        ?s ?p ?o .
        ?o rdfs:label "성기훈" .
      }}
      UNION
      {{
        ?s rdfs:label "성기훈" .
        ?s ?p ?o .
        ?o rdfs:label "조상우" .
      }}
      FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
    }}
    """
    
    rel_results = fuseki_client.query_sparql(kb_id, relation_query)
    rel_bindings = rel_results.get("results", {}).get("bindings", [])
    
    if rel_bindings:
        print(f"\n[{graph_uri}]")
        for rb in rel_bindings:
            p = rb.get("p", {}).get("value", "?")
            p_short = p.split("/")[-1] if "/" in p else p
            print(f"  - {p_short}")
