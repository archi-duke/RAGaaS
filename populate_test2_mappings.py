
import asyncio
import json
import os
import re
from motor.motor_asyncio import AsyncIOMotorClient
import hashlib

# Configuration
MONGO_URI = "mongodb://root:example@localhost:27017"
DB_NAME = "ragaas"
KB_ID = "d2980afe-3238-4d34-854d-400bb3937bb9"
DOC_ID = "72560d34-0647-43a8-a303-9da6103bd8c0"
JSONL_PATH = "backend/doc2onto_out/d2980afe-3238-4d34-854d-400bb3937bb9/72560d34-0647-43a8-a303-9da6103bd8c0/candidates_filtered.jsonl"

def normalize_entity_name(name: str) -> str:
    if not name: return ""
    name = re.sub(r'^\d+번\s*', '', name)
    name = re.sub(r'^참가자\s*', '', name)
    return name.strip()

def compute_triple_hash(subject: str, predicate: str, obj: str) -> str:
    # Normalize inputs for hash calculation to match Fuseki retrieval
    s = normalize_entity_name(subject)
    p = predicate.strip()
    o = normalize_entity_name(obj)
    key = f"{s}|{p}|{o}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]

async def populate_mappings():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db["triple_chunk_mappings"]
    
    if not os.path.exists(JSONL_PATH):
        print(f"File not found: {JSONL_PATH}")
        return

    print(f"Reading {JSONL_PATH}...")
    
    count = 0
    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            record = json.loads(line)
            
            # Each record might have a list of triples
            triples = record.get("triples", [])
            for t in triples:
                subj = t.get("subject", "")
                pred = t.get("predicate", "")
                obj = t.get("object", "")
                
                if not subj or not obj: continue
                
                # Normalize names
                norm_subj = normalize_entity_name(subj)
                norm_obj = normalize_entity_name(obj)
                
                # Compute hash
                t_hash = compute_triple_hash(norm_subj, pred, norm_obj)
                
                # Determine chunk_id from source_chunk_id
                source_chunk_id = t.get("source_chunk_id", "")
                if "|" in source_chunk_id:
                    chunk_idx = source_chunk_id.split("|")[-1]
                else:
                    chunk_idx = "0"
                chunk_id = f"{DOC_ID}_{int(chunk_idx)}"
                
                # Create mapping document (without _id for $set)
                mapping = {
                    "kb_id": KB_ID,
                    "doc_id": DOC_ID,
                    "chunk_id": chunk_id,
                    "triple_hash": t_hash,
                    "subject": norm_subj,
                    "predicate": pred,
                    "object": norm_obj,
                    "source_start": 0, # Approximation or look up if possible
                    "source_end": 1000,
                    "created_at": "2026-01-18T00:00:00Z"
                }
                
                # Insert or Update
                await collection.update_one(
                    {"kb_id": KB_ID, "triple_hash": t_hash, "chunk_id": chunk_id},
                    {
                        "$set": mapping,
                        "$setOnInsert": {"_id": str(os.urandom(16).hex())}
                    },
                    upsert=True
                )
                count += 1

    print(f"Populated {count} mappings for KB {KB_ID}")

if __name__ == "__main__":
    asyncio.run(populate_mappings())
