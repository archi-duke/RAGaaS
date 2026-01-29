from SPARQLWrapper import SPARQLWrapper, JSON
import os
import sys

# Set encoding to utf-8 for output
sys.stdout.reconfigure(encoding='utf-8')

FUSEKI_URL = os.getenv("FUSEKI_URL", "http://localhost:3030")
KB_ID = "fe5ef020-a2f7-425d-883d-5f8982c6320c"

def verify_variations():
    safe_kb_id = f"kb_{KB_ID.replace('-', '_')}"
    dataset_url = f"{FUSEKI_URL}/{safe_kb_id}/sparql"
    
    sparql = SPARQLWrapper(dataset_url)
    
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?s ?sLabel
    WHERE {
        ?s ?p ?o .
        FILTER (
            CONTAINS(LCASE(str(?s)), "기훈") || 
            CONTAINS(LCASE(str(?s)), "성기훈")
        )
        OPTIONAL { ?s rdfs:label ?sLabel }
    }
    LIMIT 20
    """
    
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    
    print(f"Checking for 'Gi-hun' variations in KB {KB_ID}...")
    
    try:
        results = sparql.query().convert()
        bindings = results["results"]["bindings"]
        
        if not bindings:
            print("No variations found.")
            return

        print(f"Found {len(bindings)} distinct entities:")
        for b in bindings:
            s = b['s']['value']
            lbl = b.get('sLabel', {}).get('value', 'NoLabel')
            print(f" - URI: {s} | Label: {lbl}")
            
    except Exception as e:
        print(f"Error querying Fuseki: {e}")

if __name__ == "__main__":
    verify_variations()
