from pymilvus import connections, Collection

# Connect to Milvus
connections.connect(host='localhost', port='19530')

# Collection 이름
kb_id = 'd2980afe-3238-4d34-854d-400bb3937bb9'
collection_name = f"kb_{kb_id.replace('-', '_')}"

collection = Collection(collection_name)
collection.load()

# 특정 chunk_id로 검색
chunk_id = '1a815e61-64d0-46e4-bda1-f7de2775a3f8_2'
results = collection.query(
    expr=f'chunk_id == "{chunk_id}"',
    output_fields=['chunk_id', 'content']
)

if results:
    print(f"Found chunk: {chunk_id}")
    print(f"Content: {results[0]['content'][:500]}")
else:
    print(f"Chunk not found: {chunk_id}")
