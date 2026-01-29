import requests

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

def search_relations(kb_id, rel_term):
    dataset = f"kb_{kb_id.replace('-', '_')}"
    print(f"--- Searching for relation containing '{rel_term}' ---")
    
    query = f"""
    SELECT ?s ?p ?o WHERE {{
        GRAPH ?g {{
            ?s ?p ?o .
            FILTER(CONTAINS(STR(?p), "{rel_term}"))
        }}
    }} LIMIT 10
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
                    print(f"  {b['s']['value']} -> {b['p']['value']} -> {b['o']['value']}")
            else:
                print(f"  No relations found with '{rel_term}'")
        else:
            print(f"  Error: {response.status_code}")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == "__main__":
    search_relations(KB_ID, "스승")
    print()
    search_relations(KB_ID, "사조")
    print()
    search_relations(KB_ID, "teacher")
