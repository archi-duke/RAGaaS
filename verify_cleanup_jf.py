
import asyncio
from app.core.milvus import create_collection, connect_milvus
from app.core.fuseki import fuseki_client
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_cleanup(kb_id):
    print(f"\n--- Checking Cleanup for KB: {kb_id} ---")
    
    # 1. Check Milvus
    try:
        connect_milvus()
        collection = create_collection(kb_id)
        collection.load()
        num_entities = collection.num_entities
        print(f"Milvus: {num_entities} entities remain in collection.")
    except Exception as e:
        print(f"Milvus Check Failed (Collection might not exist): {e}")

    # 2. Check Fuseki
    try:
        # Check total triples in KB
        query = "SELECT (COUNT(*) as ?count) WHERE { GRAPH ?g { ?s ?p ?o } }"
        res = fuseki_client.query_sparql(kb_id, query)
        count = res["results"]["bindings"][0]["count"]["value"]
        print(f"Fuseki: {count} total triples remain in all named graphs.")
        
        # Check specific named graphs for documents (if any left)
        query_graphs = "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } FILTER(STRSTARTS(STR(?g), 'urn:doc:')) }"
        res_graphs = fuseki_client.query_sparql(kb_id, query_graphs)
        graphs = [b["g"]["value"] for b in res_graphs["results"]["bindings"]]
        if graphs:
            print(f"Fuseki: Found {len(graphs)} internal document graphs remaining: {graphs}")
        else:
            print("Fuseki: No document-specific named graphs (urn:doc:*) remain.")
            
    except Exception as e:
        print(f"Fuseki Check Failed: {e}")

if __name__ == "__main__":
    kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
    asyncio.run(check_cleanup(kb_id))
