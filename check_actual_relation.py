"""
Fuseki DB에 실제로 저장된 조상우-성기훈 관계 확인
"""
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.core.fuseki import fuseki_client

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

# 조상우와 성기훈 사이의 모든 관계 조회
query = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?s ?p ?o ?sLabel ?pLabel ?oLabel
FROM <urn:x-arq:UnionGraph>
WHERE {
  {
    ?s rdfs:label "조상우" .
    ?s ?p ?o .
    ?o rdfs:label "성기훈" .
  }
  UNION
  {
    ?s rdfs:label "성기훈" .
    ?s ?p ?o .
    ?o rdfs:label "조상우" .
  }
  ?s rdfs:label ?sLabel .
  ?o rdfs:label ?oLabel .
  OPTIONAL { ?p rdfs:label ?pLabel }
  FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
}
"""

print("=" * 80)
print("Fuseki DB 직접 조회: 조상우 <-> 성기훈 관계")
print("=" * 80)

results = fuseki_client.query_sparql(kb_id, query)
bindings = results.get("results", {}).get("bindings", [])

print(f"\n발견된 관계: {len(bindings)}개\n")

for b in bindings:
    s = b.get("sLabel", {}).get("value", "?")
    p = b.get("p", {}).get("value", "?")
    o = b.get("oLabel", {}).get("value", "?")
    
    # Predicate를 short form으로 변환
    if "/" in p:
        p_short = p.split("/")[-1]
    else:
        p_short = p
    
    print(f"  {s} --[{p_short}]--> {o}")
    print(f"    (Full URI: {p})")
