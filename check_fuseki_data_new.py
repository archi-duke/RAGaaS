import requests

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

def check_fuseki_data(kb_id):
    dataset = f"kb_{kb_id.replace('-', '_')}"
    print(f"--- Fuseki Check for dataset: {dataset} ---")
    
    # Check total triples
    query = "SELECT (count(*) as ?count) WHERE { GRAPH ?g { ?s ?p ?o } }"
    try:
        response = requests.post(
            f"http://localhost:3030/{dataset}/query",
            data={"query": query},
            auth=("admin", "admin"),
            timeout=10
        )
        if response.status_code == 200:
            count = response.json()["results"]["bindings"][0]["count"]["value"]
            print(f"[Fuseki] Total triples in Named Graphs: {count}")
        else:
            print(f"[Fuseki] Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[Fuseki] Request error: {e}")

    # Check some triples
    query_samples = "SELECT ?s ?p ?o ?g WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 5"
    try:
        response = requests.post(
            f"http://localhost:3030/{dataset}/query",
            data={"query": query_samples},
            auth=("admin", "admin"),
            timeout=10
        )
        if response.status_code == 200:
            bindings = response.json()["results"]["bindings"]
            print(f"[Fuseki] Sample Triples:")
            for b in bindings:
                print(f"  <{b['s']['value']}> <{b['p']['value']}> <{b['o']['value']}> (Graph: {b['g']['value']})")
        else:
            print(f"[Fuseki] Error {response.status_code}")
    except Exception as e:
        print(f"[Fuseki] Request error: {e}")

if __name__ == "__main__":
    check_fuseki_data(KB_ID)
