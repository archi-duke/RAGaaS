import requests
import sys

API_URL = "http://localhost:8000/api"

def check_status():
    print("Checking backend status...")
    try:
        # 1. Root Check
        res = requests.get("http://localhost:8000/")
        if res.status_code == 200:
            print("[OK] Backend is reachable.")
        else:
            print(f"[FAIL] Backend root returned {res.status_code}")
    except Exception as e:
        print(f"[CRITICAL] Could not connect to backend: {e}")
        return

    try:
        # 2. List KBs
        res = requests.get(f"{API_URL}/knowledge-bases")
        if res.status_code == 200:
            kbs = res.json()
            print(f"[OK] KB retrieval successful. Found {len(kbs)} KBs.")
            for kb in kbs:
                print(f" - {kb['name']} (ID: {kb['id']})")
        else:
            print(f"[FAIL] Failed to list KBs: {res.status_code} {res.text}")

    except Exception as e:
        print(f"[CRITICAL] Error checking KBs: {e}")

if __name__ == "__main__":
    check_status()
