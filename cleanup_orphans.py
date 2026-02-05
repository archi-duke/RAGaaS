
import asyncio
import os
import json
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.core.neo4j_client import neo4j_client
from app.core.fuseki import fuseki_client
from app.core.config import settings
import httpx

async def cleanup_orphans():
    print("="*50)
    print("🧹 Starting Orphan Data Cleanup")
    print("="*50)

    # 1. MongoDB Connect & Fetch Valid Docs
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(database=client.ragaas, document_models=[Document, KnowledgeBase])
    
    docs = await Document.find_all().to_list()
    valid_doc_ids = set([str(doc.id) for doc in docs])
    print(f"✅ Found {len(valid_doc_ids)} valid documents in MongoDB.")

    # 2. Cleanup Neo4j
    print("\n[Neo4j] Cleaning up orphaned relationships...")
    try:
        # Get all distinct doc_ids from Neo4j relationships not in INVERSE_OF
        # (Inverse relation might not have doc_id, but usually copies it)
        query_check_orphan = """
        MATCH ()-[r]->()
        WHERE r.doc_id IS NOT NULL
        RETURN DISTINCT r.doc_id as doc_id
        """
        records = neo4j_client.execute_query(query_check_orphan)
        neo4j_doc_ids = set([r["doc_id"] for r in records])
        
        orphan_neo4j = neo4j_doc_ids - valid_doc_ids
        
        if orphan_neo4j:
            print(f"⚠️ Found {len(orphan_neo4j)} orphaned doc_ids in Neo4j: {list(orphan_neo4j)[:5]}...")
            
            # Delete orphaned relationships
            # Batch deletion to be safe
            batch_size = 100
            orphan_list = list(orphan_neo4j)
            
            total_deleted = 0
            for i in range(0, len(orphan_list), batch_size):
                batch = orphan_list[i:i+batch_size]
                del_query = """
                MATCH ()-[r]->()
                WHERE r.doc_id IN $batch_ids
                DELETE r
                """
                neo4j_client.execute_query(del_query, {"batch_ids": batch})
                total_deleted += len(batch)
                print(f"   - Deleted relationships for {len(batch)} orphaned docs...")
            
            print(f"✅ [Neo4j] Deleted relationships for {total_deleted} orphaned documents.")
            
            # Delete isolated nodes (optional, but good for hygiene)
            clean_nodes_query = """
            MATCH (n)
            WHERE NOT (n)--()
            DELETE n
            """
            # neo4j_client.execute_query(clean_nodes_query) # Uncomment if safe
            # print("   - Deleted isolated nodes.")
            
        else:
            print("✅ [Neo4j] No orphaned relationships found.")

    except Exception as e:
        print(f"❌ [Neo4j] Error: {e}")

    # 3. Cleanup Fuseki (Named Graphs)
    print("\n[Fuseki] Cleaning up orphaned Named Graphs...")
    try:
        # Fuseki doesn't have a simple "LIST GRAPHS" API in python client wrapper usually,
        # but we can query standard SPARQL
        sparql_graphs = "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }"
        # We need to query across all datasets or specific one? 
        # Strategy: Iterate over KBs
        kbs = await KnowledgeBase.find_all().to_list()
        
        for kb in kbs:
            kb_id = str(kb.id)
            try:
                # Query graphs in this KB's dataset
                # Note: fuseki_client.query_sparql target dataset logic:
                # it uses "kb_{kb_id}"
                
                res = fuseki_client.query_sparql(kb_id, sparql_graphs)
                bindings = res.get("results", {}).get("bindings", [])
                
                graphs = [b["g"]["value"] for b in bindings]
                orphan_graphs = []
                
                for g in graphs:
                    if g.startswith("urn:doc:"):
                        doc_id = g.replace("urn:doc:", "")
                        if doc_id not in valid_doc_ids:
                            orphan_graphs.append(g)
                
                if orphan_graphs:
                    print(f"⚠️ [Fuseki] KB {kb_id}: Found {len(orphan_graphs)} orphaned graphs.")
                    for g in orphan_graphs:
                        # Drop Graph
                        update_sparql = f"DROP GRAPH <{g}>"
                        fuseki_client.update_sparql(kb_id, update_sparql)
                    print(f"   - Dropped {len(orphan_graphs)} graphs.")
                
                # Check Reification Orphans (meta:docId) in Default Graph or Union Graph
                # Reification usually lives in the same Named Graph as the triple, so DROP GRAPH handles it.
                # But if there are leaks in default graph:
                
                check_reif_orphan = f"""
                PREFIX meta: <http://rag.local/meta/>
                DELETE {{
                    ?stmt ?p ?o .
                }}
                WHERE {{
                    ?stmt meta:docId ?docId .
                    FILTER (?docId NOT IN ({', '.join([f'"{d}"' for d in valid_doc_ids])}))
                    ?stmt ?p ?o .
                }}
                """
                # This query might be too heavy if valid_doc_ids is huge.
                # Instead, select orphaned docIds first.
                
                select_orphan_reif = """
                PREFIX meta: <http://rag.local/meta/>
                SELECT DISTINCT ?docId WHERE {
                    ?stmt meta:docId ?docId .
                }
                """
                res = fuseki_client.query_sparql(kb_id, select_orphan_reif)
                found_doc_ids = [b["docId"]["value"] for b in res.get("results", {}).get("bindings", [])]
                
                orphan_reif_ids = [d for d in found_doc_ids if d not in valid_doc_ids]
                
                if orphan_reif_ids:
                    print(f"⚠️ [Fuseki] KB {kb_id}: Found {len(orphan_reif_ids)} orphaned reification docIds.")
                    for d_id in orphan_reif_ids:
                         # Delete all statements with this docId
                         del_reif = f"""
                         PREFIX meta: <http://rag.local/meta/>
                         DELETE {{ ?stmt ?p ?o }}
                         WHERE {{
                             ?stmt meta:docId "{d_id}" .
                             ?stmt ?p ?o .
                         }}
                         """
                         fuseki_client.update_sparql(kb_id, del_reif)
                    print(f"   - Deleted reification statements for orphaned docs.")

            except Exception as e:
                # Dataset might not exist
                pass

    except Exception as e:
        print(f"❌ [Fuseki] Error: {e}")

    print("\n✨ Cleanup Completed!")

if __name__ == "__main__":
    asyncio.run(cleanup_orphans())
