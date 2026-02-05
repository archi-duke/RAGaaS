
import asyncio
from pymilvus import connections, Collection, utility
from app.core.database import SessionLocal
from app.models.document import Document
from app.core.neo4j_client import neo4j_client
from sqlalchemy import select

async def cleanup_orphaned_data():
    print("[GC] Starting Garbage Collection...")
    
    # 1. 존재하는 모든 KB ID와 Doc ID 가져오기
    kb_ids = []
    valid_docs = {}  # kb_id -> set(doc_ids)
    
    async with SessionLocal() as db:
        # 모든 문서 조회
        result = await db.execute(select(Document.id, Document.kb_id))
        rows = result.fetchall()
        
        for doc_id, kb_id in rows:
            if kb_id not in valid_docs:
                valid_docs[kb_id] = set()
            valid_docs[kb_id].add(doc_id)
            
    print(f"[GC] Found {sum(len(s) for s in valid_docs.values())} valid documents across {len(valid_docs)} KBs.")

    # 2. Milvus 정리
    try:
        connections.connect("default", host="milvus-standalone", port="19530")
        collections = utility.list_collections()
        
        for col_name in collections:
            if not col_name.startswith("kb_"):
                continue
                
            kb_id = col_name.replace("kb_", "").replace("_", "-") # 간단한 파싱 (정확하지 않을 수 있음)
            # 정확한 파싱: kb_UUID 형식
            try:
                # UUID 형식 검증 대충 (36자)
                if len(kb_id) != 36:
                     # _가 -로 변환될 때의 모호성 때문에 정확한 ID 복원 어려울 수 있음
                     # 여기서는 collection 내의 doc_id가 valid_docs에 있는지 확인할 것임
                     pass
            except:
                pass
            
            print(f"[GC] Checking Milvus collection: {col_name}")
            col = Collection(col_name)
            col.load()
            
            # 모든 doc_id 조회
            results = col.query(expr='chunk_id != ""', output_fields=["doc_id"])
            chunk_doc_ids = set([r["doc_id"] for r in results])
            
            # 이 컬렉션이 속한 KB의 유효 문서 목록 (모르면 전체 문서 목록에서 찾음 - 안전하게)
            # 사실 doc_id는 global unique하므로 전체 valid_docs 값들의 합집합과 비교하면 됨
            all_valid_doc_ids = set().union(*valid_docs.values())
            
            orphaned_docs = chunk_doc_ids - all_valid_doc_ids
            
            if orphaned_docs:
                print(f"[GC] Found {len(orphaned_docs)} orphaned docs in {col_name}: {orphaned_docs}")
                expr = f'doc_id in {list(orphaned_docs)}'
                # 리스트가 문자열로 변환될 때 따옴표 문제 주의: JSON dumps 사용
                import json
                expr = f'doc_id in {json.dumps(list(orphaned_docs))}'
                
                col.delete(expr)
                col.flush()
                print(f"[GC] Deleted orphaned chunks.")
            else:
                print(f"[GC] No orphaned chunks found.")
                
    except Exception as e:
        print(f"[GC] Milvus error: {e}")

    # 3. Neo4j 정리 (KB 단위가 아니라 전체 노드 스캔 필요할 수도 있지만, kb_id 속성 활용)
    # KB 자체가 삭제되었는데 노드가 남은 경우도 있을 수 있음
    try:
        # DB에 존재하는 KB 목록
        valid_kb_ids = list(valid_docs.keys())
        
        if not valid_kb_ids:
             print("[GC] No valid KBs found. Skipping Neo4j safety check to avoid deleting everything.")
        else:
            # 1. 존재하지 않는 KB의 노드 삭제
            # query = f"MATCH (n:Entity) WHERE NOT n.kb_id IN {json.dumps(valid_kb_ids)} DETACH DELETE n"
            # neo4j_client.execute_query(query) 
            # -> 이건 너무 위험할 수 있으니 패스 (KB 삭제 로직은 별도라고 가정)
            pass
            
            # 2. 존재하는 KB 내에서, 존재하지 않는 문서의 노드 삭제?
            # Neo4j 노드에는 doc_id가 없음! (TripleChunkMapping에만 있음)
            # 따라서 TripleChunkMapping 테이블 정리 -> 그에 따른 Neo4j 정리 필요
            pass
            
    except Exception as e:
        print(f"[GC] Neo4j error: {e}")

if __name__ == "__main__":
    asyncio.run(cleanup_orphaned_data())
