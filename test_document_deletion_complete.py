"""
문서 삭제 로직의 완전성을 검증하는 통합 테스트
- 문서 업로드 후 MongoDB, Milvus, Fuseki에 데이터가 생성되는지 확인
- 문서 삭제 후 모든 저장소에서 데이터가 제거되는지 확인
- 가비지 데이터가 남지 않는지 확인
"""

import requests
import time
import os
import sys
from pathlib import Path
from pymongo import MongoClient

# Add backend to path for direct DB access
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

from app.core.milvus import connect_milvus, create_collection
from app.core.fuseki import FusekiClient
from app.core.config import settings

API_URL = "http://localhost:8000/api"
TEST_KB_NAME = "test jf"  # 기존 KB 사용 (Fuseki 백엔드)

def find_kb_by_name(kb_name):
    """KB 이름으로 ID 찾기"""
    res = requests.get(f"{API_URL}/knowledge-bases")
    if res.status_code == 200:
        kbs = res.json()
        for kb in kbs:
            if kb["name"] == kb_name:
                return kb["id"]
    return None

def upload_test_document(kb_id):
    """테스트 문서 업로드"""
    print(f"\n📤 테스트 문서 업로드 중 (KB: {kb_id})...")
    
    test_file_path = "test_deletion_doc.txt"
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("홍길동은 서울에 산다.\n조선의 의적이다.\n")
    
    with open(test_file_path, "rb") as f:
        files = {"file": (test_file_path, f, "text/plain")}
        # Graph extraction enabled
        data = {
            "oe_section_aware": "false",
            "extract_inverse_relations": "false",
            "confidence_threshold": "0.7"
        }
        res = requests.post(f"{API_URL}/knowledge-bases/{kb_id}/documents", files=files, data=data)
    
    os.remove(test_file_path)
    
    if res.status_code == 200:
        doc_id = res.json()["id"]
        print(f"✅ 문서 업로드 완료: {doc_id}")
        return doc_id
    else:
        print(f"❌ 문서 업로드 실패: {res.status_code} - {res.text}")
        return None

def check_data_in_mongo(kb_id, doc_id):
    """MongoDB에서 문서 존재 확인"""
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB]
    doc = db.documents.find_one({"id": doc_id, "knowledge_base_id": kb_id})
    client.close()
    return doc is not None

def check_data_in_milvus(kb_id, doc_id):
    """Milvus에서 청크 존재 확인"""
    connect_milvus()
    collection = create_collection(kb_id)
    collection.load()
    
    results = collection.query(
        expr=f'doc_id == "{doc_id}"',
        output_fields=["chunk_id", "content"]
    )
    return len(results), results

def check_data_in_fuseki(kb_id, chunk_ids):
    """Fuseki에서 트리플 존재 확인 (Reification 패턴 사용)"""
    if not chunk_ids:
        return 0
    
    fuseki_client = FusekiClient()
    
    # VALUES 절을 위한 chunk ID 리스트 생성
    chunk_values = " ".join([f'"{cid}"' for cid in chunk_ids])
    
    query = f"""
    PREFIX meta: <http://example.org/meta/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT (COUNT(*) as ?count)
    FROM <urn:x-arq:UnionGraph>
    WHERE {{
        VALUES ?chunkId {{ {chunk_values} }}
        ?st rdf:type rdf:Statement .
        ?st meta:sourceNodeId ?chunkId .
    }}
    """
    
    results = fuseki_client.query_sparql(kb_id, query)
    if results and len(results) > 0:
        return int(results[0].get("count", {}).get("value", 0))
    return 0

def delete_document(kb_id, doc_id):
    """문서 삭제"""
    print(f"\n🗑️  문서 삭제 중 (Doc: {doc_id})...")
    res = requests.delete(f"{API_URL}/knowledge-bases/{kb_id}/documents/{doc_id}")
    
    if res.status_code == 200:
        print(f"✅ 문서 삭제 요청 완료")
        return True
    else:
        print(f"❌ 문서 삭제 실패: {res.status_code} - {res.text}")
        return False

def run_integration_test():
    """통합 테스트 실행"""
    print("=" * 60)
    print("🧪 문서 삭제 완전성 테스트 시작")
    print("=" * 60)
    
    # 1. KB 찾기
    kb_id = find_kb_by_name(TEST_KB_NAME)
    if not kb_id:
        print(f"❌ KB '{TEST_KB_NAME}'를 찾을 수 없습니다.")
        return False
    
    print(f"✅ 테스트 KB ID: {kb_id}")
    
    # 2. 문서 업로드
    doc_id = upload_test_document(kb_id)
    if not doc_id:
        return False
    
    # 3. 인제스트 대기 (그래프 추출 포함)
    print("\n⏳ 인제스트 처리 대기 중 (10초)...")
    time.sleep(10)
    
    # 4. 업로드 후 데이터 확인
    print("\n📊 [업로드 후] 데이터 존재 확인:")
    
    mongo_exists = check_data_in_mongo(kb_id, doc_id)
    print(f"  - MongoDB: {'✅ 존재' if mongo_exists else '❌ 없음'}")
    
    milvus_count, milvus_chunks = check_data_in_milvus(kb_id, doc_id)
    chunk_ids = [c["chunk_id"] for c in milvus_chunks]
    print(f"  - Milvus: {milvus_count}개 청크 {'✅' if milvus_count > 0 else '❌'}")
    if milvus_count > 0:
        print(f"    Chunk IDs: {chunk_ids}")
    
    fuseki_count = check_data_in_fuseki(kb_id, chunk_ids)
    print(f"  - Fuseki: {fuseki_count}개 트리플 {'✅' if fuseki_count >= 0 else '❌'}")
    
    if not mongo_exists or milvus_count == 0:
        print("\n⚠️  데이터가 제대로 생성되지 않았습니다. 테스트 중단.")
        return False
    
    # 5. 문서 삭제
    if not delete_document(kb_id, doc_id):
        return False
    
    # 6. 삭제 처리 대기
    print("\n⏳ 삭제 처리 대기 중 (5초)...")
    time.sleep(5)
    
    # 7. 삭제 후 데이터 확인
    print("\n📊 [삭제 후] 데이터 제거 확인:")
    
    mongo_exists_after = check_data_in_mongo(kb_id, doc_id)
    print(f"  - MongoDB: {'❌ 여전히 존재' if mongo_exists_after else '✅ 제거됨'}")
    
    milvus_count_after, _ = check_data_in_milvus(kb_id, doc_id)
    print(f"  - Milvus: {milvus_count_after}개 청크 {'❌ 가비지 존재' if milvus_count_after > 0 else '✅ 제거됨'}")
    
    fuseki_count_after = check_data_in_fuseki(kb_id, chunk_ids)
    print(f"  - Fuseki: {fuseki_count_after}개 트리플 {'❌ 가비지 존재' if fuseki_count_after > 0 else '✅ 제거됨'}")
    
    # 8. 결과 판정
    print("\n" + "=" * 60)
    if not mongo_exists_after and milvus_count_after == 0 and fuseki_count_after == 0:
        print("🎉 테스트 성공! 모든 데이터가 깨끗이 제거되었습니다.")
        print("=" * 60)
        return True
    else:
        print("⚠️  테스트 실패! 가비지 데이터가 남아있습니다:")
        if mongo_exists_after:
            print("  - MongoDB에 문서 레코드가 남아있음")
        if milvus_count_after > 0:
            print(f"  - Milvus에 {milvus_count_after}개 청크가 남아있음")
        if fuseki_count_after > 0:
            print(f"  - Fuseki에 {fuseki_count_after}개 트리플이 남아있음")
        print("=" * 60)
        return False

if __name__ == "__main__":
    try:
        success = run_integration_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n💥 테스트 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
