import requests
import os
from pathlib import Path
from pymilvus import connections, utility

# 1. Fetch Active KB IDs
API_URL = "http://localhost:8000/api"
ACTIVE_KBS = []
try:
    res = requests.get(f"{API_URL}/knowledge-bases")
    if res.status_code == 200:
        ACTIVE_KBS = [kb["id"] for kb in res.json()]
    else:
        print("Failed to fetch active KBs")
        exit(1)
except Exception as e:
    print(f"Error fetching active KBs: {e}")
    exit(1)

print(f"Active KB IDs ({len(ACTIVE_KBS)}):")
for kbid in ACTIVE_KBS:
    print(f" - {kbid}")

ERROS_FOUND = False

# 2. Check Fuseki Orphan Datasets
try:
    print("\n[Checking Fuseki Orphans...]")
    FUSEKI_URL = "http://localhost:3030/$/datasets" # Adjust if needed
    auth = ('admin', 'admin')
    res = requests.get(FUSEKI_URL, auth=auth)
    if res.status_code == 200:
        datasets = res.json().get("datasets", [])
        orphans = []
        for ds in datasets:
            ds_name = ds["ds.name"].lstrip("/") # e.g. /kb_123 -> kb_123
            # Check if this dataset belongs to any active KB
            # Naming convention: kb_{uuid_replaced_-with_}
            is_valid = False
            for kbid in ACTIVE_KBS:
                expected_name = f"kb_{kbid.replace('-', '_')}"
                if ds_name == expected_name:
                    is_valid = True
                    break
            if not is_valid:
                orphans.append(ds_name)
        
        if orphans:
            print(f"[WARNING] Found {len(orphans)} orphan Fuseki datasets: {orphans}")
            ERROS_FOUND = True
        else:
            print("[OK] No orphan Fuseki datasets found.")
    else:
        print(f"[FAIL] Could not list Fuseki datasets: {res.status_code}")
except Exception as e:
    print(f"[FAIL] Fuseki check error: {e}")

# 3. Check Milvus Orphan Collections
try:
    print("\n[Checking Milvus Orphans...]")
    connections.connect(alias="default", host="localhost", port="19530")
    collections = utility.list_collections()
    orphans = []
    
    for col_name in collections:
        if not col_name.startswith("kb_"):
            continue # Ignore non-kb collections if any
            
        is_valid = False
        for kbid in ACTIVE_KBS:
            expected_name = f"kb_{kbid.replace('-', '_')}"
            if col_name == expected_name:
                is_valid = True
                break
        
        if not is_valid:
            orphans.append(col_name)
            
    if orphans:
        print(f"[WARNING] Found {len(orphans)} orphan Milvus collections: {orphans}")
        ERROS_FOUND = True
    else:
        print("[OK] No orphan Milvus collections found.")
except Exception as e:
    print(f"[FAIL] Milvus check error: {e}")

# 4. Check File System Orphans (doc2onto_out)
try:
    print("\n[Checking File System Orphans (doc2onto_out)...]")
    doc2onto_path = Path("backend/doc2onto_out") # From root
    if doc2onto_path.exists():
        subdirs = [x for x in doc2onto_path.iterdir() if x.is_dir()]
        orphans = []
        for d in subdirs:
            kb_id = d.name
            if kb_id not in ACTIVE_KBS:
                orphans.append(kb_id)
        
        if orphans:
            print(f"[WARNING] Found {len(orphans)} orphan directories in doc2onto_out: {orphans}")
            ERROS_FOUND = True
        else:
            print("[OK] No orphan directories in doc2onto_out.")
    else:
        print("[OK] doc2onto_out directory does not exist.")
except Exception as e:
    print(f"[FAIL] File system check error: {e}")


if not ERROS_FOUND:
    print("\n------------------------------------------------")
    print("✅  Deletion Verification Passed: No orphans found.")
    print("------------------------------------------------")
else:
    print("\n------------------------------------------------")
    print("❌  Deletion Verification Failed: Orphans detected.")
    print("------------------------------------------------")
