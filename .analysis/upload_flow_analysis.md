# Upload Document 모달 동작 흐름 분석

## 개요
Upload Document 모달에서 "Upload" 버튼 클릭 시 실행되는 동작 흐름을 분석한 문서입니다.

---

## 1. 프론트엔드: Upload 버튼 클릭 시 동작

### 1.1 버튼 위치 및 조건
**파일**: `frontend/src/components/UploadDocumentModal.tsx`

**버튼 코드** (라인 929-935):
```tsx
<button
    className="btn btn-primary"
    onClick={handleUpload}
    disabled={(!file && !resumedDocId) || isUploading || isExtracting || showPreviewModal || showDictionaryModal}
>
    {isUploading ? 'Uploading...' : (previewData ? 'Confirm Ingestion' : 'Upload')}
</button>
```

**버튼 활성화 조건**:
- 파일이 선택되었거나 (`file`) 재개할 문서 ID가 있어야 함 (`resumedDocId`)
- 업로드 중이 아니어야 함 (`!isUploading`)
- 추출 중이 아니어야 함 (`!isExtracting`)
- Preview 모달이 열려있지 않아야 함 (`!showPreviewModal`)
- Dictionary 모달이 열려있지 않아야 함 (`!showDictionaryModal`)

**버튼 텍스트**:
- 업로드 중: "Uploading..."
- Triple Preview 데이터가 있는 경우: "Confirm Ingestion"
- 일반 업로드: "Upload"

---

## 2. handleUpload 함수 동작 분석

### 2.1 함수 위치
**파일**: `frontend/src/components/UploadDocumentModal.tsx` (라인 268-326)

### 2.2 동작 분기

#### **분기 1: Triple Preview가 완료된 경우** (라인 270-290)
```typescript
if (previewData && previewData.preview_id) {
    setIsExtracting(true);
    try {
        await extractionApi.confirm(previewData.preview_id, {
            enable_inference: graphParams.enable_inference,
            callback_url: "http://127.0.0.1:8000/api/knowledge-bases/ingest/callback"
        });
        onUploadComplete();
        onClose();
    } catch (error) {
        // 에러 처리
    } finally {
        setIsExtracting(false);
    }
    return;
}
```

**동작**:
1. `extractionApi.confirm()` 호출 → Ingest Service의 `/confirm/{preview_id}` 엔드포인트 호출
2. 성공 시:
   - `onUploadComplete()` 호출 → 문서 목록 새로고침
   - `onClose()` 호출 → 모달 닫기

**API 엔드포인트**: `POST http://127.0.0.1:8001/api/confirm/{preview_id}`

---

#### **분기 2: 일반 파일 업로드** (라인 294-325)
```typescript
if (!file && !resumedDocId) return;

setIsUploading(true);
try {
    const config = {
        ...graphParams,
        chunking_strategy: strategy,
        chunking_config: chunkingConfig,
        entity_dictionary: dictionaryData?.dictionary
    };

    if (file) {
        await docApi.upload(kbId, file, config);
        onUploadComplete();
        onClose();
    } else if (resumedDocId) {
        alert("Cannot upload without file. Please proceed with Extraction steps.");
    }
} catch (err) {
    // 에러 처리
} finally {
    setIsUploading(false);
}
```

**동작**:
1. 설정 객체 생성:
   - `graphParams`: 그래프 추출 파라미터
   - `chunking_strategy`, `chunking_config`: 청킹 전략 및 설정
   - `entity_dictionary`: Entity Dictionary 데이터 (있는 경우)

2. `docApi.upload()` 호출 → Backend의 `/knowledge-bases/{kb_id}/documents` 엔드포인트 호출

3. 성공 시:
   - `onUploadComplete()` 호출 → 문서 목록 새로고침
   - `onClose()` 호출 → 모달 닫기

**API 엔드포인트**: `POST http://127.0.0.1:8000/api/knowledge-bases/{kb_id}/documents`

---

## 3. 백엔드: 문서 업로드 처리

### 3.1 엔드포인트
**파일**: `backend/app/api/document.py`
**함수**: `upload_document` (라인 18-169)

### 3.2 처리 단계

#### **단계 1: Knowledge Base 조회**
```python
kb = await KBModel.get(kb_id)
if not kb:
    raise HTTPException(status_code=404, detail="Knowledge Base not found")
```

#### **단계 2: 문서 레코드 처리**
- 기존 문서가 있으면 덮어쓰기 (상태를 `PROCESSING`으로 변경)
- 없으면 새 문서 생성

#### **단계 3: 파일 저장**
```python
shared_path = settings.SHARED_STORAGE_PATH
kb_path = os.path.join(shared_path, kb_id)
file_path = os.path.join(kb_path, f"{doc.id}_{doc.filename}")
```
- 공유 스토리지 경로에 파일 저장
- 파일명 형식: `{doc_id}_{filename}`

#### **단계 4: 설정 병합**
- KB의 기본 설정과 요청에서 받은 설정 병합
- Chunking 설정, Graph 설정 등 구성

#### **단계 5: 문서 메타데이터 업데이트**
```python
doc.extractor_type = graph_config.get("extractor_type")
doc.max_paths = graph_config.get("max_paths_per_chunk")
doc.enable_text_cleaning = enable_text_cleaning
doc.enable_subject_restoration = enable_subject_restoration
# ... 기타 설정들
doc.file_path = file_path
await doc.save()
```

#### **단계 6: Ingest Service 호출 (비동기 태스크)**
```python
async def call_ingest_service():
    from app.services.ingestion.ingest_client import ingest_client
    await ingest_client.create_ingest_job(
        kb_id=kb_id,
        doc_id=doc.id,
        file_path=file_path,
        # ... 기타 설정들
    )
```

**중요**: 이 함수는 `background_tasks`로 실행되어 즉시 응답을 반환하고 백그라운드에서 처리됩니다.

---

## 4. Ingest Service: 문서 처리

### 4.1 엔드포인트
**파일**: `ingest_service/app/api/ingest.py`
**함수**: `create_ingest_job` (라인 306-341)

### 4.2 처리 흐름

#### **단계 1: Job 생성**
```python
job_id = str(uuid.uuid4())
jobs[job_id] = {
    "job_id": job_id,
    "status": JobStatus.PENDING,
    "kb_id": request.kb_id,
    "doc_id": request.doc_id,
    # ...
}
```

#### **단계 2: 백그라운드 태스크 시작**
```python
background_tasks.add_task(process_ingest_job, job_id, request)
```

---

### 4.3 process_ingest_job 함수 (라인 123-302)

이 함수가 실제로 **3단계 처리**를 수행합니다:

#### **1단계: 엔티티 추출 (Entity Extraction)**

**상태 업데이트**: `EXTRACTING_ENTITIES`
```python
await send_pipeline_status(callback_url, job_id, doc_id, kb_id, "EXTRACTING_ENTITIES")
```

**동작**:
- `DictionaryBuilder`를 사용하여 문서에서 엔티티 추출
- 샘플링 크기 제한 적용 (기본 50,000자)
- 엔티티 정규화 수행 (설정된 경우)

**결과**:
- `entity_dictionary`: 추출된 엔티티 사전

---

#### **2단계: 청킹 및 트리플 추출 (Chunking & Triple Extraction)**

**상태 업데이트**: `EXTRACTING_TRIPLES`
```python
await send_pipeline_status(callback_url, job_id, doc_id, kb_id, "EXTRACTING_TRIPLES")
```

**동작**:
1. **청킹**:
   - 선택된 청킹 전략에 따라 문서를 청크로 분할
   - 지원 전략: `fixed_size`, `sliding_window`, `hierarchical`, `semantic`, `markdown`, `hybrid`

2. **트리플 추출** (Graph RAG가 활성화된 경우):
   - LlamaIndex의 Graph Extractor 사용
   - 각 청크에서 (Subject, Predicate, Object) 트리플 추출
   - Entity Dictionary를 사용하여 엔티티 정규화

3. **임베딩 생성**:
   - 각 청크에 대한 벡터 임베딩 생성

**결과**:
- `nodes`: 청크 노드 리스트
- `triples`: 추출된 트리플 리스트
- `embeddings`: 임베딩 벡터 리스트

---

#### **3단계: DB 적재 (Database Storage)**

**상태 업데이트**: `STORING`
```python
await send_pipeline_status(callback_url, job_id, doc_id, kb_id, "STORING")
```

**동작**:
1. **Milvus에 청크 저장**:
   ```python
   await milvus_connector.insert_chunks(kb_id, doc_id, chunks_data, embeddings)
   ```
   - 청크 텍스트와 임베딩을 Milvus 벡터 DB에 저장

2. **Graph Store에 트리플 저장** (Graph RAG가 활성화된 경우):
   - **Fuseki (Ontology)** 또는 **Neo4j** 중 선택된 백엔드에 저장
   ```python
   if graph_store == "fuseki":
       await fuseki_connector.insert_triples(kb_id, doc_id, triples, generate_inverse)
   else:
       await neo4j_connector.insert_triples(kb_id, doc_id, triples, generate_inverse)
   ```

3. **추론 실행** (Inference, 활성화된 경우):
   - 규칙 기반 추론을 통해 추가 트리플 생성

**최종 상태**: `COMPLETED`
```python
await send_pipeline_status(callback_url, job_id, doc_id, kb_id, "COMPLETED")
```

---

## 5. 콜백을 통한 상태 업데이트

### 5.1 Pipeline Status Callback
**함수**: `send_pipeline_status` (ingest_service/app/api/ingest.py, 라인 106-120)

```python
async def send_pipeline_status(callback_url: str, job_id: str, doc_id: str, kb_id: str, status: str):
    if not callback_url:
        return
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.post(callback_url, json={
                "job_id": job_id,
                "doc_id": doc_id,
                "kb_id": kb_id,
                "status": "processing",
                "pipeline_status": status,
            })
    except Exception as e:
        print(f"Failed to send pipeline status: {e}")
```

**호출 시점**:
- `EXTRACTING_ENTITIES`: 엔티티 추출 시작
- `EXTRACTING_TRIPLES`: 트리플 추출 시작
- `STORING`: DB 저장 시작

### 5.2 Backend Callback Handler
**파일**: `backend/app/api/document.py`
**함수**: `ingest_callback` (라인 206-250)

**동작**:
1. 문서 상태 업데이트
2. WebSocket을 통해 프론트엔드에 실시간 상태 전송
```python
await manager.send_document_update(kb_id, doc_id, {
    "id": doc_id,
    "status": payload.status,
    "pipeline_status": payload.pipeline_status,
    # ...
})
```

---

## 6. 전체 흐름 요약

### 6.1 정상 흐름 (Graph RAG 활성화)

```
[프론트엔드]
1. Upload 버튼 클릭
   ↓
2. handleUpload() 실행
   ↓
3. docApi.upload() 호출
   ↓

[백엔드]
4. upload_document() 처리
   - 파일 저장
   - 문서 레코드 생성/업데이트
   - 상태: PROCESSING
   ↓
5. call_ingest_service() (백그라운드)
   ↓

[Ingest Service]
6. create_ingest_job() 
   - Job 생성
   - 상태: PENDING
   ↓
7. process_ingest_job() (백그라운드)
   ↓
   
   [1단계: 엔티티 추출]
   - 상태: EXTRACTING_ENTITIES
   - DictionaryBuilder로 엔티티 추출
   - 엔티티 정규화
   ↓
   
   [2단계: 청킹 및 트리플 추출]
   - 상태: EXTRACTING_TRIPLES
   - 문서 청킹
   - Graph Extractor로 트리플 추출
   - 임베딩 생성
   ↓
   
   [3단계: DB 적재]
   - 상태: STORING
   - Milvus에 청크 저장
   - Fuseki/Neo4j에 트리플 저장
   - 추론 실행 (옵션)
   ↓
   
8. 완료
   - 상태: COMPLETED
   - 콜백 호출
   ↓

[백엔드]
9. ingest_callback() 처리
   - 문서 상태 업데이트
   - WebSocket으로 프론트엔드에 알림
   ↓

[프론트엔드]
10. WebSocket 수신
    - 문서 목록 자동 업데이트
    - 상태 표시 갱신
```

### 6.2 2단계 Preview 흐름 (Extract Entities → Extract Triples → Upload)

```
[프론트엔드]
1. "Extract Entities" 버튼 클릭
   ↓
2. handleExtractEntities() 실행
   ↓
3. extractionApi.previewDictionary() 호출
   ↓

[Ingest Service]
4. preview_dictionary() 처리
   - 엔티티 추출만 수행
   - Preview Cache에 저장
   - preview_id 반환
   ↓

[프론트엔드]
5. Entity Dictionary Modal 표시
   - 사용자가 엔티티 확인/수정
   ↓
6. "Extract Triples" 버튼 클릭
   ↓
7. handleExtractTriples() 실행
   ↓
8. extractionApi.preview() 호출
   - entity_dictionary 전달
   ↓

[Ingest Service]
9. create_preview() 처리
   - 청킹 및 트리플 추출
   - Preview Cache에 저장
   - preview_id 반환
   ↓

[프론트엔드]
10. Extraction Preview Modal 표시
    - 사용자가 트리플 확인
    ↓
11. "Upload" (Confirm Ingestion) 버튼 클릭
    ↓
12. handleUpload() 실행
    ↓
13. extractionApi.confirm() 호출
    ↓

[Ingest Service]
14. confirm_preview() 처리
    ↓
15. _save_preview_data() (백그라운드)
    - 상태: STORING
    - Milvus에 청크 저장
    - Fuseki/Neo4j에 트리플 저장
    - 추론 실행 (옵션)
    ↓
16. 완료
    - 상태: COMPLETED
    - 콜백 호출
```

---

## 7. 현재 구현 상태 확인 포인트

### 7.1 확인해야 할 사항

1. **Ingest Service가 실행 중인가?**
   - 포트 8001에서 실행되어야 함
   - Health Check: `http://127.0.0.1:8001/health`

2. **콜백 URL이 올바른가?**
   - Frontend → Backend: `http://127.0.0.1:8000/api/knowledge-bases/ingest/callback`
   - 백엔드가 8000 포트에서 실행 중이어야 함

3. **WebSocket 연결이 활성화되어 있는가?**
   - 실시간 상태 업데이트를 위해 필요
   - `backend/app/core/websocket_manager.py` 확인

4. **Graph Backend가 설정되어 있는가?**
   - Knowledge Base 생성 시 `graph_backend` 설정
   - `none`, `ontology`, `neo4j` 중 선택

5. **Fuseki/Neo4j가 실행 중인가?** (Graph RAG 사용 시)
   - Fuseki: `http://localhost:3030`
   - Neo4j: `bolt://localhost:7687`

---

## 8. 문제 진단 체크리스트

### 8.1 Upload 버튼 클릭 후 아무 일도 일어나지 않는 경우

- [ ] 브라우저 콘솔에 에러가 있는가?
- [ ] Network 탭에서 API 호출이 실패했는가?
- [ ] Backend 로그에 에러가 있는가?
- [ ] Ingest Service 로그에 에러가 있는가?

### 8.2 엔티티 추출이 완료되지 않는 경우

- [ ] Ingest Service가 실행 중인가?
- [ ] LLM API 키가 설정되어 있는가?
- [ ] 파일 경로가 올바른가?
- [ ] 샘플링 크기가 너무 큰가?

### 8.3 트리플 추출이 완료되지 않는 경우

- [ ] Entity Dictionary가 전달되었는가?
- [ ] Graph Extractor 설정이 올바른가?
- [ ] LLM 호출 제한에 걸렸는가?

### 8.4 DB 적재가 완료되지 않는 경우

- [ ] Milvus가 실행 중인가?
- [ ] Fuseki/Neo4j가 실행 중인가?
- [ ] 연결 정보가 올바른가?
- [ ] 디스크 공간이 충분한가?

---

## 9. 로그 확인 방법

### 9.1 Backend 로그
```bash
# 터미널에서 backend 실행 시 로그 확인
cd backend
uvicorn app.main:app --reload --port 8000
```

### 9.2 Ingest Service 로그
```bash
# 터미널에서 ingest_service 실행 시 로그 확인
cd ingest_service
uvicorn app.main:app --reload --port 8001
```

### 9.3 Frontend 로그
- 브라우저 개발자 도구 → Console 탭
- Network 탭에서 API 호출 상태 확인

---

## 10. 결론

Upload Document 모달의 "Upload" 버튼은 다음과 같은 동작을 수행하도록 구현되어 있습니다:

1. **일반 업로드 모드**:
   - 파일 업로드 → Backend → Ingest Service
   - 3단계 자동 처리: 엔티티 추출 → 청킹/트리플 추출 → DB 적재

2. **2단계 Preview 모드**:
   - Extract Entities → Extract Triples → Upload (Confirm)
   - 각 단계에서 사용자 확인 가능
   - 마지막 Upload는 DB 적재만 수행

현재 구현은 **완전히 구현되어 있으며**, 문제가 발생한다면 위의 체크리스트를 통해 진단할 수 있습니다.
