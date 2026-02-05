import requests
import json

FUSEKI_URL = "http://localhost:3030"
AUTH = ("admin", "admin")
# KB ID for test2
KB_ID = "d2980afe_3238_4d34_854d_400bb3937bb9"
DS_NAME = f"/kb_{KB_ID}"

def query_all():
    url = f"{FUSEKI_URL}{DS_NAME}/query"
    # Query across all graphs to see where data is and what it looks like
    query = """
    SELECT ?g ?s ?p ?o
    WHERE {
      GRAPH ?g {
        ?s ?p ?o .
      }
    }
    LIMIT 20
    """
    try:
        resp = requests.post(url, data={"query": query}, auth=AUTH)
        resp.raise_for_status()
        results = resp.json().get("results", {}).get("bindings", [])
        print(f"--- All Data in {DS_NAME} ---")
        if not results:
            print("No data found.")
            return

        for r in results:
            g = r.get('g', {}).get('value', 'default')
            s = r['s']['value']
            p = r['p']['value']
            o = r['o']['value']
            print(f"G: {g}")
            print(f"S: {s}")
            print(f"P: {p}")
            print(f"O: {o}")
            print("-" * 20)
    except Exception as e:
        print(f"Error querying {DS_NAME}: {e}")

if __name__ == "__main__":
    query_all()
