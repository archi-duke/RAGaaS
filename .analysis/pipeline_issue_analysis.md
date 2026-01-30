# 파이프라인 동작 문제 분석 보고서

## 1. 파이프라인 구조 개요

문서 업로드 시 **엔티티 추출 → 청킹 → 트리플 추출 → 스토리지 적재** 순서로 진행됩니다.

```
[Backend document.py] → [Ingest Client] → [Ingest Service /api/ingest]
                                                    ↓
[Pipeline] Phase 1: Entity Extraction (enable_entity_normalization=True 시)
           Phase 2: Chunking
           Phase 3: Triple Extraction + Embeddings
           Phase 4: Entity Normalization
                                                    ↓
[Milvus] 청크+임베딩 저장  |  [Fuseki/Neo4j] 트리플 저장
```

---

## 2. 발견된 문제점

### 2.1 sampling_size 미전달 (엔티티 추출 품질 저하)

**위치**: `backend/app/services/ingestion/ingest_client.py`

**문제**: `create_ingest_job`에 `sampling_size` 파라미터가 없어 Ingest Service로 전달되지 않음.

**영향**: 
- 문서의 `max_sample_size` (기본 50,000자)가 무시됨
- 파이프라인은 기본값 10,000자만 사용 → 대용량 문서에서 엔티티 추출 범위가 제한됨

**수정**: ingest_client에 `sampling_size` 파라미터 추가 및 payload에 포함

---

### 2.2 청킹 설정 중첩 구조 미처리

**위치**: `backend/app/api/document.py`

**문제**: 프론트엔드가 `chunking_config`를 중첩 객체로 전달:
```javascript
config = {
  chunking_strategy: "fixed_size",
  chunking_config: { chunk_size: 300, chunk_overlap: 20, ... },  // 중첩!
  extractor_type: "simple",
  ...
}
```
`final_config.get("chunk_size")`는 `chunk_size`가 중첩 객체 안에 있어 `None` 반환 → 기본값 300 사용 (실제로는 동일할 수 있으나, `chunk_overlap` 등 다른 값도 누락 가능)

**수정**: 중첩된 `chunking_config`를 병합하여 사용
```python
nested = final_config.get("chunking_config") or {}
chunk_size = final_config.get("chunk_size") or nested.get("chunk_size", 300)
```

---

### 2.3 Docker 환경에서 콜백 URL 오류

**위치**: `backend/app/api/document.py` (라인 152)

**문제**: 콜백 URL이 `http://127.0.0.1:8000/...`로 고정됨.
- Docker에서 Ingest Service는 별도 컨테이너에서 실행
- Ingest Service가 `127.0.0.1:8000`으로 POST 시도 → 백엔드에 도달하지 못함 (같은 컨테이너의 localhost에 연결 시도)

**수정**: 환경 변수 또는 설정 기반 콜백 URL 사용
```python
callback_base = os.getenv("CALLBACK_BASE_URL", "http://127.0.0.1:8000")
callback_url = f"{callback_base}/api/knowledge-bases/ingest/callback"
```

---

### 2.4 graph_config 누락 필드

**위치**: `backend/app/api/document.py` → `ingest_client`

**문제**: `graph_config`에 `allowed_entity_types`, `allowed_relation_types`가 document.py에서 설정되지 않음. (선택 사항이므로 치명적이진 않음)

---

### 2.5 파일 경로 해석 (Docker vs 로컬)

**위치**: `ingest_service/app/utils/file_utils.py`

**상황**: 
- Backend: `file_path = /data/uploads/{kb_id}/{doc_id}_{filename}` (Docker 시)
- Ingest Service: 동일한 경로로 파일 읽기 시도
- Docker Compose에서 `./data/uploads:/data/uploads`로 양쪽에 마운트되어 있으면 동일 경로 사용 가능

**확인 필요**: 로컬 개발 시 Backend와 Ingest Service의 `SHARED_STORAGE_PATH`가 동일한 디렉터리를 가리키는지 확인

---

## 3. 수정 적용 사항 (완료)

1. **ingest_client.py**: `sampling_size` 파라미터 추가 및 payload 전달 ✅
2. **document.py**: 
   - 중첩 `chunking_config` 병합 로직 추가 ✅
   - `sampling_size`(doc.max_sample_size) ingest_client에 전달 ✅
   - 콜백 URL을 환경 변수(`CALLBACK_BASE_URL`) 기반으로 변경 ✅
   - `doc_id`를 `str(doc.id)`로 명시적 변환 ✅
3. **docker-compose.yml**: Backend에 `CALLBACK_BASE_URL=http://backend:8000` 추가 ✅
