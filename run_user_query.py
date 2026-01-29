import requests
import json

FUSEKI_URL = "http://localhost:3030"
DATASET = "kb_4ba60b29_cfd3_4c04_969a_bfa64d6a46e1"

def run_query():
    query = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    PREFIX inst: <http://rag.local/inst/>
    PREFIX rel: <http://rag.local/rel/>
    PREFIX prop: <http://rag.local/prop/>
    PREFIX class: <http://rag.local/class/>
    SELECT DISTINCT ?teacherLabel WHERE {
      ?s rdfs:label ?sLabel .
      FILTER(STR(?sLabel) = "성기훈") .
      ?s (rel:제자|^rel:스승) ?teacher .
      ?teacher rdfs:label ?teacherLabel .
    }
    """
    
    # 1. First allow searching across all named graphs
    query = query.replace("WHERE {", "FROM <urn:x-arq:UnionGraph>\nWHERE {")
    
    print(f"Executing Query on Fuseki Dataset: {DATASET}...")
    
    kb_id = DATASET
    sparql_endpoint = f"{FUSEKI_URL}/{kb_id}/sparql"
    
    try:
        response = requests.post(
            sparql_endpoint,
            data={"query": query},
            headers={"Content-Type": "application/x-www-form-urlencoded"} # Standard SPARQL Protocol
        )
        
        if response.status_code != 200:
             # Try without dataset specific URL if standard port mapping differs
             print(f"Failed on {kb_id}, Status: {response.status_code}. Response: {response.text}")
             return

        results = response.json()
        bindings = results.get("results", {}).get("bindings", [])
        
        print(f"\nResults Found: {len(bindings)}")
        for b in bindings:
            print(f" - Teacher: {b.get('teacherLabel', {}).get('value')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_query()
