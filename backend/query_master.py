from app.core.fuseki import fuseki_client
import urllib.parse

kb_id = "35c9a4e3-de46-4c0d-aeff-201518cf8532"

def print_comment_triples():
    print(f"\n{'='*20} Searching for rdfs:comment {'='*20}")
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?s ?o
    WHERE {
        ?s rdfs:comment ?o .
    }
    LIMIT 20
    """
    results = fuseki_client.query_sparql(kb_id, query)
    for b in results.get("results", {}).get("bindings", []):
        s = b.get("s", {}).get("value", "?")
        o = b.get("o", {}).get("value", "?")
        print(f"{s} --[rdfs:comment]--> {o}")

print_comment_triples()



