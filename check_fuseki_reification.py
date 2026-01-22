#!/usr/bin/env python3
"""
Fuseki Reification 데이터 확인
"""
import httpx

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
doc_id = "46a6e074-6a53-4d75-80c0-49ed19d091ac"

dataset_name = f"kb_{kb_id.replace('-', '_')}"
graph_uri = f"urn:doc:{doc_id}"

# Reification 조회
sparql = f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX meta: <http://rag.local/meta/>

SELECT ?stmt ?s ?p ?o ?sourceNodeId
FROM <{graph_uri}>
WHERE {{
    ?stmt rdf:type rdf:Statement .
    ?stmt rdf:subject ?s .
    ?stmt rdf:predicate ?p .
    ?stmt rdf:object ?o .
    OPTIONAL {{ ?stmt meta:sourceNodeId ?sourceNodeId }}
}}
LIMIT 10
"""

print(f"Dataset: {dataset_name}")
print(f"Graph: {graph_uri}")
print(f"\nSPARQL Query:\n{sparql}\n")

url = f"http://localhost:3030/{dataset_name}/query"

try:
    response = httpx.post(
        url,
        data={"query": sparql},
        headers={"Accept": "application/sparql-results+json"},
        auth=("admin", "admin"),
        timeout=30.0
    )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        results = response.json()
        bindings = results.get("results", {}).get("bindings", [])
        print(f"Found {len(bindings)} reification statements\n")
        
        for i, b in enumerate(bindings[:5]):
            print(f"Statement {i+1}:")
            print(f"  stmt: {b.get('stmt', {}).get('value', 'N/A')}")
            print(f"  s: {b.get('s', {}).get('value', 'N/A')}")
            print(f"  p: {b.get('p', {}).get('value', 'N/A')}")
            print(f"  o: {b.get('o', {}).get('value', 'N/A')}")
            print(f"  sourceNodeId: {b.get('sourceNodeId', {}).get('value', 'N/A')}")
            print()
    else:
        print(f"Error: {response.text}")
        
except Exception as e:
    print(f"Exception: {e}")
