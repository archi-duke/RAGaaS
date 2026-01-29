
import asyncio
from app.core.fuseki import fuseki_client
from app.core.neo4j_client import neo4j_client
from app.models.knowledge_base import KnowledgeBase
from app.core.database import init_db

async def check_data():
    await init_db()
    
    # 1. Fuseki (test jf) 확인
    print("--- [1] Checking Fuseki (test jf) ---")
    jf_kb = await KnowledgeBase.find_one(KnowledgeBase.name == "test jf")
    if jf_kb:
        kb_id = jf_kb.id
        print(f"KB ID: {kb_id}")
        query = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?sLabel ?p ?oLabel
        WHERE {
            ?s rdfs:label ?sLabel .
            ?s ?p ?o .
            ?o rdfs:label ?oLabel .
            FILTER(CONTAINS(LCASE(?sLabel), "성기훈"))
        }
        """
        try:
            res = fuseki_client.query_sparql(kb_id, query)
            bindings = res.get("results", {}).get("bindings", [])
            print(f"Found {len(bindings)} triples for '성기훈':")
            for b in bindings:
                p = b['p']['value'].split('/')[-1].replace('rel:', '').replace('prop:', '')
                o = b['oLabel']['value']
                print(f"  - has_{p} -> {o}")
                if "후배" in p or "제자" in p or "후배" in o or "제자" in o:
                    print(f"    🌟 [MATCH!] Found relevant relation: {p} -> {o}")
        except Exception as e:
            print(f"Error querying Fuseki: {e}")
    else:
        print("Knowledge Base 'test jf' not found.")

    print("\n" + "="*50 + "\n")

    # 2. Neo4j (test) 확인
    print("--- [2] Checking Neo4j (test) ---")
    neo_kb = await KnowledgeBase.find_one(KnowledgeBase.name == "test")
    if neo_kb:
        kb_id = neo_kb.id
        print(f"KB ID: {kb_id}")
        query = """
        MATCH (s:Entity)-[r]->(o:Entity)
        WHERE s.kb_id = $kb_id AND s.name CONTAINS '성기훈'
        RETURN type(r) as p, o.name as o
        """
        try:
            res = neo4j_client.execute_query(query, {"kb_id": kb_id})
            print(f"Found {len(res)} triples for '성기훈':")
            for r in res:
                p = r['p']
                o = r['o']
                print(f"  - {p} -> {o}")
                if "후배" in p or "제자" in p or "후배" in o or "제자" in o:
                    print(f"    🌟 [MATCH!] Found relevant relation: {p} -> {o}")
        except Exception as e:
            print(f"Error querying Neo4j: {e}")
    else:
        print("Knowledge Base 'test' not found.")

if __name__ == "__main__":
    asyncio.run(check_data())
