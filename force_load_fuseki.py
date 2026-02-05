import sys
import os
import requests
from requests.auth import HTTPBasicAuth

# Fix: Force-insert data from Doc2Onto output to Fuseki

def load_data():
    print("Starting manual data load to Fuseki...")
    
    # Configuration
    FUSEKI_URL = "http://fuseki:3030" # Service name in Docker network
    KB_ID = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
    SAFE_KB_ID = f"kb_{KB_ID.replace('-', '_')}"
    DATASET_URL = f"{FUSEKI_URL}/{SAFE_KB_ID}"
    
    # Paths (As mounted in container)
    BASE_TRIG = "/Doc2Onto/output/base.trig"
    
    if not os.path.exists(BASE_TRIG):
        print(f"Error: File not found at {BASE_TRIG}")
        # Try to find it via find command logic if path is different in reality
        return

    print(f"Reading {BASE_TRIG}...")
    with open(BASE_TRIG, "rb") as f:
        data = f.read()
        
    print(f"Uploading {len(data)} bytes to {DATASET_URL}...")
    
    # 1. Update (INSERT DATA) or PUT/POST to GSP
    # Using GSP (Graph Store Protocol) is easiest for file upload
    # POST /dataset/data?graph=default or specific graph
    # Doc2Onto uses TriG which contains graph names, so we just POST to /data
    
    upload_url = f"{DATASET_URL}/data"
    
    try:
        response = requests.post(
            upload_url,
            data=data,
            headers={"Content-Type": "application/trig"},
            auth=HTTPBasicAuth("admin", "admin")
        )
        
        if response.status_code in [200, 201, 204]:
            print("Successfully uploaded base.trig to Fuseki!")
        else:
            print(f"Failed to upload: {response.status_code} {response.text}")
            
    except Exception as e:
        print(f"Error during upload: {e}")

if __name__ == "__main__":
    load_data()
