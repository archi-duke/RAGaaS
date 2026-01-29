"""
Fuseki 전체에서 "후배" 관계 검색
"""
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.core.fuseki import fuseki_client

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

# UnionGraph에서 "후배" 관계 검색
query1 = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel
FROM <urn:x-arq:UnionGraph>
WHERE {
  ?s ?p ?o .
  ?s rdfs:label ?sLabel .
  ?o rdfs:label ?oLabel .
  FILTER(CONTAINS(STR(?p), "후배"))
}
"""

print("=" * 80)
print("[1] UnionGraph에서 '후배' Predicate 검색")
print("=" * 80)

results1 = fuseki_client.query_sparql(kb_id, query1)
bindings1 = results1.get("results", {}).get("bindings", [])

if bindings1:
    print(f"\n발견: {len(bindings1)}개\n")
    for b in bindings1:
        s = b.get("sLabel", {}).get("value", "?")
        p = b.get("p", {}).get("value", "?")
        o = b.get("oLabel", {}).get("value", "?")
        print(f"  {s} --[{p}]--> {o}")
else:
    print("\n❌ '후배' Predicate를 찾을 수 없습니다.")

# 조상우 관련 모든 Predicate 조회
query2 = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?p ?o ?oLabel
FROM <urn:x-arq:UnionGraph>
WHERE {
  ?s rdfs:label "조상우" .
  ?s ?p ?o .
  OPTIONAL { ?o rdfs:label ?oLabel }
  FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
  FILTER(?p != <http://www.w3.org/2000/01/rdf-schema#label>)
}
"""

print("\n" + "=" * 80)
print("[2] 조상우의 모든 Outgoing 관계")
print("=" * 80)

results2 = fuseki_client.query_sparql(kb_id, query2)
bindings2 = results2.get("results", {}).get("bindings", [])

print(f"\n발견: {len(bindings2)}개\n")
for b in bindings2:
    p = b.get("p", {}).get("value", "?")
    o_label = b.get("oLabel", {}).get("value", b.get("o", {}).get("value", "?"))
    p_short = p.split("/")[-1] if "/" in p else p
    print(f"  조상우 --[{p_short}]--> {o_label}")
