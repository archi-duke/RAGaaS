import requests
import json

FUSEKI_URL = "http://localhost:3030"
AUTH = ("admin", "admin")
KB_ID = "d2980afe_3238_4d34_854d_400bb3937bb9"
DS_NAME = f"/kb_{KB_ID}"

def check_entity(name):
    url = f"{FUSEKI_URL}{DS_NAME}/query"
    query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?p ?o ?dir
    {{
      {{
        ?s rdfs:label "{name}" .
        ?s ?p ?o .
        BIND("OUT" AS ?dir)
      }}
      UNION
      {{
        ?o2 rdfs:label "{name}" .
        ?s ?p ?o2 .
        BIND("IN" AS ?dir)
      }}
    }}
    """
    try:
        resp = requests.post(url, data={"query": query}, auth=AUTH)
        resp.raise_for_status()
        results = resp.json().get("results", {}).get("bindings", [])
        print(f"--- Relations for '{name}' ---")
        for r in results:
            p = r['p']['value']
            o = r.get('o', {}).get('value', 'N/A')
            s = r.get('s', {}).get('value', 'N/A')
            dir = r['dir']['value']
            if dir == "OUT":
                print(f"OUT: {p} -> {o}")
            else:
                print(f"IN: {s} -> {p}")
            print("-" * 20)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_entity("오일남")
