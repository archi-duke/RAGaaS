import asyncio
import os
import sys
from dotenv import load_dotenv

# 현재 디렉토리(.backend)를 path에 추가하여 app 모듈 import 가능하게 함
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# .env 로드 (로컬 실행 시 필요할 수 있음)
load_dotenv()

from app.core.config import settings
from app.doc2onto.qa.cypher_generator import CypherGenerator
from app.core.neo4j_client import neo4j_client

async def main():
    print("=== Debugging Doc2Onto Cypher Generation ===")
    
    # 테스트할 질문
    query_text = "성기훈의 스승의 스승은 누구야?"
    print(f"Question: {query_text}")
    
    # API Key 확인
    if not settings.OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY not found in settings.")
        return

    # 1. Generator 초기화 및 쿼리 생성
    print("\n[1] Initializing CypherGenerator...")
    try:
        generator = CypherGenerator(api_key=settings.OPENAI_API_KEY)
        
        # 힌트 컨텍스트 (실제 상황에선 추출된 엔티티가 들어감)
        context = "관련 엔티티 후보: 성기훈"
        
        print("Generating Cypher query...")
        result = generator.generate(query_text, context=context)
        
        cypher = result.get("cypher")
        thought = result.get("thought")
        
        print("\n>>> Generated Cypher:")
        print(cypher)
        print("\n>>> Thought:")
        print(thought)
        
        if not cypher:
            print("Failed to generate cypher.")
            return

    except Exception as e:
        print(f"Error generating cypher: {e}")
        import traceback
        traceback.print_exc()
        return

    # 2. Neo4j 실행
    print("\n[2] Executing Query on Neo4j...")
    try:
        # Neo4j 연결 확인 (동기 메서드일수도 있으니 확인)
        # verify_connectivity는 보통 동기이거나 async일 수 있음. neo4j_client 코드 확인 필요하지만 일단 진행.
        if not neo4j_client.verify_connectivity():
             print("Neo4j connection failed.")
             return
        
        # 쿼리 실행 (execute_query가 async인지 확인 필요하지만, 보통 client wrapper는 async로 구현됨)
        # backend/app/core/neo4j_client.py를 보면 driver.execute_query를 씀 (동기일 확률 높음?)
        # 아니요, RAGaaS 코드는 대부분 async/asyncio를 씁니다. 
        # 하지만 neo4j_client.py 내부 구현이 `def execute_query` (동기) 인지 `async def` 인지 확인 필요.
        # 이전 코드(graph.py)에서 `await backend.query`는 있었지만 `backend.query` 내부에서 `neo4j_client.execute_query`를 호출함.
        # `Neo4jDriver`는 보통 동기 방식의 `neo4j` 패키지를 쓰면 동기임.
        # 안전을 위해 동기/비동기 모두 고려. 여기서 그냥 호출해보고 에러나면 수정.
        # graph.py에는 `chunk_ids = [record["chunk_id"] for record in records]` 라고 되어있음, 즉 await이 안붙어있을 수도 있음. 
        # 하지만 `neo4j_backend.py`의 `query` 메서드는 `async def`임.
        # 그 내부에서 `records = neo4j_client.execute_query(...)` 를 `await` 없이 썼는지 확인해보자.
        
        # 방금 수정한 neo4j.py를 다시 보면:
        # records = neo4j_client.execute_query(cypher_query) 
        # await가 없습니다! -> 동기 함수입니다.
        
        records = neo4j_client.execute_query(cypher)
        
        print(f"\nResult count: {len(records)}")
        for i, record in enumerate(records):
            print(f"[{i+1}] {record}")
            
    except Exception as e:
        print(f"Error executing query: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # neo4j_client가 동기라면 main도 굳이 async일 필요 없지만, 
    # 생성기 호출 등은 동기(requests)이므로 상관 없음.
    asyncio.run(main())
