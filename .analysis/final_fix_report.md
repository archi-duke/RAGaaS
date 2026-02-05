# ✅ 최종 수정 사항 (2026-01-27 16:57)

## 🔧 중요한 수정

### 문제 발견
프론트엔드에서 "processing"만 표시되는 문제 발견

### 원인 분석
1. **send_pipeline_status 함수**: `status` 필드가 항상 `"processing"`으로 고정
2. **백엔드 ingest_callback**: `status`가 `"completed"`가 아니면 항상 `PROCESSING`으로 설정
3. **프론트엔드**: `COMPLETED` 상태를 기대 (`PUBLISHED` 아님)

### 해결 방법

#### 1. send_pipeline_status 수정
**파일**: `ingest_service/app/api/ingest.py` (라인 111-112)

```python
# Before
"status": "processing",  # ⚠️ 항상 고정

# After
overall_status = "completed" if status == "COMPLETED" else "processing"
"status": overall_status,  # ✅ 동적 설정
```

#### 2. PUBLISHED → COMPLETED 변경
**파일**: `ingest_service/app/api/ingest.py`

프론트엔드가 `COMPLETED`를 기대하므로 모든 `PUBLISHED`를 `COMPLETED`로 변경:

```python
# process_ingest_job (라인 299)
await send_pipeline_status(request.callback_url, job_id, request.doc_id, request.kb_id, "COMPLETED")

# _save_preview_data (라인 692)
await send_pipeline_status(callback_url, job_id, doc_id, kb_id, "COMPLETED")
```

---

## 🎯 최종 상태 흐름

### 일괄 업로드 모드

```
1. EXTRACTING_ENTITIES    → Status: "processing", Pipeline: "EXTRACTING_ENTITIES"
   ↓                         UI: "Entities..." (노란색, 애니메이션)
   
2. ENTITY_EXTRACTED       → Status: "processing", Pipeline: "ENTITY_EXTRACTED"
   ↓                         UI: "Entities" (파란색, 아주 짧게)
   
3. EXTRACTING_TRIPLES     → Status: "processing", Pipeline: "EXTRACTING_TRIPLES"
   ↓                         UI: "Triples..." (노란색, 애니메이션)
   
4. TRIPLE_EXTRACTED       → Status: "processing", Pipeline: "TRIPLE_EXTRACTED"
   ↓                         UI: "Triples" (보라색, 아주 짧게)
   
5. STORING                → Status: "processing", Pipeline: "STORING"
   ↓                         UI: "Storing" (노란색, 애니메이션)
   
6. COMPLETED              → Status: "completed", Pipeline: "COMPLETED"
                            UI: "Published" (초록색)
```

---

## 📊 변경 파일 요약

### ingest_service/app/api/ingest.py
1. ✅ `send_pipeline_status`: 동적 status 설정 (라인 111-112)
2. ✅ `process_ingest_job`: COMPLETED 전송 (라인 299)
3. ✅ `_save_preview_data`: COMPLETED 전송 (라인 692)

---

## 🧪 테스트 확인사항

### 필수 확인
- [ ] Ingest Service 재시작
- [ ] 일괄 업로드 테스트
  - [ ] "Entities..." 표시 확인
  - [ ] "Entities" (짧게) 표시 확인
  - [ ] "Triples..." 표시 확인
  - [ ] "Triples" (짧게) 표시 확인
  - [ ] "Storing" 표시 확인
  - [ ] "Published" 최종 표시 확인
- [ ] Preview 모드 테스트
  - [ ] Extract Entities 흐름
  - [ ] Extract Triples 흐름
  - [ ] Upload 완료 시 "Published" 표시

---

## 🎉 예상 결과

이제 프론트엔드에서 정확한 상태 순서를 볼 수 있습니다:

**Entities... → Entities → Triples... → Triples → Storing → Published**

각 상태는 WebSocket을 통해 실시간으로 업데이트됩니다!
