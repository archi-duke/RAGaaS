import sys
import os
import asyncio
import json

# Add backend path
sys.path.append("/app")

from app.services.retrieval.graph_backends.fuseki import FusekiBackend
from app.core.fuseki import fuseki_client
from app.core.config import settings

async def main():
    print("Initializing FusekiBackend...")
    try:
        backend = FusekiBackend()
    except Exception as e:
        print(f"Error initializing backend: {e}")
        return

    query = "성기훈의 스승의 스승은 누구야?"
    # Using entities that might be extracted for context
    entities = ["성기훈"] 
    
    print(f"\nTest Query: {query}")
    print("-" * 50)
    
    if not backend.generator:
        print("ERROR: SPARQLGenerator not initialized. Check OpenAI API Key and Doc2Onto installation.")
        return

    # 1. Generate SPARQL
    print("Generating SPARQL with Doc2Onto...")
    try:
        gen_result = backend.generator.generate(
            question=query,
            context=f"Entities: {', '.join(entities)}",
            mode="ontology",
            inverse_relation="auto"
        )
        generated_sparql = gen_result.get("sparql")
        print("\n[Generated SPARQL Body]:")
        print(generated_sparql)
    except Exception as e:
        print(f"Error during generation: {e}")
        return

    if not generated_sparql:
        print("No SPARQL generated.")
        return

    # 2. Apply the fix (Inject FROM <urn:x-arq:UnionGraph>)
    if "WHERE" in generated_sparql:
        sparql_query_content = generated_sparql.replace("WHERE", "FROM <urn:x-arq:UnionGraph>\nWHERE", 1)
    else:
        sparql_query_content = generated_sparql

    prefixes = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    PREFIX inst: <http://example.org/onto/inst/> 
    PREFIX rel: <http://example.org/onto/rel/> 
    PREFIX prop: <http://example.org/onto/prop/>
    """
    
    full_query = prefixes + sparql_query_content
    
    print("\n[Final Executed Query]:")
    print(full_query)
    
    # 3. Execute Query
    # KB ID found from previous logs
    kb_id = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
    
    print(f"\nExecuting against KB ID: {kb_id}...")
    try:
        results = fuseki_client.query_sparql(kb_id, full_query)
        bindings = results.get("results", {}).get("bindings", [])
        
        print(f"\n[Execution Results] Found {len(bindings)} bindings:")
        print(json.dumps(bindings, indent=2, ensure_ascii=False))
        
        # Parsed clean output
        print("\n[Parsed Answers]:")
        for binding in bindings:
            row = []
            for var in binding:
                val = binding[var]['value']
                # extract name if it's a uri
                if "/" in val:
                    val = val.split("/")[-1]
                row.append(f"{var}={val}")
            print(", ".join(row))
            
    except Exception as e:
        print(f"Error executing query: {e}")

if __name__ == "__main__":
    asyncio.run(main())
