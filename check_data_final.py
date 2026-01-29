import requests
import json

FUSEKI_URL = "http://localhost:3030"
AUTH = ("admin", "admin")
KB_ID = "d2980afe_3238_4d34_854d_400bb3937bb9"
DS_NAME = f"/kb_{KB_ID}"

def check_triples():
    url = f"{FUSEKI_URL}{DS_NAME}/query"
    query = """
    SELECT ?s ?p ?o ?g
    WHERE {
      GRAPH ?g {
        { ?s ?p ?o . FILTER(CONTAINS(STR(?s), "성기훈") || CONTAINS(STR(?o), "성기훈")) }
        UNION
        { ?s ?p ?o . FILTER(CONTAINS(STR(?s), "오일남") || CONTAINS(STR(?o), "오일남")) }
      }
    }
    """
    try:
        resp = requests.post(url, data={"query": query}, auth=AUTH)
        resp.raise_for_status()
        results = resp.json().get("results", {}).get("bindings", [])
        print("--- Triples involving 성기훈 or 오일남 ---")
        for r in results:
            print(f"G: {r['g']['value']}")
            print(f"S: {r['s']['value']}")
            print(f"P: {r['p']['value']}")
            print(f"O: {r['o']['value']}")
            print("-" * 20)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_triples()
