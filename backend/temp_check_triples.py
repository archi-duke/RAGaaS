
import asyncio
import sys
import os

# Add parent directory to path to allow imports from app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.fuseki import fuseki_client
from app.core.config import settings

async def main():
    kb_id = "35c9a4e3-de46-4c0d-aeff-201518cf8532"  # From logs
    query = """
    PREFIX rel: <http://rag.local/relation/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT ?s ?sLabel ?p ?o ?oLabel
    WHERE {
        ?s rdfs:label ?sLabel .
        FILTER regex(?sLabel, "성기훈", "i")
        
        ?s ?p ?o .
        OPTIONAL { ?o rdfs:label ?oLabel }
    }
    LIMIT 100
    """
    
    print(f"Querying KB: {kb_id}")
    try:
        results = fuseki_client.query_sparql(kb_id, query)
        print(f"Found {len(results.get('results', {}).get('bindings', []))} triples:")
        for b in results.get('results', {}).get('bindings', []):
            p = b['p']['value']
            o = b.get('oLabel', {}).get('value', b['o']['value'])
            print(f"  - [{p}] -> {o}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
