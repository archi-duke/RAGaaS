# Status 업데이트 및 임시 파일 저장 개선 계획

## 📋 현재 문제점

### 1. Status 업데이트 문제
**기대 동작**:
```
Entities... → Entities (완료, 아주 잠깐) → Triples... → Triples (완료, 아주 잠깐) → Storing → Published
```

**현재 상태**:
- Status가 제대로 반영되지 않음
- 중간 단계 완료 상태가 표시되지 않음

### 2. 임시 파일 저장 문제
**요구사항**:
- 일괄 진행 모드에서도 임시 저장 파일들이 생성되어야 함
- Entity Dictionary, Triples 등의 중간 결과물을 파일로 저장

---

## 🔍 현재 코드 분석

### Status 전송 위치

#### 1. **Ingest Service** (`ingest_service/app/api/ingest.py`)

**`send_pipeline_status()` 함수** (라인 106-120):
```python
async def send_pipeline_status(callback_url: str, job_id: str, doc_id: str, kb_id: str, status: str):
    """Helper to send granular pipeline status to backend"""
    if not callback_url: return
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            await client.post(callback_url, json={
                "job_id": job_id,
                "doc_id": doc_id,
                "kb_id": kb_id,
                "status": "processing",  # ⚠️ 항상 "processing"으로 고정
                "pipeline_status": status
            })
    except Exception as e:
        print(f"[Callback] Failed to send status {status}: {e}")
```

**호출 위치**:
1. `process_ingest_job()` (라인 168): Pipeline 콜백을 통해 호출
2. `_save_preview_data()` (라인 612): `STORING` 상태만 전송
3. `create_dictionary_preview()` (라인 758): `EXTRACTING_ENTITIES` 상태만 전송

#### 2. **Pipeline** (`ingest_service/app/core/pipeline.py`)

**Status Callback 호출** (라인 360-361, 389-390):
```python
# 엔티티 추출 시작
if status_callback:
    await status_callback("EXTRACTING_ENTITIES")

# 트리플 추출 시작
if status_callback:
    await status_callback("EXTRACTING_TRIPLES")
```

**문제점**:
- ✅ 시작 상태만 전송 (`EXTRACTING_ENTITIES`, `EXTRACTING_TRIPLES`)
- ❌ 완료 상태 미전송 (`ENTITY_EXTRACTED`, `TRIPLE_EXTRACTED`)
- ❌ `STORING` 상태는 `process_ingest_job`에서 전송하지 않음 (Preview 모드에서만 전송)

---

## 🎯 개선 계획

### Phase 1: Status 업데이트 개선

#### 1.1 Pipeline에서 완료 상태 추가

**파일**: `ingest_service/app/core/pipeline.py`

**수정 위치**:
- 엔티티 추출 완료 후: `ENTITY_EXTRACTED` 전송
- 트리플 추출 완료 후: `TRIPLE_EXTRACTED` 전송

**변경 사항**:
```python
# Before
if status_callback:
    await status_callback("EXTRACTING_ENTITIES")
# ... 엔티티 추출 로직 ...

# After
if status_callback:
    await status_callback("EXTRACTING_ENTITIES")
# ... 엔티티 추출 로직 ...
if status_callback:
    await status_callback("ENTITY_EXTRACTED")  # ✅ 추가
```

#### 1.2 process_ingest_job에서 STORING 상태 추가

**파일**: `ingest_service/app/api/ingest.py`

**수정 위치**: `process_ingest_job()` 함수 (라인 196 이전)

**변경 사항**:
```python
# Before
# 5. Save (Milvus, Neo4j/Fuseki)
print(f"[IngestJob] Saving to databases for doc {request.doc_id}...")

# After
# 5. Save (Milvus, Neo4j/Fuseki)
await send_pipeline_status(request.callback_url, job_id, request.doc_id, request.kb_id, "STORING")  # ✅ 추가
print(f"[IngestJob] Saving to databases for doc {request.doc_id}...")
```

#### 1.3 완료 후 PUBLISHED 상태 전송

**파일**: `ingest_service/app/api/ingest.py`

**수정 위치**: `process_ingest_job()` 함수 (라인 280 이후)

**변경 사항**:
```python
# Before
jobs[job_id]["result"] = {...}
jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
print(f"[IngestJob] ✅ Job {job_id} COMPLETED for doc {request.doc_id}")

# After
jobs[job_id]["result"] = {...}
jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
print(f"[IngestJob] ✅ Job {job_id} COMPLETED for doc {request.doc_id}")

# Send PUBLISHED status
await send_pipeline_status(request.callback_url, job_id, request.doc_id, request.kb_id, "PUBLISHED")  # ✅ 추가
```

---

### Phase 2: 임시 파일 저장 구현

#### 2.1 임시 파일 저장 위치 정의

**저장 경로 구조**:
```
{SHARED_STORAGE_PATH}/
  └── {kb_id}/
      └── {doc_id}/
          ├── original_{filename}          # 원본 파일
          ├── entity_dictionary.json       # 엔티티 사전
          ├── chunks.json                  # 청크 목록
          ├── triples.json                 # 트리플 목록
          └── metadata.json                # 메타데이터 (통계 등)
```

#### 2.2 파일 저장 유틸리티 함수 생성

**새 파일**: `ingest_service/app/utils/temp_storage.py`

```python
import os
import json
from typing import Dict, Any, List
from datetime import datetime

class TempStorage:
    """임시 파일 저장 관리"""
    
    def __init__(self, base_path: str = "/data/temp"):
        self.base_path = base_path
    
    def get_doc_path(self, kb_id: str, doc_id: str) -> str:
        """문서별 임시 저장 경로 반환"""
        path = os.path.join(self.base_path, kb_id, doc_id)
        os.makedirs(path, exist_ok=True)
        return path
    
    async def save_entity_dictionary(
        self, 
        kb_id: str, 
        doc_id: str, 
        dictionary: Dict[str, Any]
    ) -> str:
        """엔티티 사전 저장"""
        path = self.get_doc_path(kb_id, doc_id)
        file_path = os.path.join(path, "entity_dictionary.json")
        
        data = {
            "created_at": datetime.utcnow().isoformat(),
            "entity_count": len(dictionary),
            "dictionary": dictionary
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[TempStorage] Saved entity dictionary: {file_path}")
        return file_path
    
    async def save_chunks(
        self, 
        kb_id: str, 
        doc_id: str, 
        chunks: List[Dict[str, Any]]
    ) -> str:
        """청크 목록 저장"""
        path = self.get_doc_path(kb_id, doc_id)
        file_path = os.path.join(path, "chunks.json")
        
        data = {
            "created_at": datetime.utcnow().isoformat(),
            "chunk_count": len(chunks),
            "chunks": chunks
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[TempStorage] Saved chunks: {file_path}")
        return file_path
    
    async def save_triples(
        self, 
        kb_id: str, 
        doc_id: str, 
        triples: List[Dict[str, Any]]
    ) -> str:
        """트리플 목록 저장"""
        path = self.get_doc_path(kb_id, doc_id)
        file_path = os.path.join(path, "triples.json")
        
        data = {
            "created_at": datetime.utcnow().isoformat(),
            "triple_count": len(triples),
            "triples": triples
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[TempStorage] Saved triples: {file_path}")
        return file_path
    
    async def save_metadata(
        self, 
        kb_id: str, 
        doc_id: str, 
        metadata: Dict[str, Any]
    ) -> str:
        """메타데이터 저장"""
        path = self.get_doc_path(kb_id, doc_id)
        file_path = os.path.join(path, "metadata.json")
        
        data = {
            "created_at": datetime.utcnow().isoformat(),
            **metadata
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[TempStorage] Saved metadata: {file_path}")
        return file_path
    
    async def load_entity_dictionary(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        """엔티티 사전 로드"""
        path = self.get_doc_path(kb_id, doc_id)
        file_path = os.path.join(path, "entity_dictionary.json")
        
        if not os.path.exists(file_path):
            return None
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return data.get("dictionary")
    
    async def cleanup(self, kb_id: str, doc_id: str):
        """임시 파일 정리"""
        import shutil
        path = self.get_doc_path(kb_id, doc_id)
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"[TempStorage] Cleaned up: {path}")

# Singleton instance
temp_storage = TempStorage()
```

#### 2.3 Pipeline에서 임시 파일 저장 호출

**파일**: `ingest_service/app/core/pipeline.py`

**수정 위치**:
1. 엔티티 추출 완료 후
2. 청킹 완료 후
3. 트리플 추출 완료 후

**변경 사항**:
```python
# 엔티티 추출 완료 후
if status_callback:
    await status_callback("ENTITY_EXTRACTED")

# ✅ 임시 파일 저장 추가
if kb_id and doc_id:  # 필요한 경우에만
    from app.utils.temp_storage import temp_storage
    await temp_storage.save_entity_dictionary(kb_id, doc_id, entity_dictionary)
```

#### 2.4 process_ingest_job에서 임시 파일 저장

**파일**: `ingest_service/app/api/ingest.py`

**수정 위치**: `process_ingest_job()` 함수

**변경 사항**:
```python
# Pipeline 처리 완료 후
result = await ingest_pipeline.process(...)

# ✅ 임시 파일 저장
from app.utils.temp_storage import temp_storage

if result.get("entity_dictionary"):
    await temp_storage.save_entity_dictionary(
        request.kb_id, 
        request.doc_id, 
        result["entity_dictionary"]
    )

if result.get("nodes"):
    chunks_data = [{"content": node.get_content(), "metadata": node.metadata} 
                   for node in result["nodes"]]
    await temp_storage.save_chunks(request.kb_id, request.doc_id, chunks_data)

if result.get("triples"):
    await temp_storage.save_triples(request.kb_id, request.doc_id, result["triples"])

# 메타데이터 저장
await temp_storage.save_metadata(request.kb_id, request.doc_id, {
    "node_count": result["node_count"],
    "triple_count": result["triple_count"],
    "stats": result.get("stats", [])
})
```

---

### Phase 3: Pipeline에서 kb_id, doc_id 전달

**문제**: 현재 `pipeline.process()`는 `kb_id`, `doc_id`를 받지 않음

**해결 방법**:

#### 3.1 Pipeline 함수 시그니처 수정

**파일**: `ingest_service/app/core/pipeline.py`

**변경 사항**:
```python
# Before
async def process(
    self,
    text: str,
    chunking_strategy: str = "fixed_size",
    # ... 기타 파라미터
    status_callback: Optional[any] = None
):

# After
async def process(
    self,
    text: str,
    chunking_strategy: str = "fixed_size",
    # ... 기타 파라미터
    kb_id: Optional[str] = None,  # ✅ 추가
    doc_id: Optional[str] = None,  # ✅ 추가
    status_callback: Optional[any] = None
):
```

#### 3.2 호출부 수정

**파일**: `ingest_service/app/api/ingest.py`

**변경 사항**:
```python
# process_ingest_job()
result = await ingest_pipeline.process(
    text=text,
    # ... 기타 파라미터
    kb_id=request.kb_id,  # ✅ 추가
    doc_id=request.doc_id,  # ✅ 추가
    status_callback=pipeline_callback
)

# create_preview()
result = await ingest_pipeline.process(
    text=text,
    # ... 기타 파라미터
    kb_id=request.kb_id,  # ✅ 추가
    doc_id=request.doc_id,  # ✅ 추가
    status_callback=pipeline_callback
)
```

---

## 📝 구현 순서

### Step 1: Status 업데이트 개선 (우선순위: 높음)
1. ✅ `pipeline.py`에 완료 상태 추가
   - `ENTITY_EXTRACTED` 전송
   - `TRIPLE_EXTRACTED` 전송

2. ✅ `ingest.py`의 `process_ingest_job()`에 상태 추가
   - `STORING` 전송 (DB 저장 시작 전)
   - `PUBLISHED` 전송 (완료 후)

3. ✅ `_save_preview_data()`에 완료 상태 추가
   - `PUBLISHED` 전송 (완료 후)

### Step 2: 임시 파일 저장 구현 (우선순위: 중간)
1. ✅ `temp_storage.py` 유틸리티 생성
2. ✅ `pipeline.py`에 kb_id, doc_id 파라미터 추가
3. ✅ `pipeline.py`에서 임시 파일 저장 호출
4. ✅ `process_ingest_job()`에서 임시 파일 저장 호출

### Step 3: 테스트 및 검증
1. ✅ 일괄 업로드 테스트
   - Status 순서 확인: `Entities...` → `Entities` → `Triples...` → `Triples` → `Storing` → `Published`
   - 임시 파일 생성 확인

2. ✅ Preview 모드 테스트
   - Extract Entities → Extract Triples → Upload 흐름
   - 각 단계별 임시 파일 확인

---

## 🎯 예상 결과

### Status 업데이트 흐름 (일괄 모드)

```
1. EXTRACTING_ENTITIES    (엔티티 추출 시작)
   ↓
2. ENTITY_EXTRACTED       (엔티티 추출 완료) ← ✅ 추가
   ↓
3. EXTRACTING_TRIPLES     (트리플 추출 시작)
   ↓
4. TRIPLE_EXTRACTED       (트리플 추출 완료) ← ✅ 추가
   ↓
5. STORING                (DB 저장 시작) ← ✅ 추가
   ↓
6. PUBLISHED              (완료) ← ✅ 추가
```

### 임시 파일 구조

```
/data/temp/
  └── {kb_id}/
      └── {doc_id}/
          ├── entity_dictionary.json     ← ✅ 엔티티 사전
          ├── chunks.json                ← ✅ 청크 목록
          ├── triples.json               ← ✅ 트리플 목록
          └── metadata.json              ← ✅ 메타데이터
```

---

## 🔧 추가 고려사항

### 1. 임시 파일 정리 정책
- **옵션 A**: 완료 후 자동 삭제 (디스크 절약)
- **옵션 B**: 일정 기간 보관 후 삭제 (디버깅 용이)
- **옵션 C**: 사용자가 명시적으로 삭제할 때까지 보관

**권장**: 옵션 B (24시간 보관 후 자동 삭제)

### 2. 대용량 파일 처리
- JSON 파일이 너무 클 경우 압축 저장 고려
- 또는 청크 단위로 분할 저장

### 3. 에러 처리
- 임시 파일 저장 실패 시 로그만 남기고 계속 진행
- 중요한 데이터는 DB에 저장되므로 임시 파일은 보조 수단

### 4. 프론트엔드 상태 표시
- 각 상태에 맞는 UI 업데이트 필요
- `ENTITY_EXTRACTED`, `TRIPLE_EXTRACTED`는 아주 짧게 표시 (0.5초 정도)

---

## 📊 변경 파일 목록

### 수정 파일
1. `ingest_service/app/core/pipeline.py`
   - 완료 상태 전송 추가
   - kb_id, doc_id 파라미터 추가
   - 임시 파일 저장 호출 추가

2. `ingest_service/app/api/ingest.py`
   - `process_ingest_job()`: STORING, PUBLISHED 상태 추가
   - `_save_preview_data()`: PUBLISHED 상태 추가
   - 임시 파일 저장 호출 추가

### 신규 파일
1. `ingest_service/app/utils/temp_storage.py`
   - 임시 파일 저장/로드 유틸리티

---

## ✅ 체크리스트

### Phase 1: Status 업데이트
- [ ] `pipeline.py`: ENTITY_EXTRACTED 전송 추가
- [ ] `pipeline.py`: TRIPLE_EXTRACTED 전송 추가
- [ ] `ingest.py`: process_ingest_job()에 STORING 추가
- [ ] `ingest.py`: process_ingest_job()에 PUBLISHED 추가
- [ ] `ingest.py`: _save_preview_data()에 PUBLISHED 추가

### Phase 2: 임시 파일 저장
- [ ] `temp_storage.py` 생성
- [ ] `pipeline.py`: kb_id, doc_id 파라미터 추가
- [ ] `pipeline.py`: 엔티티 사전 저장 추가
- [ ] `process_ingest_job()`: 모든 중간 결과 저장 추가
- [ ] 호출부 수정 (kb_id, doc_id 전달)

### Phase 3: 테스트
- [ ] 일괄 업로드 테스트
- [ ] Preview 모드 테스트
- [ ] 임시 파일 생성 확인
- [ ] Status 순서 확인
- [ ] 에러 케이스 테스트
