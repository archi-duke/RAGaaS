"""
DB에 저장된 SPARQL 생성 프롬프트를 새 Vibe 형식으로 업데이트하는 스크립트
"""
import asyncio
import os
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def update_prompts():
    # MongoDB 연결
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://root:example@localhost:27017")
    mongo_db = os.environ.get("MONGO_DB", "ragaas")
    
    client = AsyncIOMotorClient(mongo_uri)
    db = client[mongo_db]
    prompts_collection = db["prompts"]
    
    # 새 프롬프트 내용 읽기
    vibe_prompt_path = Path("backend/data/prompts/sparql_vibe_prompt.txt")
    if not vibe_prompt_path.exists():
        print(f"❌ 프롬프트 파일을 찾을 수 없습니다: {vibe_prompt_path}")
        return
    
    new_content = vibe_prompt_path.read_text(encoding="utf-8")
    
    # 기존 프롬프트 찾기
    existing = await prompts_collection.find_one({"name": "sparql_generation_prompt"})
    
    if existing:
        print(f"✅ 기존 프롬프트 발견: {existing['name']}")
        print(f"   - Version: {existing.get('version', 'N/A')}")
        print(f"   - Content 길이: {len(existing.get('content', ''))} chars")
        
        # 업데이트
        result = await prompts_collection.update_one(
            {"name": "sparql_generation_prompt"},
            {
                "$set": {
                    "content": new_content,
                    "version": "2.0-vibe",
                    "type": "sparql_generation"
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"\n🎉 프롬프트가 성공적으로 업데이트되었습니다!")
            print(f"   - 새 Content 길이: {len(new_content)} chars")
            print(f"   - Version: 2.0-vibe (트리플 반환 형식)")
        else:
            print(f"\n⚠️ 업데이트 실패 또는 변경사항 없음")
    else:
        print("⚠️ 기존 프롬프트가 DB에 없습니다. 새로 생성합니다...")
        
        await prompts_collection.insert_one({
            "name": "sparql_generation_prompt",
            "content": new_content,
            "version": "2.0-vibe",
            "type": "sparql_generation"
        })
        
        print("✅ 새 프롬프트가 생성되었습니다!")
    
    # 검증
    updated = await prompts_collection.find_one({"name": "sparql_generation_prompt"})
    if updated and "SELECT ?subject ?predicate ?object" in updated.get("content", ""):
        print("\n✅ 검증 완료: 트리플 반환 템플릿이 포함되어 있습니다!")
    else:
        print("\n❌ 검증 실패: 트리플 반환 템플릿을 찾을 수 없습니다!")
    
    client.close()

if __name__ == "__main__":
    print("=" * 60)
    print("SPARQL 프롬프트 DB 업데이트 스크립트")
    print("=" * 60)
    asyncio.run(update_prompts())
