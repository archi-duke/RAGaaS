"""
test jf KB의 청크 크기를 500으로 업데이트
"""
import requests

API_URL = "http://localhost:8000/api"
KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"

print("=" * 70)
print("📝 test jf KB 청크 크기 업데이트")
print("=" * 70)

# 현재 설정 확인
print("\n[1] 현재 설정 확인:")
res = requests.get(f"{API_URL}/knowledge-bases/{KB_ID}")
if res.status_code == 200:
    kb = res.json()
    current_size = kb['chunking_config']['chunk_size']
    print(f"  현재 chunk_size: {current_size}")
else:
    print(f"  ❌ KB 조회 실패: {res.status_code}")
    exit(1)

# 청크 크기 업데이트
print("\n[2] chunk_size를 500으로 업데이트:")
update_data = {
    "chunking_config": {
        **kb['chunking_config'],
        "chunk_size": 500
    }
}

res = requests.patch(f"{API_URL}/knowledge-bases/{KB_ID}", json=update_data)
if res.status_code == 200:
    print(f"  ✅ 업데이트 성공")
else:
    print(f"  ❌ 업데이트 실패: {res.status_code}")
    print(f"  응답: {res.text}")
    exit(1)

# 업데이트 확인
print("\n[3] 업데이트 확인:")
res = requests.get(f"{API_URL}/knowledge-bases/{KB_ID}")
if res.status_code == 200:
    kb = res.json()
    new_size = kb['chunking_config']['chunk_size']
    print(f"  새로운 chunk_size: {new_size}")
    
    if new_size == 500:
        print(f"\n✅ 청크 크기가 500으로 성공적으로 변경되었습니다!")
    else:
        print(f"\n⚠️  예상과 다른 값: {new_size}")
else:
    print(f"  ❌ 확인 실패: {res.status_code}")

print("\n" + "=" * 70)
print("⚠️  주의: 이미 업로드된 문서는 영향을 받지 않습니다.")
print("새로운 청크 크기는 앞으로 업로드되는 문서에만 적용됩니다.")
print("=" * 70)
