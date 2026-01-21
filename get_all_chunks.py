from pymilvus import connections, Collection

def get_chunks(kb_id, doc_id):
    connections.connect()
    collection = Collection(f"kb_{kb_id.replace('-', '_')}")
    res = collection.query(
        expr=f'doc_id == "{doc_id}"',
        output_fields=["chunk_id", "content"]
    )
    # Sort by chunk_id
    res.sort(key=lambda x: x["chunk_id"])
    for r in res:
        print(f"--- {r['chunk_id']} ---")
        print(r["content"])

if __name__ == "__main__":
    get_chunks("d2980afe-3238-4d34-854d-400bb3937bb9", "72560d34-0647-43a8-a303-9da6103bd8c0")
