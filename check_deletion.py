"""
test jf KB 데이터 삭제 확인 (Fuseki)
"""
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.core.fuseki import fuseki_client

kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

print("=" * 80)
print("test jf KB Fuseki 데이터 삭제 확인")
print("=" * 80)

# 1. 모든 Named Graph 확인
print("\n[1] Named Graph 목록")
print("-" * 80)

graph_query = """
SELECT DISTINCT ?g (COUNT(*) as ?count)
WHERE {
  GRAPH ?g { ?s ?p ?o }
}
GROUP BY ?g
ORDER BY ?g
"""

try:
    results = fuseki_client.query_sparql(kb_id, graph_query)
    bindings = results.get("results", {}).get("bindings", [])
    
    if bindings:
        print(f"  발견된 Named Graph: {len(bindings)}개\n")
        for b in bindings:
            graph_uri = b.get("g", {}).get("value", "?")
            count = b.get("count", {}).get("value", "0")
            print(f"  - {graph_uri}")
            print(f"    트리플 개수: {count}")
    else:
        print("  ✓ Named Graph가 없습니다 (완전 삭제됨)")
except Exception as e:
    print(f"  오류: {e}")

# 2. UnionGraph 전체 트리플 개수
print("\n[2] UnionGraph 전체 트리플 개수")
print("-" * 80)

count_query = """
SELECT (COUNT(*) as ?count)
FROM <urn:x-arq:UnionGraph>
WHERE {
  ?s ?p ?o .
}
"""

try:
    results = fuseki_client.query_sparql(kb_id, count_query)
    bindings = results.get("results", {}).get("bindings", [])
    if bindings:
        count = bindings[0].get("count", {}).get("value", "0")
        print(f"  총 트리플 개수: {count}")
        
        if count == "0":
            print("  ✓ Fuseki에 데이터가 없습니다 (완전 삭제됨)")
        else:
            print(f"  ⚠️ {count}개의 트리플이 남아있습니다")
except Exception as e:
    print(f"  오류: {e}")

# 3. 특정 엔티티 확인 (조상우, 성기훈, 기훈)
print("\n[3] 특정 엔티티 확인 (조상우, 성기훈, 기훈)")
print("-" * 80)

entity_query = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?label (COUNT(*) as ?count)
FROM <urn:x-arq:UnionGraph>
WHERE {
  ?s rdfs:label ?label .
  FILTER(?label IN ("조상우", "성기훈", "기훈", "오일남"))
}
GROUP BY ?label
"""

try:
    results = fuseki_client.query_sparql(kb_id, entity_query)
    bindings = results.get("results", {}).get("bindings", [])
    
    if bindings:
        print(f"  ⚠️ 다음 엔티티가 남아있습니다:\n")
        for b in bindings:
            label = b.get("label", {}).get("value", "?")
            count = b.get("count", {}).get("value", "0")
            print(f"    - {label}: {count}개 트리플")
    else:
        print("  ✓ 조상우, 성기훈, 기훈, 오일남 관련 데이터 모두 삭제됨")
except Exception as e:
    print(f"  오류: {e}")

print("\n" + "=" * 80)
print("확인 완료")
print("=" * 80)
