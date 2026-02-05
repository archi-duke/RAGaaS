"""
Beanie를 사용하여 test jf KB의 청크 크기 업데이트
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings
from app.models.knowledge_base import KnowledgeBase

KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

async def update_chunk_size():
    print("=" * 70)
    print("📝 test jf KB 청크 크기 업데이트 (Beanie)")
    print("=" * 70)
    
    # MongoDB 연결
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(
        database=client[settings.MONGO_DB],
        document_models=[KnowledgeBase]
    )
    
    # KB 조회
    print("\n[1] 현재 설정:")
    kb = await KnowledgeBase.get(KB_ID)
    if not kb:
        print("  ❌ KB를 찾을 수 없습니다.")
        return
    
    current_size = kb.chunking_config.get('chunk_size', 'N/A')
    print(f"  현재 chunk_size: {current_size}")
    
    # 업데이트
    print("\n[2] chunk_size를 500으로 업데이트:")
    kb.chunking_config['chunk_size'] = 500
    await kb.save()
    print(f"  ✅ 업데이트 완료")
    
    # 확인
    print("\n[3] 업데이트 확인:")
    kb = await KnowledgeBase.get(KB_ID)
    new_size = kb.chunking_config.get('chunk_size', 'N/A')
    print(f"  새로운 chunk_size: {new_size}")
    
    if new_size == 500:
        print(f"\n✅ 청크 크기가 500으로 성공적으로 변경되었습니다!")
    else:
        print(f"\n⚠️  예상과 다른 값: {new_size}")
    
    print("\n" + "=" * 70)
    print("⚠️  주의사항:")
    print("  - 이미 업로드된 문서는 영향을 받지 않습니다.")
    print("  - 새로운 청크 크기는 앞으로 업로드되는 문서에만 적용됩니다.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(update_chunk_size())
