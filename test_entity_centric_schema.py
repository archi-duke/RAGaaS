"""
Entity-Centric Dynamic Schema 기능 테스트

3가지 케이스를 검증:
1. 단일 엔티티 중심 (성기훈의 스승의 스승은?)
2. 목적어/속성 중심 (장풍을 사용하는 참가자는?)
3. 두 엔티티 간 관계 (성기훈과 조상우의 관계는?)
"""

import asyncio
import sys
import os

# Change to backend directory for correct file paths
backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)

# Add backend to path
sys.path.insert(0, backend_dir)

async def test_entity_centric_schema():
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    
    # test jf KB ID
    kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
    
    fuseki = FusekiBackend()
    
    print("=" * 80)
    print("Entity-Centric Dynamic Schema 테스트")
    print("=" * 80)
    
    # 케이스 1: 단일 엔티티 중심 쿼리
    print("\n[케이스 1] 단일 엔티티 중심: '성기훈의 스승의 스승은?'")
    print("-" * 80)
    
    try:
        result1 = await fuseki.query(
            kb_id=kb_id,
            entities=["성기훈"],
            hops=2,
            query_type="graph",
            relationship_keywords=[],
            query_text="성기훈의 스승의 스승은?",
            enable_entity_centric_schema=True,
            use_dynamic_schema=False  # Entity-Centric만 사용
        )
        
        print(f"✓ 결과:")
        print(f"  - Chunk IDs: {len(result1.get('chunk_ids', []))}")
        print(f"  - Triples: {len(result1.get('triples', []))}")
        print(f"  - Found Entities: {result1.get('found_entities', [])[:5]}")
        
        # Trace logs에서 Entity-Centric 로직 확인
        trace_logs = result1.get('trace_logs', [])
        entity_centric_logs = [log for log in trace_logs if 'Entity-Centric' in log]
        
        print(f"\n  Entity-Centric Logs:")
        for log in entity_centric_logs:
            print(f"    {log}")
        
        if result1.get('triples'):
            print(f"\n  발견된 트리플 (샘플):")
            for triple in result1['triples'][:3]:
                print(f"    {triple}")
        
    except Exception as e:
        print(f"✗ 오류: {e}")
        import traceback
        traceback.print_exc()
    
    # 케이스 2: 목적어/속성 중심 쿼리
    print("\n" + "=" * 80)
    print("[케이스 2] 목적어/속성 중심: '장풍을 사용하는 참가자는?'")
    print("-" * 80)
    
    try:
        result2 = await fuseki.query(
            kb_id=kb_id,
            entities=["장풍"],
            hops=1,
            query_type="graph",
            relationship_keywords=[],
            query_text="장풍을 사용하는 참가자는?",
            enable_entity_centric_schema=True,
            use_dynamic_schema=False
        )
        
        print(f"✓ 결과:")
        print(f"  - Chunk IDs: {len(result2.get('chunk_ids', []))}")
        print(f"  - Triples: {len(result2.get('triples', []))}")
        print(f"  - Found Entities: {result2.get('found_entities', [])[:5]}")
        
        trace_logs = result2.get('trace_logs', [])
        entity_centric_logs = [log for log in trace_logs if 'Entity-Centric' in log]
        
        print(f"\n  Entity-Centric Logs:")
        for log in entity_centric_logs:
            print(f"    {log}")
        
        if result2.get('triples'):
            print(f"\n  발견된 트리플 (샘플):")
            for triple in result2['triples'][:3]:
                print(f"    {triple}")
                
    except Exception as e:
        print(f"✗ 오류: {e}")
        import traceback
        traceback.print_exc()
    
    # 케이스 3: 두 엔티티 간 관계
    print("\n" + "=" * 80)
    print("[케이스 3] 두 엔티티 간 관계: '성기훈과 조상우의 관계는?'")
    print("-" * 80)
    
    try:
        result3 = await fuseki.query(
            kb_id=kb_id,
            entities=["성기훈", "조상우"],
            hops=1,
            query_type="graph",
            relationship_keywords=[],
            query_text="성기훈과 조상우의 관계는?",
            enable_entity_centric_schema=True,
            use_dynamic_schema=False
        )
        
        print(f"✓ 결과:")
        print(f"  - Chunk IDs: {len(result3.get('chunk_ids', []))}")
        print(f"  - Triples: {len(result3.get('triples', []))}")
        print(f"  - Found Entities: {result3.get('found_entities', [])[:5]}")
        
        trace_logs = result3.get('trace_logs', [])
        entity_centric_logs = [log for log in trace_logs if 'Entity-Centric' in log]
        
        print(f"\n  Entity-Centric Logs:")
        for log in entity_centric_logs:
            print(f"    {log}")
        
        if result3.get('triples'):
            print(f"\n  발견된 트리플 (샘플):")
            for triple in result3['triples'][:3]:
                print(f"    {triple}")
                
    except Exception as e:
        print(f"✗ 오류: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("테스트 완료")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_entity_centric_schema())
