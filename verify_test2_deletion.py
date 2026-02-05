import requests
from pathlib import Path
from pymilvus import connections, utility

KB_ID = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
KB_NAME = "test2"
COLLECTION_NAME = f"kb_{KB_ID.replace('-', '_')}"

print(f"=== Deletion Verification for '{KB_NAME}' ===")
print(f"KB ID: {KB_ID}")
print(f"Expected Milvus Collection: {COLLECTION_NAME}")
print()

issues = []

# 1. KB List Check
print("[1] Checking KB List...")
try:
    res = requests.get("http://localhost:8000/api/knowledge-bases")
    if res.status_code == 200:
        kbs = res.json()
        found = any(kb["id"] == KB_ID for kb in kbs)
        if found:
            print("  ❌ FAIL: KB still exists in database!")
            issues.append("KB record")
        else:
            print("  ✅ OK: KB removed from database")
except Exception as e:
    print(f"  ⚠️ ERROR: {e}")

# 2. Milvus Check
print("[2] Checking Milvus...")
try:
    connections.connect("default", host="localhost", port="19530")
    if utility.has_collection(COLLECTION_NAME):
        print(f"  ❌ FAIL: Milvus collection '{COLLECTION_NAME}' still exists!")
        issues.append("Milvus collection")
    else:
        print("  ✅ OK: Milvus collection deleted")
except Exception as e:
    print(f"  ⚠️ ERROR: {e}")

# 3. Fuseki Check
print("[3] Checking Fuseki...")
try:
    FUSEKI_URL = "http://localhost:3030"
    dataset_name = f"kb_{KB_ID.replace('-', '_')}"
    res = requests.get(f"{FUSEKI_URL}/$/datasets/{dataset_name}", auth=("admin", "admin"), timeout=5)
    if res.status_code == 200:
        print(f"  ❌ FAIL: Fuseki dataset '{dataset_name}' still exists!")
        issues.append("Fuseki dataset")
    elif res.status_code == 404:
        print("  ✅ OK: Fuseki dataset deleted")
    else:
        print(f"  ⚠️ WARN: Unexpected status {res.status_code}")
except Exception as e:
    print(f"  ⚠️ ERROR: {e}")

# 4. File System Check
print("[4] Checking doc2onto_out...")
doc2onto_dir = Path(f"backend/doc2onto_out/{KB_ID}")
if doc2onto_dir.exists():
    print(f"  ❌ FAIL: Directory '{doc2onto_dir}' still exists!")
    issues.append("doc2onto_out directory")
else:
    print("  ✅ OK: doc2onto_out directory deleted")

# Summary
print()
print("=" * 50)
if not issues:
    print("✅  PASSED: All data for test2 has been cleanly deleted!")
else:
    print(f"❌  FAILED: Orphan data found in: {', '.join(issues)}")
print("=" * 50)
