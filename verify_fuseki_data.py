import httpx
import asyncio

FUSEKI_URL = "http://localhost:3030"
KB_ID = "49d09a72-3aac-457b-8340-c15983dd8f98"
DOC_ID = "fb45d29a-3bfc-4cc9-adf7-fc240e6d5281"

async def main():
    dataset_name = f"kb_{KB_ID.replace('-', '_')}"
    graph_uri = f"urn:doc:{DOC_ID}"
    
    query = f"""
    SELECT ?s ?p ?o
    WHERE {{
        GRAPH <{graph_uri}> {{
            ?s ?p ?o
        }}
    }}
    LIMIT 10
    """
    
    print(f"Querying Fuseki dataset: {dataset_name}")
    print(f"Graph URI: {graph_uri}")
    
    async with httpx.AsyncClient() as client:
        try:
            # 1. Check dataset existence
            resp = await client.get(f"{FUSEKI_URL}/$/datasets/{dataset_name}", auth=("admin", "admin"))
            if resp.status_code != 200:
                print(f"Dataset not found: {resp.status_code}")
                return

            # 2. Execute SPARQL query
            resp = await client.post(
                f"{FUSEKI_URL}/{dataset_name}/query",
                data={"query": query},
                auth=("admin", "admin")
            )
            
            if resp.status_code == 200:
                results = resp.json()
                bindings = results["results"]["bindings"]
                print(f"\nFound {len(bindings)} triples (limit 10):")
                for b in bindings:
                    s = b['s']['value']
                    p = b['p']['value']
                    o = b['o']['value']
                    print(f"{s}  --[{p}]-->  {o}")
            else:
                print(f"Query failed: {resp.status_code} {resp.text}")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
