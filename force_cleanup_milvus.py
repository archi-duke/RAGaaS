#!/usr/bin/env python3
"""
Force cleanup orphaned Milvus data with compaction
"""
from pymilvus import connections, Collection, utility
import time

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
collection_name = f"kb_{KB_ID.replace('-', '_')}"

print(f"Connecting to Milvus...")
connections.connect("default", host="localhost", port="19530")

if not utility.has_collection(collection_name):
    print(f"Collection '{collection_name}' does not exist.")
    exit(0)

collection = Collection(collection_name)
collection.load()

print(f"Total entities: {collection.num_entities}")

# Delete all orphaned docs
expr = 'doc_id == "6498b669-dbe4-49af-b999-843f017ed7b0"'
print(f"Deleting with expression: {expr}")

res = collection.delete(expr)
print(f"Delete result: {res}")

# Flush
collection.flush()
print("Flushed")

# Release and reload
collection.release()
print("Released from memory")

# Compact to actually remove deleted entities
print("Starting compaction...")
collection.compact()
print("Compaction complete")

# Wait for compaction
time.sleep(2)

# Check status
collection.load()
print(f"Total entities after compaction: {collection.num_entities}")

# Verify
try:
    remaining = collection.query(expr=expr, output_fields=["chunk_id"], limit=10)
    print(f"Verification: {len(remaining)} entities still match the expression")
except Exception as e:
    print(f"Verification query: {e}")
