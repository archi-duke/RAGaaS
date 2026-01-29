import requests
import urllib.parse

KB_ID = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
DATASET_NAME = f"kb_{KB_ID.replace('-', '_')}"
FUSEKI_BASE_URL = "http://localhost:3030"
QUERY_URL = f"{FUSEKI_BASE_URL}/{DATASET_NAME}/query"

def run_query(query, label):
    print(f"\n--- {label} ---")
    try:
        response = requests.post(QUERY_URL, data={'query': query})
        response.raise_for_status()
        results = response.json()
        bindings = results.get("results", {}).get("bindings", [])
        print(f"Count: {len(bindings)}")
        for b in bindings[:10]:
            print(b)
    except Exception as e:
        print(f"Error: {e}")

# 1. CORRECT OWL namespace
query_owl_class = """
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?class ?label WHERE {
    ?class a owl:Class .
    OPTIONAL { ?class rdfs:label ?label }
} LIMIT 20
"""

# 2. Object Properties
query_object_properties = """
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?prop ?label ?domain ?range WHERE {
    ?prop a owl:ObjectProperty .
    OPTIONAL { ?prop rdfs:label ?label }
    OPTIONAL { ?prop rdfs:domain ?domain }
    OPTIONAL { ?prop rdfs:range ?range }
} LIMIT 20
"""

# 3. Datatype Properties
query_datatype_properties = """
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?prop ?label WHERE {
    ?prop a owl:DatatypeProperty .
    OPTIONAL { ?prop rdfs:label ?label }
} LIMIT 20
"""

# 4. List all named graphs
query_graphs = """
SELECT DISTINCT ?g WHERE {
    GRAPH ?g { ?s ?p ?o }
}
"""

# 5. Search for owl:Class in ALL graphs (including default)
query_owl_class_all = """
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?g ?class ?label WHERE {
    { ?class a owl:Class . OPTIONAL { ?class rdfs:label ?label } }
    UNION
    { GRAPH ?g { ?class a owl:Class . OPTIONAL { ?class rdfs:label ?label } } }
} LIMIT 20
"""

# 6. Check all rdf:type values to see what types exist
query_all_types = """
SELECT DISTINCT ?type (COUNT(?s) as ?count) WHERE {
    ?s a ?type .
} GROUP BY ?type ORDER BY DESC(?count) LIMIT 30
"""

if __name__ == "__main__":
    print(f"Inspecting Fuseki Dataset: {DATASET_NAME}")
    run_query(query_graphs, "Named Graphs")
    run_query(query_owl_class, "OWL Classes (Default Graph)")
    run_query(query_owl_class_all, "OWL Classes (All Graphs)")
    run_query(query_all_types, "All rdf:type values")
    run_query(query_object_properties, "OWL Object Properties")
