"""
최종 클린 상태 확인 (Fuseki + Milvus)
"""
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.core.fuseki import fuseki_client
from app.core.milvus import create_collection
from pymilvus import connections, utility

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

print("=" * 80)
print(f"KB ID: {kb_id} 최종 클린 상태 확인")
print("=" * 80)

# 1. Fuseki 확인
print("\n[1] Fuseki (Graph DB) 상태")
print("-" * 80)
try:
    # 모든 그래프 조회
    graph_query = "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }"
    graphs = fuseki_client.query_sparql(kb_id, graph_query).get("results", {}).get("bindings", [])
    
    # 전체 트리플 개수
    count_query = "SELECT (COUNT(*) as ?count) WHERE { {?s ?p ?o} UNION { GRAPH ?g { ?s ?p ?o } } }"
    total_count = fuseki_client.query_sparql(kb_id, count_query).get("results", {}).get("bindings", [{}])[0].get("count", {}).get("value", "0")
    
    if int(total_count) == 0:
        print("  ✓ Fuseki: 트리플이 0개입니다. (완벽하게 비어있음)")
    else:
        print(f"  ⚠️ Fuseki: {total_count}개의 트리플이 남아있습니다!")
        for g in graphs:
            print(f"    - Graph: {g.get('g', {}).get('value')}")
except Exception as e:
    print(f"  ⚠️ Fuseki 확인 중 오류: {e}")

# 2. Milvus 확인
print("\n[2] Milvus (Vector DB) 상태")
print("-" * 80)
try:
    collection_name = f"kb_{kb_id.replace('-', '_')}"
    # pymilvus 직접 연결 시도
    try:
        connections.connect(alias="default", host="localhost", port="19530")
    except:
        pass
        
    if utility.has_collection(collection_name):
        collection = create_collection(kb_id)
        collection.load()
        num_entities = collection.num_entities
        if num_entities == 0:
            print(f"  ✓ Milvus: Collection '{collection_name}'은 존재하지만 데이터는 0개입니다.")
        else:
            print(f"  ⚠️ Milvus: Collection '{collection_name}'에 {num_entities}개의 데이터가 남아있습니다!")
    else:
        print(f"  ✓ Milvus: Collection '{collection_name}'이 존재하지 않습니다. (삭제 완료)")
except Exception as e:
    print(f"  ⚠️ Milvus 확인 중 오류: {e}")

print("\n" + "=" * 80)
print("검증 완료")
print("=" * 80)
