
import requests
from requests.auth import HTTPBasicAuth

# 1. KB ID 및 데이터셋 이름 설정
KB_ID = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
DATASET_NAME = f"kb_{KB_ID.replace('-', '_')}"
FUSEKI_URL = f"http://localhost:3030/{DATASET_NAME}/query"

# 2. 인증 정보 (admin/admin)
AUTH = HTTPBasicAuth("admin", "admin")

# 3. '성기훈' 관련 모든 트리플 조회 쿼리 (Union Graph 사용 필수)
sparql_query = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?sLabel ?p ?oLabel ?direction
FROM <urn:x-arq:UnionGraph>
WHERE {
  {
    # Outgoing: 성기훈 -> ?p -> ?o
    ?s rdfs:label ?sLabel .
    FILTER(CONTAINS(STR(?sLabel), "성기훈")) .
    ?s ?p ?o .
    OPTIONAL { ?o rdfs:label ?oLabel }
    BIND("Outgoing" AS ?direction)
  }
  UNION
  {
    # Incoming: ?s -> ?p -> 성기훈
    ?o rdfs:label ?oLabel .
    FILTER(CONTAINS(STR(?oLabel), "성기훈")) .
    ?s ?p ?o .
    OPTIONAL { ?s rdfs:label ?sLabel }
    BIND("Incoming" AS ?direction)
  }
}
LIMIT 100
"""

def inspect_fuseki():
    print(f"Target Fuseki URL: {FUSEKI_URL}")
    print("Executing SPARQL Query...")
    
    try:
        resp = requests.post(FUSEKI_URL, data={'query': sparql_query}, auth=AUTH)
        if resp.status_code != 200:
            print(f"❌ Error: {resp.status_code}")
            print(resp.text)
            return

        results = resp.json().get('results', {}).get('bindings', [])
        
        if not results:
            print("❌ No triples found for entity '성기훈' (Tried pattern match)")
            return

        print(f"✅ Found {len(results)} triples for '성기훈':")
        print("-" * 120)
        print(f"{'Direction':<10} | {'Subject Label':<30} | {'Predicate':<30} | {'Object Label':<30}")
        print("-" * 120)
        
        for r in results:
            direction = r.get('direction', {}).get('value', '-')
            
            s = r.get('sLabel', {}).get('value', 'Unknown')
            if not s or s == "Unknown":
                 s_uri = r.get('s', {}).get('value', '')
                 s = s_uri.split('/')[-1]

            p = r.get('p', {}).get('value', '').split('/')[-1] # Shorten URI
            if '#' in p: p = p.split('#')[-1]
            
            o = r.get('oLabel', {}).get('value', 'Unknown')
            if not o or o == "Unknown":
                 o_uri = r.get('o', {}).get('value', '')
                 o = o_uri.split('/')[-1]
            
            print(f"{direction:<10} | {s:<30} | {p:<30} | {o:<30}")

    except Exception as e:
        print(f"Python Error: {e}")

if __name__ == "__main__":
    inspect_fuseki()
