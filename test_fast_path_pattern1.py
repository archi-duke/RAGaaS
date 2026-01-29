"""
Fast Path (Pattern 1) 검증 스크립트
"""
import sys
import os
import asyncio
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.services.retrieval.graph_backends.fuseki")
logger.setLevel(logging.INFO)

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.services.retrieval.graph_backends.fuseki import FusekiBackend

async def test_fast_path():
    print("🚀 Testing Fast Path for Pattern 1 ('장풍' Incoming)")
    
    backend = FusekiBackend()
    kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1" # test jf
    query = "장풍을 사용하는 참가자는?"
    
    # query 메서드 호출 (Graph Search의 핵심 메서드)
    result = await backend.query(
        kb_id=kb_id,
        query=query,
        # top_k=5, query 메서드는 top_k 인자를 직접 받지 않고 kwargs로 처리될 수 있음
        hops=2,
        use_dynamic_schema=True # Dynamic Schema 켜기
    )
    
    # query 결과는 dict 형태입니다 (triples, found_entities 등 포함)
    print(f"\n✅ Result Keys: {result.keys()}")
    
    triples = result.get("triples", [])
    print(f"Found {len(triples)} triples")
    
    trace_logs = result.get("trace_logs", [])
    fast_path_success = any("Fast Path successful" in log for log in trace_logs)
    
    print("\n[Log Analysis]")
    if fast_path_success:
        print("🎉 Fast Path SUCCESS confirmed in logs!")
        for log in trace_logs:
            if "Fast Path" in log:
                print(f"  - {log}")
    else:
        print("⚠️ Fast Path NOT detected in logs.")
        # 전체 로그 출력
        for log in trace_logs:
            print(f"  - {log}")

if __name__ == "__main__":
    asyncio.run(test_fast_path())
