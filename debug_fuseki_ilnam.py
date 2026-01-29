import sys
import os
import asyncio
import json

# Add backend path
sys.path.append("/app")

from app.core.fuseki import fuseki_client

async def main():
    print("Debugging Fuseki Graph Content for '일남'...")
    
    kb_id = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
    
    debug_query = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT DISTINCT ?s ?p ?o ?g
    WHERE {
      GRAPH ?g {
        ?s ?p ?o .
        FILTER (
            CONTAINS(STR(?s), "일남") || 
            CONTAINS(STR(?o), "일남") ||
            (ISLITERAL(?o) && CONTAINS(STR(?o), "일남"))
        )
      }
    }
    LIMIT 100
    """
    
    print(f"\nExecuting Debug Query against KB ID: {kb_id}...")
    try:
        results = fuseki_client.query_sparql(kb_id, debug_query)
        bindings = results.get("results", {}).get("bindings", [])
        
        print(f"\n[Debug Results] Found {len(bindings)} triples related to '일남':")
        for binding in bindings:
            s_val = binding.get("s", {}).get("value", "")
            p_val = binding.get("p", {}).get("value", "")
            o_val = binding.get("o", {}).get("value", "")
            g_val = binding.get("g", {}).get("value", "")
            
            s = s_val.split("/")[-1] if "/" in s_val else s_val
            p = p_val.split("/")[-1] if "/" in p_val else p_val
            o = o_val.split("/")[-1] if "/" in o_val else o_val
            
            print(f"Graph: {g_val}\n S: {s} | P: {p} | O: {o}\n")

        # Also check for predicate "스승" or "제자"
        print("-" * 50)
        print("Checking for '스승' or '제자' relationship...")
        
        rel_query = """
        SELECT DISTINCT ?s ?p ?o ?g
        WHERE {
          GRAPH ?g {
            ?s ?p ?o .
            FILTER (
                CONTAINS(STR(?p), "스승") || CONTAINS(STR(?p), "제자")
            )
          }
        }
        LIMIT 50
        """
        results_rel = fuseki_client.query_sparql(kb_id, rel_query)
        bindings_rel = results_rel.get("results", {}).get("bindings", [])
        print(f"Found {len(bindings_rel)} triples with '스승' or '제자' predicate:")
        for binding in bindings_rel:
             p = binding.get("p", {}).get("value", "").split("/")[-1]
             print(f"P: {p}")

    except Exception as e:
        print(f"Error executing query: {e}")

if __name__ == "__main__":
    asyncio.run(main())
