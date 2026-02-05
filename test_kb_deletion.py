import requests
import time
import os

API_URL = "http://localhost:8000/api"
KB_NAME = "Deletion Test KB"
KB_DESCRIPTION = "Temporary KB for deletion test"

def create_kb():
    print(f"Creating KB '{KB_NAME}'...")
    payload = {
        "name": KB_NAME,
        "description": KB_DESCRIPTION,
        "chunking_strategy": "size",
        "chunking_config": {"chunk_size": 500, "overlap": 50},
        "graph_backend": "fuseki" # Using Fuseki for test
    }
    res = requests.post(f"{API_URL}/knowledge-base", json=payload)
    if res.status_code == 200:
        kb_id = res.json()["id"]
        print(f"KB Created: {kb_id}")
        return kb_id
    else:
        print(f"Failed to create KB: {res.text}")
        return None

def upload_document(kb_id):
    print(f"Uploading dummy document to KB {kb_id}...")
    dummy_file_path = "deletion_test_doc.txt"
    with open(dummy_file_path, "w") as f:
        f.write("This is a test document for deletion verification.\nIt contains some text to be chunked and indexed.")
    
    with open(dummy_file_path, "rb") as f:
        files = {"file": f}
        # Assuming minimal graph params for speed
        params = {"oe_section_aware": False, "extract_inverse_relations": False} 
        res = requests.post(f"{API_URL}/ingestion/{kb_id}/documents", files=files, data=params)
    
    os.remove(dummy_file_path)
    
    if res.status_code == 200:
        doc_id = res.json()["id"]
        print(f"Document Uploaded: {doc_id}")
        return doc_id
    else:
        print(f"Failed to upload document: {res.text}")
        return None

def check_kb_exists(kb_id):
    res = requests.get(f"{API_URL}/retrieval/knowledge-bases")
    if res.status_code == 200:
        kbs = res.json()
        found = any(kb["id"] == kb_id for kb in kbs)
        return found
    return False

def delete_kb(kb_id):
    print(f"Deleting KB {kb_id}...")
    res = requests.delete(f"{API_URL}/knowledge-base/{kb_id}")
    if res.status_code == 200:
        print("Delete request successful.")
        return True
    else:
        print(f"Delete failed: {res.text}")
        return False

def verify_full_deletion(kb_id, doc_id):
    print("\n--- Verifying Deletion ---")
    
    # 1. API Check
    exists_api = check_kb_exists(kb_id)
    print(f"1. API (KB List): {'CLEARED' if not exists_api else 'FAILED (Still exists)'}")

    # For deeper verification, we might need direct DB connection or check via other endpoints
    # Here we simulate deeper checks by trying to access resources
    
    # 2. Check Document (This endpoint might return 404 if KB is gone, which is good)
    # But usually document endpoints are nested under KB or standalone. 
    # Let's try to search in that KB (should fail)
    res_search = requests.post(f"{API_URL}/retrieval/{kb_id}/search", json={"query": "test", "top_k": 1})
    if res_search.status_code == 404:
        print(f"2. Retrieval/Search: CLEARED (404 Not Found)")
    else:
        print(f"2. Retrieval/Search: FAILED (Status: {res_search.status_code})")

    # 3. Fuseki Check (Optional if you have internal access, here we just assume API reflects backend state)
    # You can add logic to query Fuseki/Milvus directly if libraries are available in this env.
    
    if not exists_api and res_search.status_code == 404:
        return True
    return False

if __name__ == "__main__":
    kb_id = create_kb()
    if kb_id:
        doc_id = upload_document(kb_id)
        if doc_id:
            print("Waiting for ingestion (5s)...")
            time.sleep(5) 
            
            if delete_kb(kb_id):
                print("Waiting for deletion cleanup (3s)...")
                time.sleep(3)
                if verify_full_deletion(kb_id, doc_id):
                    print("\n[SUCCESS] KB and related data appear to be deleted.")
                else:
                    print("\n[WARNING] Deletion verification failed.")
