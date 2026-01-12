import asyncio
import sys
import os
import requests
import json
import time

# Add path to import backend modules
sys.path.append('/app')

# Use requests to talk to the API running in the container (localhost:8000)
BASE_URL = "http://localhost:8000/api/knowledge-bases"


def test_cascading_deletion():
    print("--- Testing Cascading Deletion ---")
    
    # 1. Create a Test Knowledge Base
    kb_name = f"CascadeTest_{int(time.time())}"
    print(f"Creating KB: {kb_name}")
    resp = requests.post(f"{BASE_URL}/", json={
        "name": kb_name,
        "description": "Validation for Cascading Deletion",
        "chunking_strategy": "fixed",
        "chunking_config": {"chunk_size": 200, "chunk_overlap": 20},
        "enable_graph_rag": True,
        "graph_backend": "ontology"
    })
    if resp.status_code != 200:
        print(f"Failed to create KB: {resp.text}")
        return
    kb = resp.json()
    kb_id = kb['id']
    print(f"KB Created: {kb_id}")
    
    # 2. Upload a Document
    print("Uploading Document...")
    files = {'file': ('test_doc.txt', 'This is a test document. It should be deleted completely. 성기훈은 오일남의 제자이다.')}
    resp = requests.post(f"{BASE_URL}/{kb_id}/documents", files=files, json={})
    if resp.status_code != 200:
        print(f"Failed to upload document: {resp.text}")
        return
    doc = resp.json()
    doc_id = doc['id']
    print(f"Document Uploaded: {doc_id}")
    
    # 3. Wait for Processing
    print("Waiting for processing...")
    max_retries = 20
    processed = False
    for i in range(max_retries):
        time.sleep(2)
        resp = requests.get(f"{BASE_URL}/{kb_id}/documents")
        docs = resp.json()
        target_doc = next((d for d in docs if d['id'] == doc_id), None)
        if target_doc and target_doc['status'] == 'completed':
            print("Document processing completed.")
            processed = True
            break
        print(f"Status: {target_doc['status'] if target_doc else 'Unknown'}")
        
    if not processed:
        print("Document processing timed out.")
        return

    # 4. Verify Data Exists
    print("\n--- Verifying Data Existence ---")
    
    # Check Milvus chunks
    resp = requests.get(f"{BASE_URL}/{kb_id}/documents/{doc_id}/chunks")
    chunks = resp.json().get('chunks', [])
    print(f"Milvus Chunks: {len(chunks)} (Expected > 0)")
    for c in chunks:
        print(f" - Chunk ID: {c.get('chunk_id')}")

    
    # Check Fuseki Triples
    # Use internal client
    try:
        from app.core.fuseki import fuseki_client
        # Ensure dataset created (api does it, but just in case)
        query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }"
        result = fuseki_client.query_sparql(kb_id, query)
        count = result['results']['bindings'][0]['count']['value']
        print(f"Fuseki Triples: {count} (Expected > 0)")
        
        # DEBUG: Print triples
        debug_q = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 20"
        debug_res = fuseki_client.query_sparql(kb_id, debug_q)
        print("--- EXISTING TRIPLES ---")
        for b in debug_res['results']['bindings']:
            print(f"{b['s']['value']} {b['p']['value']} {b['o']['value']}")
        print("------------------------")

    except Exception as e:
        print(f"Fuseki Check Failed: {e}")
        
    if len(chunks) == 0:
        print("FAILURE: No chunks found. Cannot verify deletion.")
        return

    # 5. Delete Document
    print("\n--- Deleting Document ---")
    resp = requests.delete(f"{BASE_URL}/{kb_id}/documents/{doc_id}")
    if resp.status_code == 200:
        print("Delete API called successfully.")
    else:
        print(f"Delete API Failed: {resp.text}")
        return
        
    # 6. Verify Data Absence
    print("\n--- Verifying Data Absence ---")
    
    # Check Milvus Remaining Chunks
    try:
        from pymilvus import connections, Collection
        from app.core.config import settings
        connections.connect(host=settings.MILVUS_HOST, port='19530')
        col_name = f"kb_{kb_id.replace('-', '_')}"
        col = Collection(col_name)
        col.load()
        res = col.query(expr=f'doc_id == "{doc_id}"', output_fields=["chunk_id"])
        print(f"Milvus Remaining Chunks: {len(res)} (Expected 0)")
    except Exception as e:
        print(f"Milvus verification error: {e}")
        
    # Check Fuseki (Should be 0 if only this doc was there)
    try:
        result = fuseki_client.query_sparql(kb_id, query)
        count = result['results']['bindings'][0]['count']['value']
        print(f"Fuseki Remaining Triples: {count} (Expected 0)")
        
        if int(count) > 0:
            print("--- Attempting Manual DELETE Query matching document.py logic ---")
            # Reconstruct logic
            for c in chunks:
                cid = c.get('chunk_id')
                chunk_uri = f"http://rag.local/source/{cid}"
                delete_query = f"""
                PREFIX rel: <http://rag.local/relation/>
                DELETE {{
                    ?s ?p ?o .
                    ?inv_s ?inv_p ?s . 
                }}
                WHERE {{
                    ?s rel:hasSource <{chunk_uri}> .
                    ?s ?p ?o .
                    OPTIONAL {{ ?inv_s ?inv_p ?s }}
                }}
                """
                print(f"Executing manual DELETE for {cid}...")
                success = fuseki_client.update_sparql(kb_id, delete_query)
                print(f"Update Result: {success}")
            
            # Re-check
            result = fuseki_client.query_sparql(kb_id, query)
            new_count = result['results']['bindings'][0]['count']['value']
            print(f"Fuseki Triples after Manual Delete: {new_count}")

    except Exception as e:
        print(f"Fuseki verification error: {e}")



    # Cleanup KB
    requests.delete(f"{BASE_URL}/{kb_id}")
    print("Test KB deleted.")


if __name__ == "__main__":
    test_cascading_deletion()
