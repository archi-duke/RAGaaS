import requests
import json

FUSEKI_URL = "http://localhost:3030"
AUTH = ("admin", "admin")
KB_ID = "d2980afe_3238_4d34_854d_400bb3937bb9"
DS_NAME = f"/kb_{KB_ID}"

def check_uri(uri):
    url = f"{FUSEKI_URL}{DS_NAME}/query"
    query = f"""
    SELECT ?p ?o ?dir ?s
    WHERE {{
      {{
        <{uri}> ?p ?o .
        BIND("OUT" AS ?dir)
        BIND(<{uri}> AS ?s)
      }}
      UNION
      {{
        ?s ?p <{uri}> .
        BIND("IN" AS ?dir)
        BIND(<{uri}> AS ?o)
      }}
    }}
    """
    try:
        resp = requests.post(url, data={"query": query}, auth=AUTH)
        resp.raise_for_status()
        results = resp.json().get("results", {}).get("bindings", [])
        print(f"--- Relations for <{uri}> ---")
        for r in results:
            p = r['p']['value']
            o = r.get('o', {}).get('value', 'N/A')
            s = r.get('s', {}).get('value', 'N/A')
            dir = r['dir']['value']
            print(f"{dir}: {s} -> {p} -> {o}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_uri("http://rag.local/inst/오일남")
