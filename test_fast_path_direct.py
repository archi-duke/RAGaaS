"""
Fast Path 기능 직접 테스트
"""
import asyncio
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

async def test_fast_path():
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    
    kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
    fuseki = FusekiBackend()
    
    print("=" * 80)
    print("Fast Path 직접 테스트: '조상우와 성기훈의 관계는?'")
    print("=" * 80)
    
    result = await fuseki.query(
        kb_id=kb_id,
        entities=["조상우", "성기훈"],
        hops=2,
        query_type="graph",
        relationship_keywords=[],
        query_text="조상우와 성기훈의 관계는?",
        enable_entity_centric_schema=True,
        use_dynamic_schema=True
    )
    
    print(f"\n✅ 결과:")
    print(f"  - Chunk IDs: {len(result.get('chunk_ids', []))}")
    print(f"  - Triples: {len(result.get('triples', []))}")
    print(f"  - Found Entities: {result.get('found_entities', [])}")
    
    if result.get('triples'):
        print(f"\n  발견된 트리플:")
        for triple in result['triples']:
            print(f"    {triple}")
    
    if result.get('chunk_ids'):
        print(f"\n  Chunk IDs:")
        for cid in result['chunk_ids']:
            print(f"    {cid}")
    
    print(f"\n  Trace Logs (마지막 10개):")
    for log in result.get('trace_logs', [])[-10:]:
        print(f"    {log}")

if __name__ == "__main__":
    asyncio.run(test_fast_path())
