import os
import sys
from pymongo import MongoClient
from pymilvus import connections, Collection, utility

# 환경 변수 설정
MONGO_URI = os.getenv("MONGO_URI", "mongodb://root:example@localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ragaas")
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")

def check_kb_status(kb_name):
    # 1. MongoDB에서 KB ID 찾기
    try:
        client = MongoClient(MONGO_URI)
        db = client[MONGO_DB]
        kb = db.knowledge_bases.find_one({"name": kb_name})
        
        if not kb:
            print(f"❌ '{kb_name}' KB를 찾을 수 없습니다.")
            return
            
        kb_id = str(kb['_id'])
        print(f"✅ KB Found: {kb_name} (ID: {kb_id})")
        print(f"   Status: {kb.get('status')}")
        
    except Exception as e:
        print(f"❌ MongoDB 접속 실패: {e}")
        return

    # 2. Milvus 데이터 확인
    print(f"\n🔍 Milvus 데이터 확인 중... (KB ID: {kb_id})")
    try:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        
        if not utility.has_collection(collection_name):
            print(f"❌ Milvus 컬렉션을 찾을 수 없습니다: {collection_name}")
            print(f"   -> 원인: 문서 업로드 시점에 Milvus가 꺼져있어 데이터가 저장되지 않았을 가능성이 큽니다.")
            return

        collection = Collection(collection_name)
        collection.load()
        count = collection.num_entities
        print(f"✅ Milvus 컬렉션 발견: {collection_name}")
        print(f"📊 저장된 청크(Entity) 개수: {count}개")
        
        if count == 0:
            print("❌ 컬렉션은 있지만 데이터가 0개입니다.")
        else:
            print("✅ 데이터가 정상적으로 존재합니다. 방금 Milvus를 재시작했으므로 이제 화면에서 보일 것입니다.")
            
    except Exception as e:
        print(f"❌ Milvus 접속 또는 조회 실패: {e}")

if __name__ == "__main__":
    check_kb_status("test jf")
