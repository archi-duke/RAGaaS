"""
test jf KB의 가비지 청크 정리
MongoDB에 없는 문서의 청크를 Milvus에서 삭제
"""
import sys
sys.path.insert(0, '/app')

from pymongo import MongoClient
from app.core.milvus import connect_milvus, create_collection
from app.core.fuseki import FusekiClient
from app.core.config import settings

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"  # test jf

print("=" * 70)
print("🧹 test jf KB 가비지 청크 정리")
print("=" * 70)

# 1. MongoDB에서 유효한 문서 ID 목록 가져오기
print("\n[1] MongoDB에서 유효한 문서 ID 조회...")
valid_doc_ids = set()
try:
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB]
    docs = list(db.documents.find({"knowledge_base_id": KB_ID}))
    valid_doc_ids = {doc['id'] for doc in docs}
    print(f"  유효한 문서: {len(valid_doc_ids)}개")
    client.close()
except Exception as e:
    print(f"  ❌ 실패: {e}")
    exit(1)

# 2. Milvus에서 모든 청크 조회
print("\n[2] Milvus에서 모든 청크 조회...")
orphaned_chunks = []
try:
    connect_milvus()
    collection = create_collection(KB_ID)
    collection.load()
    
    all_chunks = collection.query(
        expr="id > 0",
        output_fields=["doc_id", "chunk_id"],
        limit=10000
    )
    
    print(f"  전체 청크: {len(all_chunks)}개")
    
    # 가비지 청크 식별
    for chunk in all_chunks:
        doc_id = chunk.get('doc_id')
        if doc_id not in valid_doc_ids:
            orphaned_chunks.append(chunk)
    
    print(f"  가비지 청크: {len(orphaned_chunks)}개")
    
except Exception as e:
    print(f"  ❌ 실패: {e}")
    exit(1)

# 3. 가비지 청크 삭제
if orphaned_chunks:
    print(f"\n[3] {len(orphaned_chunks)}개 가비지 청크 삭제 중...")
    
    # doc_id별로 그룹화
    orphaned_doc_ids = set(chunk['doc_id'] for chunk in orphaned_chunks)
    print(f"  가비지 문서 ID: {orphaned_doc_ids}")
    
    try:
        for doc_id in orphaned_doc_ids:
            # Milvus에서 삭제
            expr = f'doc_id == "{doc_id}"'
            collection.delete(expr)
            print(f"    ✅ Milvus에서 삭제: {doc_id}")
        
        collection.flush()
        print(f"  ✅ Milvus flush 완료")
        
        # Fuseki에서도 삭제 (chunk_id 기반)
        chunk_ids = [chunk['chunk_id'] for chunk in orphaned_chunks]
        if chunk_ids:
            print(f"\n[4] Fuseki에서 {len(chunk_ids)}개 청크 참조 삭제 중...")
            fuseki_client = FusekiClient()
            
            # 배치로 삭제
            batch_size = 50
            for i in range(0, len(chunk_ids), batch_size):
                batch = chunk_ids[i:i+batch_size]
                quoted_ids = " ".join([f'"{cid}"' for cid in batch])
                
                delete_query = f"""
                PREFIX meta: <http://example.org/meta/>
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                
                DELETE {{ 
                    ?stmt ?p ?o .
                }}
                WHERE {{
                    VALUES ?chunkId {{ {quoted_ids} }}
                    ?stmt meta:sourceNodeId ?chunkId .
                    ?stmt ?p ?o .
                }}
                """
                
                try:
                    fuseki_client.update_sparql(KB_ID, delete_query)
                    print(f"    ✅ Fuseki 배치 {i//batch_size + 1} 삭제 완료")
                except Exception as e:
                    print(f"    ⚠️  Fuseki 배치 {i//batch_size + 1} 실패: {e}")
        
    except Exception as e:
        print(f"  ❌ 삭제 실패: {e}")
        exit(1)
    
    print("\n✅ 가비지 정리 완료!")
else:
    print("\n✅ 가비지 청크가 없습니다.")

# 4. 최종 확인
print("\n[5] 정리 후 상태 확인...")
try:
    collection.load()
    remaining = collection.query(
        expr="id > 0",
        output_fields=["doc_id"],
        limit=10000
    )
    print(f"  남은 청크: {len(remaining)}개")
except Exception as e:
    print(f"  ❌ 확인 실패: {e}")

print("\n" + "=" * 70)
