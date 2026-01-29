
import asyncio
from app.core.fuseki import fuseki_client
from app.core.neo4j_client import neo4j_client
from app.models.knowledge_base import KnowledgeBase
from app.core.database import init_db

async def check_data():
    await init_db()
    
    # 1. Fuseki (test jf) 확인
    print("\n" + "="*50)
    print("--- [1] Checking Fuseki (Name: 'test jf') ---")
    jf_kb = await KnowledgeBase.find_one(KnowledgeBase.name == "test jf")
    if jf_kb:
        kb_id = jf_kb.id
        print(f"KB ID: {kb_id}")
        
        # 더 포괄적인 SPARQL (URI 자체 매칭 또는 Label 매칭)
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?s ?p ?o ?sLabel ?oLabel
        WHERE {{
            {{
                ?s ?p ?o .
                ?s rdfs:label ?sLabel .
                FILTER(CONTAINS(LCASE(?sLabel), "성기훈"))
            }}
            UNION
            {{
                ?s ?p ?o .
                FILTER(CONTAINS(LCASE(STR(?s)), "성기훈"))
            }}
            OPTIONAL {{ ?o rdfs:label ?oLabel }}
        }}
        LIMIT 50
        """
        try:
            res = fuseki_client.query_sparql(kb_id, query)
            bindings = res.get("results", {}).get("bindings", [])
            print(f"Found {len(bindings)} triples for '성기훈':")
            for b in bindings:
                s_val = b.get('sLabel', {}).get('value', 'NoLabel')
                if s_val == 'NoLabel':
                    s_val = b['s']['value'].split('/')[-1]
                
                p_val = b['p']['value'].split('/')[-1].replace('rel:', '').replace('prop:', '')
                
                o_val = b.get('oLabel', {}).get('value', 'NoLabel')
                if o_val == 'NoLabel':
                    if b['o']['type'] == 'uri':
                        o_val = b['o']['value'].split('/')[-1]
                    else:
                        o_val = b['o']['value']

                print(f"  - [{s_val}] --({p_val})--> [{o_val}]")
                if any(x in p_val or x in o_val for x in ["후배", "제자", "junior", "student"]):
                    print(f"    🌟 [Fuseki MATCH!] Found relevant relation!")
        except Exception as e:
            print(f"Error querying Fuseki: {e}")
    else:
        print("Knowledge Base 'test jf' not found.")


    # 2. Neo4j (test n4) 확인
    print("\n" + "="*50)
    print("--- [2] Checking Neo4j (Name: 'test n4') ---")
    neo_kb = await KnowledgeBase.find_one(KnowledgeBase.name == "test n4")
    if neo_kb:
        kb_id = neo_kb.id
        print(f"KB ID: {kb_id}")
        query = """
        MATCH (s:Entity)-[r]->(o:Entity)
        WHERE s.kb_id = $kb_id AND (s.name CONTAINS '성기훈' OR s.label_ko CONTAINS '성기훈')
        RETURN s.name as s, type(r) as p, o.name as o
        LIMIT 50
        """
        try:
            res = neo4j_client.execute_query(query, {"kb_id": kb_id})
            print(f"Found {len(res)} triples for '성기훈':")
            for r in res:
                s = r['s']
                p = r['p']
                o = r['o']
                print(f"  - [{s}] --({p})--> [{o}]")
                if any(x in p or x in o for x in ["후배", "제자", "junior", "student"]):
                     print(f"    🌟 [Neo4j MATCH!] Found relevant relation!")
        except Exception as e:
            print(f"Error querying Neo4j: {e}")
    else:
        print("Knowledge Base 'test n4' not found.")

if __name__ == "__main__":
    asyncio.run(check_data())
