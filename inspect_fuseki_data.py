import asyncio
import os
import sys

# Add backend directory to path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.core.fuseki import fuseki_client

async def check():
    kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
    query = """
    SELECT DISTINCT ?p (COUNT(?s) as ?c) 
    FROM <urn:x-arq:UnionGraph> 
    WHERE { ?s ?p ?o } 
    GROUP BY ?p 
    ORDER BY DESC(?c) 
    LIMIT 50
    """
    res = fuseki_client.query_sparql(kb_id, query)
    bindings = res.get("results", {}).get("bindings", [])
    print(f"--- Predicates for KB {kb_id} ---")
    for b in bindings:
        p = b["p"]["value"]
        c = b["c"]["value"]
        print(f"{p} ({c})")
    
    # Also check if 장풍 exists as an entity and what relations it has
    query_jangpung = """
    SELECT DISTINCT ?p ?o
    FROM <urn:x-arq:UnionGraph>
    WHERE {
      ?s <http://www.w3.org/2000/01/rdf-schema#label> "장풍" .
      ?s ?p ?o .
    }
    """
    print(f"\n--- Relations for '장풍' ---")
    res_j = fuseki_client.query_sparql(kb_id, query_jangpung)
    for b in res_j.get("results", {}).get("bindings", []):
        print(f"P: {b['p']['value']} -> O: {b['o']['value']}")

    # Check incoming relations to '장풍'
    query_jangpung_in = """
    SELECT DISTINCT ?s ?p
    FROM <urn:x-arq:UnionGraph>
    WHERE {
      ?o <http://www.w3.org/2000/01/rdf-schema#label> "장풍" .
      ?s ?p ?o .
    }
    """
    print(f"\n--- Incoming Relations to '장풍' ---")
    res_in = fuseki_client.query_sparql(kb_id, query_jangpung_in)
    for b in res_in.get("results", {}).get("bindings", []):
        print(f"S: {b['s']['value']} -> P: {b['p']['value']}")

if __name__ == "__main__":
    asyncio.run(check())
