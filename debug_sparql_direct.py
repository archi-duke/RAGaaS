
import asyncio
from app.services.retrieval.graph_backends.fuseki import FusekiBackend
from app.core.config import settings
from app.doc2onto.qa.sparql_generator import SPARQLGenerator
from app.core.fuseki import fuseki_client

async def test_sparql_generation_and_execution():
    query = "성기훈의 스승의 스승은 누구애?"
    entities = ["성기훈"] # Assuming entity extraction works as expected
    kb_id = "test-kb" # Using a dummy kb_id, assuming default dataset or similar behavior

    print(f"--- Query: {query} ---")
    
    # 1. Generate SPARQL using SPARQLGenerator (simulating logic in FusekiBackend.query)
    generator = SPARQLGenerator(
        api_key=settings.OPENAI_API_KEY,
        # ontology_schema="" # Removed as not in __init__
    )
    generator.llm_endpoint = "https://api.openai.com/v1/chat/completions" # ensuring default
    
    # Simulating the context provided to generator
    context = f"Entities: {', '.join(entities)}"
    
    print("\n[1] Generating SPARQL...")
    try:
        gen_result = generator.generate(
            question=query,
            context=context,
            mode="ontology",
            inverse_relation="auto"
        )
        generated_sparql = gen_result.get("sparql")
        print("\nGenerated SPARQL:")
        print(generated_sparql)
        
    except Exception as e:
        print(f"Error generating SPARQL: {e}")
        return

    # 2. Execute the generated SPARQL against Fuseki
    if generated_sparql:
        print("\n[2] Executing SPARQL against Fuseki...")
        
        # Ensure prefixes (simplified version of what backend does)
        prefixes = """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX ent: <http://rag.local/entity/>
        PREFIX rel: <http://rag.local/relation/>
        """
        
        full_query = prefixes + "\n" + generated_sparql
        
        # We need a valid KB ID that maps to a dataset. 
        # Assuming 'dkdoc7/RAGaaS' environment uses 'ds' or similar default if kb_id not found?
        # Actually fuseki_client uses kb_id to form dataset name.
        # Let's try to list datasets or use a known one. 
        # User mentioned "dkdoc7/RAGaaS", maybe just list datasets first to pick one?
        
        # For now, let's try to list datasets to find a valid one.
        try:
             # Just lists datasets, doesn't need kb_id
             # Wait, fuseki_client.list_datasets() is a guess. Let's look at available tools for fuseki.
             pass
        except:
            pass

        # Let's assume there is a dataset. In previous context, user used 'test-kb' or similar. 
        # I'll try to execute on the main dataset.
        
        # Actually, let's just run it. If it fails due to dataset, we'll see.
        # Execute
        full_query = prefixes + ("\nFROM <urn:x-arq:UnionGraph>\n" + generated_sparql if "WHERE" not in generated_sparql else generated_sparql.replace("WHERE", "FROM <urn:x-arq:UnionGraph>\nWHERE", 1))
        
        print(f"\n[2] executing query:\n{full_query}")

        # Fetch all datasets to find the right one
        import requests
        try:
            ds_resp = requests.get(f"{settings.FUSEKI_URL}/$/datasets", auth=('admin', 'admin'))
            datasets = [d['ds.name'][1:] for d in ds_resp.json()['datasets']] # remove leading /
        except:
            datasets = ["ds"]

        print(f"[3] Searching across {len(datasets)} datasets...")
        
        found = False
        for ds_name in datasets:
             # KB ID is part of dataset name usually: kb_UUID or just name. fuseki_client.query_sparql takes kb_id!
             # BUT fuseki_client.query_sparql calls _get_dataset_url which Prepends kb_ prefix if not present?
             # Actually `_get_dataset_url` does: `kb_{kb_id.replace('-', '_')}`
             
             # If dataset name is already `kb_...`, we need to pass the ID part or modify client usage.
             # The client method `query_sparql` constructs the URL. 
             # Let's verify `FusekiClient._get_dataset_url`:
             # safe_name = f"kb_{kb_id.replace('-', '_')}"
             # return f"{self.base_url}/{safe_name}"
             
             # So if ds_name is "kb_123", we should pass "123".
             if ds_name.startswith("kb_"):
                 kb_id_candidate = ds_name[3:]
             else:
                 kb_id_candidate = ds_name # Fallback, likely won't work with client helper but let's try direct request

             # Let's bypass the helper and use the dataset name directly for standard SparqlWrapper
             # Or just use the client if we extract the ID correctly.
             
             # Simple approach: Use raw SPARQLWrapper with direct URL
             from SPARQLWrapper import SPARQLWrapper, JSON
             
             endpoint = f"{settings.FUSEKI_URL}/{ds_name}/query"
             sparql = SPARQLWrapper(endpoint)
             sparql.setCredentials("admin", "admin")
             sparql.setQuery(full_query)
             sparql.setReturnFormat(JSON)
             
             try:
                 results = sparql.query().convert()
                 bindings = results.get("results", {}).get("bindings", [])
                 if bindings:
                     print(f"\nMATCH FOUND in dataset: {ds_name}")
                     # print(json.dumps(results, indent=2, ensure_ascii=False)) # Skipped to reduce noise
                     print("--- Results (Triples) ---")
                     for b in bindings:
                         items = []
                         for var in b:
                             items.append(f"{var} -> {b[var]['value']}")
                         print(" | ".join(items))
                     found = True
                     break
                 else:
                     # print(f" - No results in {ds_name}")
                     pass
             except Exception as e:
                 print(f"Error querying {ds_name}: {e}")
        
        if found:
            print("\nDONE: Found results.")
        else:
            print("\nDONE: No results found in any dataset.")

        return # End

if __name__ == "__main__":
    asyncio.run(test_sparql_generation_and_execution())
