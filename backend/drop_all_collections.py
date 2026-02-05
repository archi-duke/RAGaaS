"""
Drop all existing Milvus collections to allow recreation with COSINE metric
"""

from pymilvus import connections, utility
from app.core.config import settings

def drop_all_collections():
    # Connect to Milvus
    connections.connect(
        alias="default",
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT
    )
    
    # Get all collections
    collections = utility.list_collections()
    
    print(f"Found {len(collections)} collections")
    
    for collection_name in collections:
        print(f"Dropping collection: {collection_name}")
        utility.drop_collection(collection_name)
    
    print("All collections dropped successfully!")
    print("Please re-upload your documents to recreate collections with COSINE metric.")

if __name__ == "__main__":
    drop_all_collections()
