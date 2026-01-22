"""
test jf KB에 테스트 문서 업로드 및 청크 확인
"""
import requests
import time

API_URL = "http://localhost:8000/api"
KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"  # test jf

print("=" * 70)
print("📤 test jf KB에 테스트 문서 업로드")
print("=" * 70)

# 1. 테스트 문서 생성
test_file = "test_chunk_view.txt"
with open(test_file, "w", encoding="utf-8") as f:
    f.write("""성기훈은 오징어 게임의 주인공이다.
그는 456번 참가자로 게임에 참여했다.
오일남은 001번 참가자이며 성기훈의 스승이다.
조상우는 218번 참가자이다.
강새벽은 067번 참가자이다.
""")

# 2. 문서 업로드
print(f"\n[1] 문서 업로드 중...")
try:
    with open(test_file, "rb") as f:
        files = {"file": (test_file, f, "text/plain")}
        data = {
            "oe_section_aware": "false",
            "extract_inverse_relations": "false",
            "confidence_threshold": "0.7"
        }
        res = requests.post(f"{API_URL}/knowledge-bases/{KB_ID}/documents", files=files, data=data)
    
    if res.status_code == 200:
        doc_id = res.json()["id"]
        print(f"  ✅ 업로드 성공: {doc_id}")
        print(f"  파일명: {test_file}")
    else:
        print(f"  ❌ 업로드 실패: {res.status_code}")
        print(f"  응답: {res.text}")
        exit(1)
        
except Exception as e:
    print(f"  ❌ 오류: {e}")
    exit(1)
finally:
    import os
    if os.path.exists(test_file):
        os.remove(test_file)

# 3. 인제스트 대기
print(f"\n[2] 인제스트 처리 대기 중 (15초)...")
time.sleep(15)

# 4. 문서 목록 확인
print(f"\n[3] 문서 목록 확인...")
try:
    res = requests.get(f"{API_URL}/knowledge-bases/{KB_ID}/documents")
    if res.status_code == 200:
        docs = res.json()
        print(f"  총 문서: {len(docs)}개")
        for doc in docs:
            print(f"    - {doc['filename']}: {doc['status']}")
    else:
        print(f"  ❌ 조회 실패: {res.status_code}")
except Exception as e:
    print(f"  ❌ 오류: {e}")

# 5. 청크 조회 테스트
print(f"\n[4] 청크 조회 테스트...")
try:
    res = requests.get(f"{API_URL}/knowledge-bases/{KB_ID}/documents/{doc_id}/chunks")
    if res.status_code == 200:
        chunks = res.json()
        print(f"  ✅ 청크 조회 성공: {len(chunks)}개")
        if chunks:
            print(f"\n  첫 번째 청크 샘플:")
            print(f"    ID: {chunks[0]['id']}")
            print(f"    내용: {chunks[0]['content'][:100]}...")
    else:
        print(f"  ❌ 청크 조회 실패: {res.status_code}")
        print(f"  응답: {res.text}")
except Exception as e:
    print(f"  ❌ 오류: {e}")

print("\n" + "=" * 70)
print("✅ 테스트 완료 - 이제 UI에서 청크를 확인할 수 있습니다!")
print("=" * 70)
