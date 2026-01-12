
import asyncio
import sys
import os
import requests
from requests.auth import HTTPBasicAuth

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.core.config import settings
from app.core.neo4j_client import neo4j_client
from app.core.fuseki import fuseki_client

async def clear_neo4j():
    print("🧹 Clearing Neo4j Database...")
    try:
        # Delete all nodes and relationships
        # Standard deletion
        await neo4j_client.query("MATCH (n) DETACH DELETE n")
        print("✅ Neo4j cleared successfully.")
    except Exception as e:
        print(f"❌ Failed to clear Neo4j: {e}")

async def clear_fuseki():
    print("🧹 Clearing Fuseki Databases...")
    # Fuseki often has multiple datasets. We should clear the primary one used by RAGaaS.
    # Usually identified by settings.FUSEKI_URL and some logic. 
    # But RAGaaS creates datasets per KB. 
    # We might need to list datasets or just clear the default 'ds' if it exists, 
    # or iterate through known datasets. 
    # Since we can't easily list all dynamically created datasets without administration API,
    # we will try to clear the common ones or ask user/check logic.
    # However, 'fuseki_client.delete_dataset(kb_id)' exists.
    # If the user wants to clear EVERYTHING, we might strictly need to use the Fuseki Admin API.
    
    fuseki_base = settings.FUSEKI_URL # e.g. http://fuseki:3030
    admin_url = f"{fuseki_base}/$/datasets"
    
    try:
        auth = HTTPBasicAuth("admin", "admin")
        resp = requests.get(admin_url, auth=auth)
        if resp.status_code == 200:
            datasets = resp.json().get("datasets", [])
            print(f"Found {len(datasets)} datasets in Fuseki.")
            for ds in datasets:
                ds_name = ds["ds.name"].lstrip("/")
                print(f" - Deleting dataset: {ds_name}")
                del_resp = requests.delete(f"{admin_url}/{ds_name}", auth=auth)
                if del_resp.status_code == 200:
                    print(f"   ✅ Deleted {ds_name}")
                else:
                    print(f"   ❌ Failed to delete {ds_name}: {del_resp.status_code}")
        else:
            print(f"❌ Failed to list Fuseki datasets: {resp.status_code}")
            
    except Exception as e:
        print(f"❌ Error clearing Fuseki: {e}")

async def main():
    await clear_neo4j()
    await clear_fuseki()
    
    # Close connections
    await neo4j_client.close()

if __name__ == "__main__":
    asyncio.run(main())
