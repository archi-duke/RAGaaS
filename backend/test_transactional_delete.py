import requests
import time
import sys
import asyncio
from sqlalchemy import create_engine, text

# BASE_URL = "http://localhost:8000/api/knowledge-bases"
# But script runs inside container? No, usually I run it via exec.
# Inside container:
BASE_URL = "http://localhost:8000/api/knowledge-bases"

def create_kb_and_doc():
    kb_name = f"TransTest_{int(time.time())}"
    print(f"Creating KB: {kb_name}")
    resp = requests.post(f"{BASE_URL}/", json={"name": kb_name, "description": "Trans Delete Test"})
    if resp.status_code != 200:
        print(f"Failed to create KB: {resp.text}")
        return None, None
    kb_id = resp.json()['id']
    
    files = {'file': ('test.txt', 'Transactional deletion test content.')}
    resp = requests.post(f"{BASE_URL}/{kb_id}/documents", files=files, json={})
    if resp.status_code != 200:
        print(f"Failed to upload doc: {resp.text}")
        return kb_id, None
    doc_id = resp.json()['id']
    
    # Wait for completion
    for _ in range(10):
        time.sleep(1)
        d = requests.get(f"{BASE_URL}/{kb_id}/documents").json()
        target = next((x for x in d if x['id'] == doc_id), None)
        if target and target['status'] == 'completed':
            return kb_id, doc_id
            
    return kb_id, doc_id

def test_api_deletion():
    print("\n--- Test 1: API Background Deletion ---")
    kb_id, doc_id = create_kb_and_doc()
    if not doc_id:
        return
        
    print(f"Deleting doc {doc_id}...")
    resp = requests.delete(f"{BASE_URL}/{kb_id}/documents/{doc_id}")
    print(f"Delete Response: {resp.status_code} {resp.json()}")
    
    # Verify status is DELETING
    d = requests.get(f"{BASE_URL}/{kb_id}/documents").json()
    target = next((x for x in d if x['id'] == doc_id), None)
    if target:
        print(f"Current Status: {target['status']}")
        if target['status'] != 'deleting':
            print("FAILURE: Status should be DELETING immediately after call")
    else:
        print("Document already gone? Fast deletion.")
        
    # Poll for disappearance
    print("Polling for disappearance...")
    for i in range(20):
        time.sleep(0.5)
        d = requests.get(f"{BASE_URL}/{kb_id}/documents").json()
        target = next((x for x in d if x['id'] == doc_id), None)
        if not target:
            print("SUCCESS: Document disappeared.")
            break
        if i == 19:
            print(f"FAILURE: Document still exists with status {target['status']}")

    # Cleanup KB
    requests.delete(f"{BASE_URL}/{kb_id}")

def test_crash_recovery():
    print("\n--- Test 2: Crash Recovery ---")
    kb_id, doc_id = create_kb_and_doc()
    if not doc_id:
        return

    # Simulate Crash: Manually update DB status to DELETING
    # We need to access DB content.
    # Since we are running INSIDE container, we can use app code or direct SQL.
    # Let's use direct SQL update via python script inside container.
    
    print(f"Simulating Crash: Manually setting {doc_id} to DELETING...")
    
    from app.core.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from sqlalchemy import update
    
    async def set_deleting():
        async with SessionLocal() as db:
            stmt = update(Document).where(Document.id == doc_id).values(status=DocumentStatus.DELETING.value)
            await db.execute(stmt)
            await db.commit()
            
    # We need to run this async function. 
    # But this script is synchronous/mixed. 
    # Let's just do a hacky run.
    loop = asyncio.new_event_loop()
    loop.run_until_complete(set_deleting())
    loop.close()
    
    print("DB Updated. Now RESTARTING backend container manually (External Step).")
    print("Run `docker restart ragaas-backend` now.")
    print("Then check logs for '[Recovery]'.")
    
    # In a real automated test we would trigger docker restart here, but we are inside the container or adjacent.
    # If this script runs via `docker exec`, we cannot restart the container from within easily unless we mount docket socket.
    # So we will verify Test 1 first, then I will run Test 2 steps manually via tool calls.

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "recovery_prep":
        test_crash_recovery()
    else:
        test_api_deletion()
