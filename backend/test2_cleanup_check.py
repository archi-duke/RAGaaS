from pymilvus import connections, utility, Collection
from app.core.fuseki import fuseki_client
import asyncio

async def check_garbage(kb_id):
    print(f"--- Checking Garbage for KB: {kb_id} ---")
    
    # Check Milvus
    connections.connect(host='standalone', port='19530')
    col_name = f"kb_{kb_id.replace('-', '_')}"
    if utility.has_collection(col_name):
        col = Collection(col_name)
        col.load()
        count = col.num_entities
        print(f"Milvus Collection '{col_name}' exists. Entity Count: {count}")
    else:
        print(f"Milvus Collection '{col_name}' does not exist.")
        
    # Check Fuseki
    query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }"
    try:
        res = fuseki_client.query_sparql(kb_id, query)
        if res:
            count = res['results']['bindings'][0]['count']['value']
            print(f"Fuseki Dataset exists. Triple Count: {count}")
            
            if int(count) > 0:
                print("Triples Sample:")
                q2 = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5"
                res2 = fuseki_client.query_sparql(kb_id, q2)
                for b in res2['results']['bindings']:
                    print(f"  {b['s']['value']} {b['p']['value']} {b['o']['value']}")
        else:
            print("Fuseki Dataset does not exist or empty.")
    except Exception as e:
        print(f"Fuseki Check Failed: {e}")

if __name__ == "__main__":
    kb_id = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
    asyncio.run(check_garbage(kb_id))
