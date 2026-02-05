from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility
from app.core.config import settings

def connect_milvus():
    connections.connect(
        alias="default", 
        host=settings.MILVUS_HOST, 
        port=settings.MILVUS_PORT
    )

def create_collection(kb_id: str, metric_type: str = "COSINE", index_type: str = "IVF_FLAT"):
    # Ensure Milvus connection is active (auto-reconnect if needed)
    try:
        # Try to list collections as a connection health check
        utility.list_collections()
    except Exception as e:
        print(f"[Milvus] Connection lost or not established: {e}. Reconnecting...")
        try:
            connections.disconnect(alias="default")
        except:
            pass
        connect_milvus()
        print("[Milvus] Reconnected successfully")
    
    collection_name = f"kb_{kb_id.replace('-', '_')}"
    
    if utility.has_collection(collection_name):
        col = Collection(collection_name)
        # Check if metadata field exists
        has_metadata = any(field.name == "metadata" for field in col.schema.fields)
        if not has_metadata:
            print(f"Collection {collection_name} has outdated schema (missing metadata). Dropping and recreating.")
            utility.drop_collection(collection_name)
        else:
            # Check if index type matches
            if col.has_index():
                idx = col.index()
                current_type = idx.params.get("index_type")
                if current_type != index_type:
                    print(f"Index type mismatch: {current_type} vs {index_type}. Recreating index.")
                    try:
                        col.release()
                    except:
                        pass
                    col.drop_index()
                else:
                    return col
            else:
                # No index, will create below
                pass
            
            if not col.has_index():
                _create_index(col, metric_type, index_type)
            return col
    
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="metadata", dtype=DataType.JSON),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=1536) # Assuming OpenAI embedding dim
    ]
    
    schema = CollectionSchema(fields, "Knowledge Base Collection")
    collection = Collection(collection_name, schema)
    _create_index(collection, metric_type, index_type)
    return collection

def _create_index(collection, metric_type, index_type):
    index_params = {
        "metric_type": metric_type,
        "index_type": index_type,
        "params": {}
    }
    
    if index_type == "IVF_FLAT":
        index_params["params"] = {"nlist": 1024}
    elif index_type == "HNSW":
        index_params["params"] = {"M": 16, "efConstruction": 200}
    elif index_type == "LSH":
        index_params["params"] = {"nbits": 8}
    elif index_type == "FLAT":
        index_params["params"] = {}
        
    collection.create_index(field_name="vector", index_params=index_params)
