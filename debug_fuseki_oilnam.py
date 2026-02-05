import sys
import os
import asyncio
import json

# Add backend path
sys.path.append("/app")

from app.core.fuseki import fuseki_client

async def main():
    print("Debugging Fuseki Graph Content for '오일남'...")
    
    print("Debugging Fuseki Graph Content for '성기훈' across ALL datasets...")
    
    import requests
    from app.core.config import settings
    
    # 1. Get all datasets
    try:
        ds_resp = requests.get(f"{settings.FUSEKI_URL}/$/datasets", auth=('admin', 'admin'))
        datasets = [d['ds.name'][1:] for d in ds_resp.json()['datasets']]
    except Exception as e:
        print(f"Error fetching datasets: {e}")
        return

    print(f"Found {len(datasets)} datasets. Scanning for '성기훈' types...")

    for kb_id in datasets:
        # Check '성기훈' type
        query = """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        
        SELECT ?type ?label
        WHERE {
            GRAPH ?g {
                ?s rdfs:label "성기훈"@ko .
                ?s rdf:type ?type .
                OPTIONAL { ?s rdfs:label ?label }
            }
        }
        LIMIT 5
        """
        
        try:
            # Direct query to dataset endpoint
            endpoint = f"{settings.FUSEKI_URL}/{kb_id}/query"
            
            # Simple wrapper usage (bypass client helper to ensure direct access)
            from SPARQLWrapper import SPARQLWrapper, JSON
            sparql = SPARQLWrapper(endpoint)
            sparql.setCredentials("admin", "admin")
            sparql.setQuery(query)
            sparql.setReturnFormat(JSON)
            results = sparql.query().convert()
            
            bindings = results.get("results", {}).get("bindings", [])
            if bindings:
                print(f"\n[KB: {kb_id}]")
                for b in bindings:
                    t_val = b.get("type", {}).get("value")
                    l_val = b.get("label", {}).get("value")
                    print(f"  Type: {t_val.split('#')[-1] if '#' in t_val else t_val}")
                    print(f"  Label: {l_val}")
        except Exception as e:
            # print(f"Skipping {kb_id}: {e}")
            pass

if __name__ == "__main__":
    asyncio.run(main())
