"""
3가지 검색 패턴 테스트

패턴 1: ? -> P -> O (Subject 미상)
패턴 2: S -> ? -> O (Relation 미상)
패턴 3: S -> P -> ? (Object 미상)
"""

import asyncio
import sys
import os

# Change to backend directory for correct file paths
backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)

# Add backend to path
sys.path.insert(0, backend_dir)

async def test_three_patterns():
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    
    # test jf KB ID
    kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
    
    fuseki = FusekiBackend()
    
    print("=" * 80)
    print("3가지 검색 패턴 테스트")
    print("=" * 80)
    
    # 패턴 1: ? -> P -> O (Subject 미상)
    print("\n[패턴 1] ? -> P -> O: '장풍을 사용하는 참가자는?'")
    print("-" * 80)
    
    try:
        result1 = await fuseki.query(
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
        print(f"  - Chunk IDs: {len(result1.get('chunk_ids', []))}")
        print(f"  - Triples: {len(result1.get('triples', []))}")
        
        # Pattern 감지 로그 확인
        trace_logs = result1.get('trace_logs', [])
        pattern_logs = [log for log in trace_logs if 'Pattern' in log]
        
        print(f"\n  Pattern Detection Logs:")
        for log in pattern_logs:
            print(f"    {log}")
        
        if result1.get('triples'):
            print(f"\n  발견된 트리플:")
            for triple in result1['triples'][:3]:
                print(f"    {triple}")
        
    except Exception as e:
        print(f"✗ 오류: {e}")
        import traceback
        traceback.print_exc()
    
    # 패턴 2: S -> ? -> O (Relation 미상)
    print("\n" + "=" * 80)
    print("[패턴 2] S -> ? -> O: '성기훈과 조상우의 관계는?'")
    print("-" * 80)
    
    try:
        result2 = await fuseki.query(
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
        print(f"  - Chunk IDs: {len(result2.get('chunk_ids', []))}")
        print(f"  - Triples: {len(result2.get('triples', []))}")
        
        trace_logs = result2.get('trace_logs', [])
        pattern_logs = [log for log in trace_logs if 'Pattern' in log]
        
        print(f"\n  Pattern Detection Logs:")
        for log in pattern_logs:
            print(f"    {log}")
        
        if result2.get('triples'):
            print(f"\n  발견된 트리플:")
            for triple in result2['triples'][:3]:
                print(f"    {triple}")
                
    except Exception as e:
        print(f"✗ 오류: {e}")
        import traceback
        traceback.print_exc()
    
    # 패턴 3: S -> P -> ? (Object 미상)
    print("\n" + "=" * 80)
    print("[패턴 3] S -> P -> ?: '성기훈의 후배는 누구야?'")
    print("-" * 80)
    
    try:
        result3 = await fuseki.query(
            kb_id=kb_id,
            entities=["성기훈"],
            hops=1,
            query_type="graph",
            relationship_keywords=[],
            query_text="성기훈의 후배는 누구야?",
            enable_entity_centric_schema=True,
            use_dynamic_schema=False
        )
        
        print(f"✓ 결과:")
        print(f"  - Chunk IDs: {len(result3.get('chunk_ids', []))}")
        print(f"  - Triples: {len(result3.get('triples', []))}")
        
        trace_logs = result3.get('trace_logs', [])
        pattern_logs = [log for log in trace_logs if 'Pattern' in log]
        
        print(f"\n  Pattern Detection Logs:")
        for log in pattern_logs:
            print(f"    {log}")
        
        if result3.get('triples'):
            print(f"\n  발견된 트리플:")
            for triple in result3['triples'][:3]:
                print(f"    {triple}")
                
    except Exception as e:
        print(f"✗ 오류: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("✅ 3가지 패턴 테스트 완료")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_three_patterns())
