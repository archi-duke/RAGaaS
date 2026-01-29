#!/usr/bin/env python3
"""
Cleanup orphaned Milvus data for test jf KB
"""
from pymilvus import connections, Collection, utility

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
collection_name = f"kb_{KB_ID.replace('-', '_')}"

print(f"Connecting to Milvus...")
connections.connect("default", host="localhost", port="19530")

if not utility.has_collection(collection_name):
    print(f"Collection '{collection_name}' does not exist. Nothing to clean.")
    exit(0)

collection = Collection(collection_name)
collection.load()

# Get all entities
print(f"Checking collection...")
total_before = collection.num_entities
print(f"Total entities before cleanup: {total_before}")

# Query all to see what's there
try:
    all_docs = collection.query(
        expr="doc_id != ''",
        output_fields=["doc_id", "chunk_id"],
        limit=100
    )
    doc_ids = set(item['doc_id'] for item in all_docs)
    print(f"Found doc_ids: {doc_ids}")
    
    # Check if these docs exist in MongoDB
    from pymongo import MongoClient
    mongo_client = MongoClient("mongodb://root:example@localhost:27017")
    db = mongo_client.ragaas
    
    orphan_doc_ids = []
    for doc_id in doc_ids:
        doc_exists = db.documents.find_one({"id": doc_id, "kb_id": KB_ID})
        if not doc_exists:
            print(f"  - {doc_id}: ORPHAN (not in MongoDB)")
            orphan_doc_ids.append(doc_id)
        else:
            print(f"  - {doc_id}: Valid")
    
    mongo_client.close()
    
    # Delete orphans
    if orphan_doc_ids:
        print(f"\nDeleting {len(orphan_doc_ids)} orphan document(s)...")
        for orphan_id in orphan_doc_ids:
            expr = f'doc_id == "{orphan_id}"'
            res = collection.delete(expr)
            print(f"  Deleted doc_id={orphan_id}: {res}")
        
        collection.flush()
        collection.release()
        collection.load()
        
        total_after = collection.num_entities
        print(f"\nTotal entities after cleanup: {total_after}")
        print(f"Deleted: {total_before - total_after}")
    else:
        print("\nNo orphans found. Collection is clean!")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
