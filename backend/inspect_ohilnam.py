import requests
from requests.auth import HTTPBasicAuth
import json

def run():
    print("Inspecting 'Oh Il-nam' in Fuseki...")
    
    # Configuration
    base_url = "http://fuseki:3030"
    kb_id = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
    ds_name = f"kb_{kb_id.replace('-', '_')}"
    endpoint = f"{base_url}/{ds_name}/query"
    
    print(f"Target Dataset: {endpoint}")
    
    queries = [
        ("Check 'Jang-pung' (장풍)", """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER (CONTAINS(STR(?s), "장풍") || CONTAINS(STR(?o), "장풍"))
        }
        """)
    ]
    
    auth = HTTPBasicAuth('admin', 'admin')
    
    for title, q in queries:
        print(f"\n--- {title} ---")
        try:
            resp = requests.post(endpoint, data={'query': q}, auth=auth)
            if resp.status_code != 200:
                print(f"Error: {resp.status_code} {resp.text}")
                continue
                
            results = resp.json().get('results', {}).get('bindings', [])
            if not results:
                print("No results found.")
            
            for b in results:
                # Simple print of bindings
                parts = []
                for k, v in b.items():
                    val = v['value']
                    type_ = v['type']
                    parts.append(f"{k}=[{type_}]{val}")
                print("  " + ", ".join(parts))
                
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    run()
