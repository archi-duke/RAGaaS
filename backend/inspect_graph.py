
import requests

KB_ID = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
FUSEKI_URL = "http://localhost:3030"

# 1. '성기훈'이라는 라벨을 가진 노드의 모든 연결(Incoming & Outgoing) 조회
sparql_query = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?sLabel ?p ?oLabel ?direction
WHERE {
  {
    # Outgoing: 성기훈 -> ?p -> ?o
    ?s rdfs:label ?sLabel .
    FILTER(STR(?sLabel) = "성기훈") .
    ?s ?p ?o .
    OPTIONAL { ?o rdfs:label ?oLabel }
    BIND("Outgoing" AS ?direction)
  }
  UNION
  {
    # Incoming: ?s -> ?p -> 성기훈
    ?o rdfs:label ?oLabel .
    FILTER(STR(?oLabel) = "성기훈") .
    ?s ?p ?o .
    OPTIONAL { ?s rdfs:label ?sLabel }
    BIND("Incoming" AS ?direction)
  }
}
LIMIT 50
"""

def inspect_fuseki():
    dataset_url = f"{FUSEKI_URL}/{KB_ID}/query"
    try:
        print(f"Executing Query on {dataset_url}...")
        resp = requests.post(dataset_url, data={'query': sparql_query})
        resp.raise_for_status()
        
        results = resp.json().get('results', {}).get('bindings', [])
        
        if not results:
            print("❌ No triples found for entity '성기훈'")
            # 혹시 라벨이 정확히 "성기훈"이 아닐 수도 있으므로 유사 검색 시도
            check_similar()
            return

        print(f"✅ Found {len(results)} triples for '성기훈':")
        print("-" * 60)
        print(f"{'Direction':<10} | {'Subject':<20} | {'Predicate':<30} | {'Object':<20}")
        print("-" * 60)
        
        for r in results:
            direction = r.get('direction', {}).get('value', '-')
            s = r.get('sLabel', {}).get('value', 'Unknown')
            p = r.get('p', {}).get('value', '').split('/')[-1] # Shorten URI
            o = r.get('oLabel', {}).get('value', 'Unknown')
            
            print(f"{direction:<10} | {s:<20} | {p:<30} | {o:<20}")

    except Exception as e:
        print(f"Error: {e}")

def check_similar():
    print("\n🔍 Checking for similar labels...")
    q = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?label WHERE {
        ?s rdfs:label ?label .
        FILTER(CONTAINS(STR(?label), "성기훈"))
    } LIMIT 10
    """
    try:
        resp = requests.post(f"{FUSEKI_URL}/{KB_ID}/query", data={'query': q})
        print(resp.json())
    except:
        pass

if __name__ == "__main__":
    inspect_fuseki()
