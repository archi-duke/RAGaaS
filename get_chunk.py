from pymilvus import connections, Collection

def get_chunk(kb_id, chunk_id):
    connections.connect()
    collection = Collection(f"kb_{kb_id.replace('-', '_')}")
    res = collection.query(
        expr=f'chunk_id == "{chunk_id}"',
        output_fields=["content"]
    )
    if res:
        print(f"Content for {chunk_id}:")
        print(res[0]["content"])
    else:
        print(f"Chunk {chunk_id} not found.")

if __name__ == "__main__":
    get_chunk("d2980afe-3238-4d34-854d-400bb3937bb9", "72560d34-0647-43a8-a303-9da6103bd8c0_4")
