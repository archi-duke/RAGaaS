#!/usr/bin/env python3
"""
Milvus chunk_id와 Fuseki sourceNodeId 매칭 확인
"""
import httpx
from pymilvus import connections, Collection

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
doc_id = "46a6e074-6a53-4d75-80c0-49ed19d091ac"

# 1. Milvus 청크 ID 조회
print("=== Milvus Chunk IDs ===")
try:
    connections.connect(host="localhost", port="19530")
    collection_name = f"kb_{kb_id.replace('-', '_')}"
    collection = Collection(name=collection_name)
    collection.load()
    
    expr = f'doc_id == "{doc_id}"'
    chunks = collection.query(
        expr=expr,
        output_fields=["chunk_id", "doc_id"],
        limit=100
    )
    
    print(f"Found {len(chunks)} chunks in Milvus:")
    milvus_chunk_ids = set()
    for chunk in chunks[:10]:
        print(f"  - {chunk['chunk_id']}")
        milvus_chunk_ids.add(chunk['chunk_id'])
    if len(chunks) > 10:
        print(f"  ... and {len(chunks) - 10} more")
        
except Exception as e:
    print(f"Error: {e}")
    milvus_chunk_ids = set()

# 2. Fuseki sourceNodeId 조회
print("\n=== Fuseki sourceNodeId ===")
dataset_name = f"kb_{kb_id.replace('-', '_')}"
graph_uri = f"urn:doc:{doc_id}"

sparql = f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX meta: <http://rag.local/meta/>

SELECT DISTINCT ?sourceNodeId
FROM <{graph_uri}>
WHERE {{
    ?stmt rdf:type rdf:Statement .
    ?stmt meta:sourceNodeId ?sourceNodeId .
}}
LIMIT 20
"""

try:
    url = f"http://localhost:3030/{dataset_name}/query"
    response = httpx.post(
        url,
        data={"query": sparql},
        headers={"Accept": "application/sparql-results+json"},
        auth=("admin", "admin"),
        timeout=30.0
    )
    
    results = response.json()
    bindings = results.get("results", {}).get("bindings", [])
    
    print(f"Found {len(bindings)} unique sourceNodeIds in Fuseki:")
    fuseki_node_ids = set()
    for b in bindings[:10]:
        node_id = b["sourceNodeId"]["value"]
        print(f"  - {node_id}")
        fuseki_node_ids.add(node_id)
        
except Exception as e:
    print(f"Error: {e}")
    fuseki_node_ids = set()

# 3. 비교
print("\n=== Comparison ===")
matching = milvus_chunk_ids & fuseki_node_ids
print(f"Milvus chunk_ids: {len(milvus_chunk_ids)}")
print(f"Fuseki sourceNodeIds: {len(fuseki_node_ids)}")
print(f"Matching: {len(matching)}")

if matching:
    print(f"\nMatching IDs: {list(matching)[:5]}")
else:
    print("\n⚠️ NO MATCHING IDs!")
    print("\nSample Milvus format:", list(milvus_chunk_ids)[:2] if milvus_chunk_ids else "N/A")
    print("Sample Fuseki format:", list(fuseki_node_ids)[:2] if fuseki_node_ids else "N/A")
