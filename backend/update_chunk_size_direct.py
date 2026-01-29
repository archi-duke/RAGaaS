"""
MongoDB에서 직접 test jf KB의 청크 크기를 500으로 업데이트
"""
import sys
sys.path.insert(0, '/app')

from pymongo import MongoClient
from app.core.config import settings

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

print("=" * 70)
print("📝 test jf KB 청크 크기 직접 업데이트 (MongoDB)")
print("=" * 70)

client = MongoClient(settings.MONGO_URI)
db = client[settings.MONGO_DB]

# 현재 설정 확인
print("\n[1] 현재 설정:")
kb = db.knowledge_bases.find_one({"id": KB_ID})
if kb:
    current_size = kb['chunking_config']['chunk_size']
    print(f"  현재 chunk_size: {current_size}")
else:
    print("  ❌ KB를 찾을 수 없습니다.")
    exit(1)

# 업데이트
print("\n[2] chunk_size를 500으로 업데이트:")
result = db.knowledge_bases.update_one(
    {"id": KB_ID},
    {"$set": {"chunking_config.chunk_size": 500}}
)

if result.modified_count > 0:
    print(f"  ✅ 업데이트 성공 ({result.modified_count}개 문서 수정)")
else:
    print(f"  ⚠️  수정된 문서 없음 (이미 500일 수 있음)")

# 확인
print("\n[3] 업데이트 확인:")
kb = db.knowledge_bases.find_one({"id": KB_ID})
new_size = kb['chunking_config']['chunk_size']
print(f"  새로운 chunk_size: {new_size}")

if new_size == 500:
    print(f"\n✅ 청크 크기가 500으로 성공적으로 변경되었습니다!")
else:
    print(f"\n⚠️  예상과 다른 값: {new_size}")

client.close()

print("\n" + "=" * 70)
print("⚠️  주의사항:")
print("  - 이미 업로드된 문서는 영향을 받지 않습니다.")
print("  - 새로운 청크 크기는 앞으로 업로드되는 문서에만 적용됩니다.")
print("=" * 70)
