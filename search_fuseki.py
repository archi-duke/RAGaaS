import requests
import json

FUSEKI_URL = "http://localhost:3030"
AUTH = ("admin", "admin")
KB_ID = "d2980afe_3238_4d34_854d_400bb3937bb9"
DS_NAME = f"/kb_{KB_ID}"

def search_label(label):
    url = f"{FUSEKI_URL}{DS_NAME}/query"
    query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?s ?p ?o ?g
    WHERE {{
      GRAPH ?g {{
        ?s rdfs:label "{label}" .
        ?s ?p ?o .
      }}
    }}
    """
    try:
        resp = requests.post(url, data={"query": query}, auth=AUTH)
        resp.raise_for_status()
        results = resp.json().get("results", {}).get("bindings", [])
        print(f"--- Search Results for '{label}' ---")
        for r in results:
            print(f"G: {r['g']['value']}")
            print(f"S: {r['s']['value']}")
            print(f"P: {r['p']['value']}")
            print(f"O: {r['o']['value']}")
            print("-" * 20)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    search_label("성기훈")
