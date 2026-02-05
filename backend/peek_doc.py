
import requests
import json

BASE_URL = "http://localhost:8000/api"
KB_ID = "0c0f4f26-f68a-479c-b76c-77a40eafc1aa"

def peek_doc():
    # List KBs
    resp = requests.get(f"{BASE_URL}/knowledge-bases")
    kbs = resp.json()
    
    for kb in kbs:
        kb_id = kb['id']
        print(f"Checking KB: {kb['name']} ({kb_id})")
        payload = {
            "query": "오영수", 
            "top_k": 3,
            "strategy": "keyword"
        }
        try:
            search_resp = requests.post(f"{BASE_URL}/knowledge-bases/{kb_id}/retrieve", json=payload)
            results = search_resp.json()
            if results:
                print(f"  FOUND {len(results)} results!")
                content = results[0].get('content')
                print(f"  Content length: {len(content)}")
                print(f"  Content preview: {content[:100]}...")
                print("  First result score:", results[0].get('score'))
                print("  First result l2_score:", results[0].get('l2_score'))
                return
        except:
            pass
    print("No results found in any KB.")

if __name__ == "__main__":
    peek_doc()
