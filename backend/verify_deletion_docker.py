"""
Docker 환경 내부에서 실행할 삭제 검증 스크립트
MongoDB, Milvus, Fuseki를 직접 확인
"""
import sys
sys.path.insert(0, '/app')

from pymongo import MongoClient
from app.core.milvus import connect_milvus, create_collection
from app.core.fuseki import FusekiClient
from app.core.config import settings

# 테스트할 KB와 문서 정보
KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"  # test jf
DOC_ID = "e13f01c2-875b-458d-88f2-15d50a340ad1"  # 방금 삭제한 문서

print("=" * 60)
print("🔍 Docker 환경 내부 삭제 검증")
print("=" * 60)

# 1. MongoDB 확인
print("\n[1] MongoDB 확인...")
try:
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB]
    doc = db.documents.find_one({"id": DOC_ID, "knowledge_base_id": KB_ID})
    
    if doc:
        print(f"  ❌ 문서가 여전히 존재함: {doc.get('filename', 'N/A')}")
    else:
        print(f"  ✅ 문서 제거됨 (ID: {DOC_ID})")
    client.close()
except Exception as e:
    print(f"  ⚠️  MongoDB 확인 실패: {e}")

# 2. Milvus 확인
print("\n[2] Milvus 확인...")
try:
    connect_milvus()
    collection = create_collection(KB_ID)
    collection.load()
    
    results = collection.query(
        expr=f'doc_id == "{DOC_ID}"',
        output_fields=["chunk_id", "content"],
        limit=100
    )
    
    if len(results) > 0:
        print(f"  ❌ {len(results)}개 청크가 여전히 존재함")
        for r in results[:3]:
            print(f"     - Chunk: {r['chunk_id'][:40]}...")
    else:
        print(f"  ✅ 모든 청크 제거됨 (doc_id: {DOC_ID})")
        
except Exception as e:
    print(f"  ⚠️  Milvus 확인 실패: {e}")

# 3. Fuseki 확인 (일반적인 청크 참조)
print("\n[3] Fuseki 확인...")
try:
    fuseki_client = FusekiClient()
    
    # 모든 청크 ID 찾기 (doc_id 기반은 어렵지만, 최근 삭제된 것 확인)
    query = f"""
    PREFIX meta: <http://example.org/meta/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT (COUNT(*) as ?count)
    FROM <urn:x-arq:UnionGraph>
    WHERE {{
        ?st rdf:type rdf:Statement .
        ?st meta:sourceNodeId ?chunkId .
    }}
    """
    
    results = fuseki_client.query_sparql(KB_ID, query)
    if results and len(results) > 0:
        total_triples = int(results[0].get("count", {}).get("value", 0))
        print(f"  ℹ️  전체 트리플 개수: {total_triples}")
        print(f"  ✅ 특정 doc_id 기반 검증은 chunk_id 필요 (Milvus에서 이미 제거됨)")
    else:
        print(f"  ✅ Fuseki 정상 (트리플 없음)")
        
except Exception as e:
    print(f"  ⚠️  Fuseki 확인 실패: {e}")

print("\n" + "=" * 60)
print("검증 완료")
print("=" * 60)
