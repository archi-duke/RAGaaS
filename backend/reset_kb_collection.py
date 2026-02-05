
import sys
import os
from pymilvus import utility

# Add app to path
sys.path.append(os.getcwd())

from app.core.milvus import connect_milvus, create_collection

def main():
    try:
        connect_milvus()
        print("Connected to Milvus.")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    kb_id = "0c0f4f26-f68a-479c-b76c-77a40eafc1aa"
    collection_name = f"kb_{kb_id.replace('-', '_')}"
    
    if utility.has_collection(collection_name):
        print(f"Dropping collection {collection_name}...")
        utility.drop_collection(collection_name)
        print("Collection dropped.")
        
        # Recreate it immediately so it's ready for upload
        print("Recreating empty collection...")
        create_collection(kb_id)
        print("Collection recreated successfully.")
    else:
        print(f"Collection {collection_name} does not exist.")

if __name__ == "__main__":
    main()
