import requests

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

def search_label(kb_id, search_term):
    dataset = f"kb_{kb_id.replace('-', '_')}"
    print(f"--- Searching for '{search_term}' in Fuseki dataset: {dataset} ---")
    
    query = f"""
    SELECT ?s ?o WHERE {{
        GRAPH ?g {{
            ?s <http://www.w3.org/2000/01/rdf-schema#label> ?o .
            FILTER(CONTAINS(STR(?o), "{search_term}"))
        }}
    }}
    """
    try:
        response = requests.post(
            f"http://localhost:3030/{dataset}/query",
            data={"query": query},
            auth=("admin", "admin"),
            timeout=10
        )
        if response.status_code == 200:
            bindings = response.json()["results"]["bindings"]
            if bindings:
                for b in bindings:
                    print(f"Found: <{b['s']['value']}> -> Label: {b['o']['value']}")
            else:
                print("No matches found.")
        else:
            print(f"Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Request error: {e}")

if __name__ == "__main__":
    search_label(KB_ID, "성기훈")
    search_label(KB_ID, "4. 성기훈")
