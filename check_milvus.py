from pymilvus import connections, Collection

connections.connect(host='localhost', port='19530')

kb_id = 'd2980afe-3238-4d34-854d-400bb3937bb9'
collection_name = f"kb_{kb_id.replace('-', '_')}"

try:
    collection = Collection(collection_name)
    collection.load()
    
    # Count all entities in this KB
    count = collection.query(
        expr="kb_id != ''",  # All entities
        output_fields=['chunk_id'],
        limit=1
    )
    
    # Get actual count using num_entities
    stats = collection.num_entities
    print(f"Milvus collection '{collection_name}' has {stats} entities")
except Exception as e:
    print(f"Error or collection doesn't exist: {e}")
