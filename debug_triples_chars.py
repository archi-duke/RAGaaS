import requests

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

def debug_triples(kb_id):
    dataset = f"kb_{kb_id.replace('-', '_')}"
    query = """
    SELECT ?s ?p ?o WHERE {
        GRAPH ?g {
            ?s ?p ?o .
            FILTER(
                CONTAINS(LCASE(STR(?s)), "기훈") || 
                CONTAINS(LCASE(STR(?o)), "기훈") ||
                CONTAINS(LCASE(STR(?s)), "일남") ||
                CONTAINS(LCASE(STR(?o)), "일남") ||
                CONTAINS(LCASE(STR(?s)), "duke") ||
                CONTAINS(LCASE(STR(?o)), "duke")
            )
        }
    }
    """
    response = requests.post(
        f"http://localhost:3030/{dataset}/query",
        data={"query": query},
        auth=("admin", "admin")
    )
    bindings = response.json()["results"]["bindings"]
    print(f"Total relevant triples: {len(bindings)}")
    for b in bindings:
        s = b["s"]["value"]
        p = b["p"]["value"]
        o = b["o"]["value"]
        print(f"  {s} -> {p} -> {o}")

if __name__ == "__main__":
    debug_triples(KB_ID)
