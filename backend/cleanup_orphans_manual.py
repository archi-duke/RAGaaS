
import asyncio
import os
import sys

# Add backend directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.core.neo4j_client import neo4j_client
from app.core.fuseki import fuseki_client
from app.core.config import settings

async def cleanup_orphans():
    print("="*50)
    print("🧹 Starting Orphan Data Cleanup")
    print("="*50)

    # 1. MongoDB Connect & Fetch Valid Docs
    print(f"[MongoDB] Connecting to {settings.MONGO_URI}...")
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(database=client.ragaas, document_models=[Document, KnowledgeBase])
    
    docs = await Document.find_all().to_list()
    valid_doc_ids = set([str(doc.id) for doc in docs])
    print(f"✅ Found {len(valid_doc_ids)} valid documents in MongoDB.")

    # 2. Cleanup Neo4j
    print("\n[Neo4j] Cleaning up orphaned relationships...")
    try:
        # Get all distinct doc_ids from Neo4j relationships not in INVERSE_OF
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
            
            # Batch deletion
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
        else:
            print("✅ [Neo4j] No orphaned relationships found.")

    except Exception as e:
        print(f"❌ [Neo4j] Error: {e}")

    # 3. Cleanup Fuseki
    print("\n[Fuseki] Cleaning up orphaned Named Graphs...")
    try:
        # Strategy: Iterate over KBs to find datasets
        kbs = await KnowledgeBase.find_all().to_list()
        
        sparql_graphs = "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }"
        
        for kb in kbs:
            kb_id = str(kb.id)
            try:
                # 1. Check Named Graphs (urn:doc:...)
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
                        update_sparql = f"DROP GRAPH <{g}>"
                        fuseki_client.update_sparql(kb_id, update_sparql)
                    print(f"   - Dropped {len(orphan_graphs)} graphs.")
                
                # 2. Check Reification Orphans (meta:docId) via SELECT first (safer)
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
                    
                    # Delete by docId
                    # Batch if necessary, but update_sparql handles reasonably sized updates
                    for d_id in orphan_reif_ids:
                         del_reif = f"""
                         PREFIX meta: <http://rag.local/meta/>
                         DELETE {{ ?stmt ?p ?o }}
                         WHERE {{
                             ?stmt meta:docId "{d_id}" .
                             ?stmt ?p ?o .
                         }}
                         """
                         fuseki_client.update_sparql(kb_id, del_reif)
                    print(f"   - Deleted reification statements for {len(orphan_reif_ids)} orphaned docs.")

            except Exception as e:
                # print(f"   - KB {kb_id} access failed (might not have dataset): {e}")
                pass

    except Exception as e:
        print(f"❌ [Fuseki] Error: {e}")

    print("\n✨ Cleanup Completed!")

if __name__ == "__main__":
    asyncio.run(cleanup_orphans())
