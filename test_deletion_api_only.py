"""
문서 삭제 로직의 완전성을 검증하는 통합 테스트 (API 전용)
- API를 통해서만 검증 (내부 DB 직접 접근 없음)
- 업로드 후 문서 리스트에 나타나는지 확인
- 삭제 후 문서가 사라지는지 확인
"""

import requests
import time
import os

API_URL = "http://localhost:8000/api"
TEST_KB_NAME = "test jf"

def find_kb_by_name(kb_name):
    """KB 이름으로 ID 찾기"""
    res = requests.get(f"{API_URL}/knowledge-bases")
    if res.status_code == 200:
        kbs = res.json()
        for kb in kbs:
            if kb["name"] == kb_name:
                return kb["id"]
    return None

def get_documents(kb_id):
    """KB의 문서 목록 조회"""
    res = requests.get(f"{API_URL}/knowledge-bases/{kb_id}/documents")
    if res.status_code == 200:
        return res.json()
    return []

def upload_test_document(kb_id):
    """테스트 문서 업로드"""
    print(f"\n📤 테스트 문서 업로드 중 (KB: {kb_id})...")
    
    test_file_path = "test_deletion_doc.txt"
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("홍길동은 서울에 산다.\n조선의 의적이다.\n김선달과 친구다.\n")
    
    with open(test_file_path, "rb") as f:
        files = {"file": (test_file_path, f, "text/plain")}
        data = {
            "oe_section_aware": "false",
            "extract_inverse_relations": "false",
            "confidence_threshold": "0.7"
        }
        res = requests.post(f"{API_URL}/knowledge-bases/{kb_id}/documents", files=files, data=data)
    
    os.remove(test_file_path)
    
    if res.status_code == 200:
        doc_id = res.json()["id"]
        print(f"✅ 문서 업로드 완료: {doc_id}")
        return doc_id
    else:
        print(f"❌ 문서 업로드 실패: {res.status_code} - {res.text}")
        return None

def delete_document(kb_id, doc_id):
    """문서 삭제"""
    print(f"\n🗑️  문서 삭제 중 (Doc: {doc_id})...")
    res = requests.delete(f"{API_URL}/knowledge-bases/{kb_id}/documents/{doc_id}")
    
    if res.status_code == 200:
        print(f"✅ 문서 삭제 요청 완료")
        return True
    else:
        print(f"❌ 문서 삭제 실패: {res.status_code} - {res.text}")
        return False

def run_api_level_test():
    """API 레벨 통합 테스트 실행"""
    print("=" * 60)
    print("🧪 문서 삭제 완전성 테스트 (API 기반)")
    print("=" * 60)
    
    # 1. KB 찾기
    kb_id = find_kb_by_name(TEST_KB_NAME)
    if not kb_id:
        print(f"❌ KB '{TEST_KB_NAME}'를 찾을 수 없습니다.")
        return False
    
    print(f"✅ 테스트 KB ID: {kb_id}")
    
    # 2. 업로드 전 문서 개수 확인
    docs_before = get_documents(kb_id)
    print(f"\n📊 업로드 전 문서 개수: {len(docs_before)}")
    
    # 3. 문서 업로드
    doc_id = upload_test_document(kb_id)
    if not doc_id:
        return False
    
    # 4. 인제스트 대기
    print("\n⏳ 인제스트 처리 대기 중 (15초)...")
    time.sleep(15)
    
    # 5. 업로드 후 문서 확인
    docs_after_upload = get_documents(kb_id)
    doc_found = any(d["id"] == doc_id for d in docs_after_upload)
    
    print(f"\n📊 [업로드 후] 검증:")
    print(f"  - 문서 개수: {len(docs_before)} → {len(docs_after_upload)}")
    print(f"  - 업로드한 문서 존재: {'✅ 확인' if doc_found else '❌ 미확인'}")
    
    if not doc_found:
        print("\n⚠️  업로드한 문서가 목록에 없습니다. 테스트 중단.")
        return False
    
    # 6. 문서 삭제
    if not delete_document(kb_id, doc_id):
        return False
    
    # 7. 삭제 처리 대기
    print("\n⏳ 삭제 처리 대기 중 (8초)...")
    time.sleep(8)
    
    # 8. 삭제 후 문서 확인
    docs_after_delete = get_documents(kb_id)
    doc_still_exists = any(d["id"] == doc_id for d in docs_after_delete)
    
    print(f"\n📊 [삭제 후] 검증:")
    print(f"  - 문서 개수: {len(docs_after_upload)} → {len(docs_after_delete)}")
    print(f"  - 삭제한 문서 존재: {'❌ 여전히 존재(FAIL)' if doc_still_exists else '✅ 제거됨'}")
    
    # 9. 결과 판정
    print("\n" + "=" * 60)
    if not doc_still_exists and len(docs_after_delete) == len(docs_before):
        print("🎉 테스트 성공! 문서가 깨끗이 삭제되었습니다.")
        print("=" * 60)
        return True
    else:
        print("⚠️  테스트 실패!")
        if doc_still_exists:
            print("  - 문서가 여전히 API에 표시됨")
        if len(docs_after_delete) != len(docs_before):
            print(f"  - 문서 개수 불일치 (예상: {len(docs_before)}, 실제: {len(docs_after_delete)})")
        print("=" * 60)
        return False

if __name__ == "__main__":
    try:
        success = run_api_level_test()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n💥 테스트 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
