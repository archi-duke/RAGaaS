import requests
import json

FUSEKI_URL = "http://localhost:3030"
AUTH = ("admin", "admin")
KB_ID = "d2980afe_3238_4d34_854d_400bb3937bb9"
DS_NAME = f"/kb_{KB_ID}"

def check_labels():
    url = f"{FUSEKI_URL}{DS_NAME}/query"
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?s ?label
    WHERE {
      GRAPH ?g {
        ?s rdfs:label ?label .
        FILTER(CONTAINS(STR(?s), "rag.local"))
      }
    }
    LIMIT 20
    """
    try:
        resp = requests.post(url, data={"query": query}, auth=AUTH)
        resp.raise_for_status()
        results = resp.json().get("results", {}).get("bindings", [])
        print(f"--- Labels for rag.local entities ---")
        for r in results:
            print(f"S: {r['s']['value']}")
            print(f"L: {r['label']['value']}")
            print("-" * 20)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_labels()
