# 인제스트/삭제 진행률·오류알림·무결성·멀티유저 동시성 개선 설계

> 상태: 검증 완료 (Reviewed, 2026-07-17) — 라인 번호/코드 인용 대조 확인, WS 채널 키 불일치 버그 실증 확인. 구현 전, 착수 순서는 §1.4 참조.
> 관련 문서: `docs/design-query-generation-loop.md` (스타일 참고), `docs/platform-contract/05`(플랫폼 신원 확정 계약, `backend/app/core/platform_auth.py`가 어댑터)

---

## 1. 배경 및 목표

### 1.1 시스템 개요

RAGaaS는 3개 서비스로 구성된다.

- **backend** (FastAPI, `:8000`) — REST API, WebSocket relay, ingest_service로부터의 콜백 수신.
- **ingest_service** (FastAPI, `:8001`) — 실제 인제스트 파이프라인(청킹/임베딩/그래프 추출/저장) 실행. `backend/app/services/ingestion/ingest_client.py`가 `POST {INGEST_SERVICE_URL}/api/ingest`로 호출한다.
- **frontend** (React, Module Federation remote).

인프라는 Milvus(원격 `192.168.219.115`), Fuseki, Neo4j, 외부 Mongo로 구성되며, **Redis는 배포 설정(`deploy/docker-compose.yml`)에 `REDIS_URL`이 이미 필수 환경변수로 선언되어 있으나 애플리케이션 코드에서는 사용되지 않는다** — `ingest_service/app/core/config.py:17`에 `REDIS_URL: str = "redis://localhost:6379/0"` 기본값만 정의되어 있고, 이 값을 읽어 쓰는 코드는 없다. 즉 Redis 인프라는 이미 배포 계층에서 준비되어 있고, 애플리케이션이 아직 이를 활용하지 않는 상태다.

인제스트 실행 흐름은 `ingest_service/app/api/ingest.py`의 `create_ingest_job`(374-402행)이 `BackgroundTasks.add_task(process_ingest_job, ...)`(396행)로 트리거하며, 작업 상태는 같은 파일 26행의 **인메모리 dict** `jobs: Dict[str, Dict[str, Any]] = {}`에 보관된다(주석: `# In-memory job storage (In production, use Redis or a Database)`).

### 1.2 확인된 문제

#### 1.2.1 진행률(인제스트) — 부분적, 침묵 구간 존재

- `jobs` dict의 `progress` 필드는 파이프라인 실행 중 딱 4개 고정 지점에서만 갱신된다: `=10`(187행, subject restoration 이후), `=80`(248행, `ingest_pipeline.process` 완료 후), `=90`(282행, Milvus insert 후), `=100`(309행, 그래프 저장 후). **10~80 사이(청킹, 임베딩, 엔티티/트리플 추출)에는 progress 값이 전혀 갱신되지 않는다.**
- `ingest_service/app/core/pipeline.py`는 `status_callback`(819행 파라미터)을 통해 `EXTRACTING_ENTITIES`(857-858행)/`ENTITY_EXTRACTED`(871-872행)/`EXTRACTING_TRIPLES`(907-908행)/`TRIPLE_EXTRACTED`(922-923행) 4개의 **텍스트 상태**만 방출한다. 청킹·임베딩 단계에는 이 콜백 호출 자체가 없다. 즉 파이프라인 내부에도 숫자 progress 개념이 없다.
- `send_pipeline_status`(ingest.py 133-150행)는 `callback_url`로 `{job_id, doc_id, kb_id, status, pipeline_status}`를 POST하지만 **숫자 progress 필드가 없고, 실패 경로에서는 호출되지 않는다**(성공 흐름에만 위치).
- backend `document.py`의 `ingest_callback`(650-719행 부근)은 콜백을 받아 Mongo `Document.status`/`pipeline_status`를 갱신하고 `manager.broadcast`로 WS 전파한다(704-712행). 이 페이로드에도 숫자 progress는 없다.
- frontend `DocumentsTab.tsx`의 `getStatusBadge`(112-148행)는 `pipeline_status` 문자열을 배지 텍스트로만 매핑한다(`EXTRACTING_ENTITIES`→"Entities...", `STORING`→"Storing" 등). **퍼센트 진행바는 없다.**

#### 1.2.2 진행률(삭제) — 없음

- `backend/app/api/document.py`의 `delete_document`(605-648행)는 `doc.status`를 `DELETING`→(성공 시 레코드 삭제)로 2단계만 관리하며, `await cleanup_service.perform_cascading_deletion(...)`(617행 주석: `# EXECUTE SYNCHRONOUSLY (WAIT) to ensure completion`)를 **동기적으로 대기**한다. 중간 이벤트는 전혀 없다.
- `cleanup_service.py`의 `perform_cascading_deletion`(13행~)은 Milvus 청크 조회 → Fuseki 삭제 → Neo4j 삭제 → Milvus 삭제 → 파일시스템 정리 → 무결성 검증 → Mongo 문서 삭제의 7단계를 거치지만, 각 단계는 `print()`로만 로그를 남기고 WS 브로드캐스트는 **341-350행 딱 한 번, 맨 끝에서만** 발생한다.

#### 1.2.3 오류처리/알림 — 취약하거나 없음

- 인제스트 실패 시 `jobs[job_id]["status"] = JobStatus.FAILED`(368행)와 `error` 메시지(369행, `_format_model_error_message` 가공)가 인메모리 dict에만 남는다. **실패 콜백이 전송되지 않으므로**(성공 경로에만 `send_pipeline_status(... "COMPLETED")`와 `callback_url` POST가 있음, 348·353-362행) backend/frontend는 실패를 전혀 알 수 없다. `_save_preview_data`(765-863행, Confirm 경로)도 동일 패턴(857-863행: 실패 시 `jobs` dict 갱신만, 콜백 없음).
- backend `IngestCallback` 모델(650-657행)에는 이미 `error: Optional[str] = None` 필드가 정의돼 있지만, `status == "failed"` 분기(693-694행)는 `doc.status = DocumentStatus.ERROR.value`만 설정할 뿐 `payload.error`를 어디에도 저장하지 않는다. 게다가 `backend/app/models/document.py`의 `Document` 모델(15-50행)에는 애초에 오류 메시지를 담을 필드(`error`/`error_message`)가 없다 — 콜백 페이로드에 에러가 실려 와도 영속화할 곳이 없다.
- 삭제 실패는 `cleanup_service.py`의 각 하위 단계 `except Exception as e: print(...)`로 **삼켜진다**(Fuseki 162행, Neo4j 212-213행, Milvus 240-241행 등). 무결성 검증 실패 시에도 원래 있던 `raise RuntimeError(error_msg)`가 **주석 처리**되어 있다(299행: `# raise RuntimeError(error_msg)  <-- REMOVED: Do not block deletion`) — 검증에 실패해도 삭제를 계속 진행한다.
- `deleting`/`processing` 상태에서 프로세스가 죽거나 예외 없이 멈추면(예: 인제스트 워커 크래시, cleanup_service 중간 크래시) 문서가 영구히 해당 상태에 머무르는 **stuck 상태 복구 로직이 없다.**
- **전역 토스트/알림 시스템이 없다.** frontend에 `react-hot-toast`/`react-toastify`/`sonner`/`notistack` 등 알림 라이브러리가 설치되어 있지 않고(package.json 확인), `Notification` 브라우저 API 사용도 없다. `DocumentsTab.tsx`는 오류를 `alert()`로만 노출한다(예: 102·106행).

#### 1.2.4 WebSocket 브로드캐스트 채널 불일치 (신규 발견 — 조사 중 확인)

이번 조사에서 브리프에 없던 **구조적 버그**를 확인했다. `backend/app/api/websocket_endpoint.py`의 `/ws/{kb_id}` 엔드포인트는 연결을 다음과 같이 등록한다.

```python
# websocket_endpoint.py 8-18행
channel_id = f"kb_{kb_id}"          # "kb_" 접두어 부여
await manager.connect(websocket, channel_id)
```

반면 `manager.broadcast(...)`를 호출하는 **모든** 지점은 접두어 없는 원본 `kb_id`를 그대로 넘긴다.

| 파일:행 | 호출부 |
|---|---|
| `backend/app/api/document.py:365` | 업로드 직후 초기 상태 브로드캐스트 |
| `backend/app/api/document.py:589` | 인제스트 트리거 직후 초기 상태 브로드캐스트 |
| `backend/app/api/document.py:704` | `ingest_callback` 처리 후 진행 상태 브로드캐스트 |
| `backend/app/services/ingestion/cleanup_service.py:343` | 삭제 완료 브로드캐스트 |
| `backend/app/services/ingestion/service.py:193, 210` | 레거시 인제스트 경로 브로드캐스트 |
| `backend/app/services/ingestion/legacy/service.py:178, 195` | 레거시 인제스트 경로 브로드캐스트 |

`backend/app/core/websocket_manager.py`의 `ConnectionManager`는 `active_connections: Dict[str, List[WebSocket]]`를 **문자열 그대로** 키로 사용한다(15행 `connect(websocket, kb_id)`, 34행 `broadcast(kb_id, message)` — 둘 다 접두어를 붙이거나 벗기지 않음). 따라서 클라이언트는 `kb_{kb_id}` 키 아래 등록되는데 서버는 항상 `{kb_id}`(접두어 없음) 키로 브로드캐스트하므로, **두 키가 절대 일치하지 않는다.** `broadcast()`는 36-38행에서 `if kb_id not in self.active_connections: logger.warning(...); return`으로 조용히 종료되므로 예외도 나지 않는다.

결과적으로 **현재 배포 상태에서 WS를 통한 진행률/완료/삭제 알림은 구조적으로 단 하나도 프론트엔드에 도달하지 않는다.** 오늘 적용된 이벤트루프 블로킹 수정(§11)은 WS 연결 자체(`ws.onopen`)가 끊기지 않게 만든 것이지, 이 브로드캐스트 라우팅 버그와는 무관하다 — 소켓은 열리지만 서버가 보내는 메시지가 해당 소켓이 속한 채널로 전달되지 않는다. 이 버그는 **Phase A의 최우선 항목**이어야 한다(§4.0) — 이후 추가할 progress/에러 페이로드도 이 경로가 고쳐지지 않으면 전부 무의미하다.

#### 1.2.5 무결성 — 부분적이거나 없음

- 삭제 시 `_verify_cleanup`(cleanup_service.py 370-417행)이 Fuseki/Neo4j/Milvus 잔여 데이터를 확인하지만, 실패해도 로그만 남기고(297-299행) 재시도·차단·후속 조치가 없다.
- 인제스트 완료 후 **검증이 전혀 없다** — 벡터 개수와 청크 개수 대조, reification 트리플의 `chunk_id`와 Milvus `chunk_id` 대조 등 어떤 정합성 확인도 수행되지 않는다.
- **`chunk_id` 불일치 근본 원인 버그**를 정확한 코드 위치로 확인했다. 정상(직접 인제스트) 경로인 `ingest.py`의 `process_ingest_job`은 266-271행에서 `chunks_data`에 `node_id`를 포함시킨다:

  ```python
  # ingest.py 266-271행 (직접 인제스트 경로 — 정상)
  chunks_data = [{
      "content": node.get_content(),
      "metadata": node.metadata,
      "node_id": node.node_id  # LlamaIndex node_id 포함
  } for node in result["nodes"]]
  ```

  반면 Preview/Confirm 2단계 경로의 `_save_preview_data`(765-863행)는 **`node_id`를 빠뜨린다**:

  ```python
  # ingest.py 788행 (Confirm 경로 — 버그)
  chunks_data = [{"content": node.get_content(), "metadata": node.metadata} for node in cached["nodes"]]
  ```

  `ingest_service/app/core/milvus_connector.py`의 `insert_chunks`(68-101행)는 80-87행에서 `node_id`가 없으면 `f"{doc_id}_{i}"` 형태의 폴백 ID를 생성한다:

  ```python
  # milvus_connector.py 80-87행
  chunk_ids = []
  for i, chunk in enumerate(chunks):
      node_id = chunk.get("node_id")
      if node_id:
          chunk_ids.append(node_id)
      else:
          chunk_ids.append(f"{doc_id}_{i}")   # ← Confirm 경로는 항상 이쪽
  ```

  하지만 그래프 저장 단계(Fuseki reification의 `meta:sourceNodeId`, Neo4j `source_node_id`)는 여전히 원본 `node.node_id`를 그대로 사용한다. 따라서 **Confirm(Preview 확정) 경로로 저장된 문서는 Milvus의 `chunk_id`(`{doc_id}_{i}` 형태)와 그래프의 `source_node_id`(LlamaIndex 원본 node_id)가 서로 불일치**하게 되고, 청크 기반 그래프-벡터 조인이 깨진다. 오늘 관측된 문제(B2)의 데이터 생성 단계 근본 원인이 바로 이것이다.
- Milvus↔그래프스토어 적재 사이에 트랜잭션이 없다. 한쪽만 저장되고 다른 쪽이 실패해도 롤백/보상 로직이 없어 orphan 데이터가 남는다.

#### 1.2.6 동시성 — 제어 전무

- 인제스트 트리거는 `BackgroundTasks.add_task(process_ingest_job, ...)`(ingest.py 396행)로, **API 프로세스와 같은 프로세스·같은 이벤트루프**에서 실행된다. 동시에 여러 작업이 들어와도 동시성 상한이 없다 — `pipeline.py` 666행의 `asyncio.Semaphore(num_workers)`는 **작업 하나 내부**의 노드 단위 그래프 추출 병렬도를 제한할 뿐, 작업 간(job-to-job) 동시성과는 무관하다.
- `jobs` dict는 인메모리라 재시작 시 전부 유실되고, ingest_service를 여러 인스턴스로 띄워도 상태가 공유되지 않는다. `ingest_service/app/workers/`에는 `__init__.py`만 존재해 큐 워커가 실제로 구현되어 있지 않다. uvicorn은 단일 프로세스로 실행된다(**구현 시 확인**: 현재 워커 프로세스 수 설정을 배포 스크립트에서 재확인).
- 결과적으로 무거운 인제스트(대용량 문서, 다수 트리플 추출) 하나가 이벤트루프를 오래 점유하면 같은 프로세스의 다른 API 요청(다른 사용자의 작업 생성/조회 포함)이 함께 지연된다. 폭주 시 임베딩/LLM API 레이트리밋 초과 위험도 크며, 사용자 간 공정성·작업 영속성·큐 가시성이 전혀 없다.
- 참고로 backend에는 플랫폼 신원 확정 미들웨어(`backend/app/core/platform_auth.py`)가 있어 요청마다 `request.state.user_id`가 확정된다. 그러나 `backend/app/services/ingestion/ingest_client.py`의 `create_ingest_job`(20-77행) 페이로드에는 **`user_id`가 포함되지 않는다** — ingest_service의 `IngestRequest`(ingest.py 85-110행)에도 `user_id` 필드가 없다. 사용자별 공정성/동시 실행 상한을 구현하려면 이 값을 backend→ingest_service 요청 경로에 새로 실어야 한다(§3.1, §8).

### 1.3 목표

1. **진행률**: 인제스트(청킹→임베딩→추출→저장)와 삭제(그래프→벡터→파일→검증→레코드) 각 단계에서 숫자 progress와 stage 텍스트를 프론트까지 실시간 전달한다.
2. **오류 알림**: 실패를 어느 단계에서든 즉시 감지해 사용자에게 구체적 사유와 함께 노출한다(콜백/WS/토스트 체인 전체 관통).
3. **무결성 보장**: 저장 직후 벡터-그래프 정합성을 검증하고, 부분 실패 시 orphan 없이 정리(보상 트랜잭션)한다.
4. **멀티유저 동시성**: 무거운 작업 하나가 전체 서비스를 막지 못하도록 큐·워커를 분리하고, 사용자 간 공정성을 확보한다.

### 목표가 아닌 것 (비목표)

- 수평 오토스케일링(워커 컨테이너의 자동 증감) — 워커를 "여러 개 띄울 수 있는 구조"까지만 만들고, 오토스케일러 연동은 향후 과제로 남긴다.
- Celery 등 다른 태스크 큐 프레임워크 도입 — §1.4의 결정에 따라 async 워커 + Redis 자체 구현을 택한다.
- Milvus/Fuseki/Neo4j 자체의 고가용성·복제 개선.
- 실시간 협업(같은 문서를 여러 사용자가 동시 편집) 충돌 해결 — 범위는 인제스트/삭제 "작업"의 동시성이지 "데이터" 동시 편집이 아니다.

### 1.4 설계 결정 및 착수 순서

- **큐 구현**: async 워커 + Redis. RQ(레디스 큐, 동기 워커 기반)가 아니라 **async-native 자체 구현**을 택한다 — 파이프라인(`ingest_pipeline.process`, `httpx.AsyncClient` 기반 LLM/임베딩 호출)이 이미 철저히 async이므로, RQ처럼 동기 프로세스 풀로 감싸면 오히려 async I/O 이점을 잃는다.
- **워커 배치**: API 프로세스와 **별도 컨테이너**로 분리한다. 오늘까지의 문제(무거운 작업 하나가 전체를 막음)의 구조적 해법은 "같은 이벤트루프에서 실행하지 않는 것"이며, 스레드 격리(오늘 적용한 Milvus 블로킹 콜 격리 패턴)만으로는 근본 해결이 안 된다.
- **착수 순서**: `Phase A(Quick Wins) + 무결성 #8(chunk_id 근본수정)` → `Phase D(큐/워커)` → `Phase B(진행률·알림 UI)` / `Phase C(무결성 나머지)`. 이유: A는 배포 리스크가 낮고 즉시 사용자 체감 개선이 크며, chunk_id 버그는 데이터가 더 쌓이기 전에 막아야 한다. D는 이후 B/C가 큐 기반 콜백 구조 위에서 설계되게 하는 선행 인프라다.

---

## 2. 전체 아키텍처

### 2.1 현재 구조 (Phase D 이전)

```
                         ┌─────────────────────────────────────────┐
                         │  ingest_service (:8001, 단일 프로세스)    │
   backend (:8000)       │                                           │
   ┌────────────────┐    │  create_ingest_job()                     │
   │ POST /documents │───▶│    └─ BackgroundTasks.add_task(          │
   │ .../upload      │    │         process_ingest_job)  ← 같은      │
   └────────────────┘    │         이벤트루프에서 실행               │
          │               │                                           │
          │ callback_url  │  jobs: Dict[str, dict]  (인메모리, 재시작 시│
          │◀──────────────│  유실, 다중 인스턴스 간 공유 불가)         │
          ▼               └─────────────────────────────────────────┘
   ingest_callback()
   Mongo Document 갱신
          │
          ▼
   manager.broadcast(kb_id, ...)   ✕  채널 키 불일치로 미도달 (§1.2.4)
          │
          ▼ (도달하지 않음)
   frontend WS (/ws/{kb_id} → 내부적으로 "kb_"+{kb_id} 채널 구독)
```

무거운 인제스트 작업이 `process_ingest_job` 안에서 실행되는 동안, 같은 프로세스가 처리해야 하는 다른 API 요청(다른 사용자의 job 생성, job 조회 등)도 이벤트루프 경합에 함께 지연된다. 워커라는 개념이 없고, API 서버 자체가 워커를 겸한다.

### 2.2 목표 구조 (Phase D 이후)

```
┌──────────────────┐        ┌───────────────────────┐        ┌─────────────────────────────┐
│ backend (:8000)  │        │   Redis (기존 인프라,   │        │ ingest-worker (신규 컨테이너,  │
│                  │        │   REDIS_URL 이미 배포   │        │   N개까지 수평 확장 가능)      │
│ POST /documents/  │───enqueue─▶│   설정에 존재)          │───pull───▶│                              │
│ .../upload        │  즉시 202  │                       │        │  asyncio.Semaphore(N)로        │
│                  │  응답     │  - 대기 큐 (list/stream) │        │  동시성 제한 후                │
│                  │        │  - job:{id} 해시         │        │  ingest_pipeline.process() 실행│
│ GET /jobs/{id}    │───조회───▶│  - 사용자별 실행 카운트   │◀──갱신──│                              │
│  (큐 위치/ETA 포함) │        │  - 상태 인덱스           │        │  단계마다 progress/stage를      │
└──────────────────┘        └───────────────────────┘        │  job:{id} 해시에 기록 +         │
          ▲                                                    │  callback_url로 POST           │
          │ callback (progress/failed 포함)                      └─────────────────────────────┘
          │
   ingest_callback() → Mongo Document 갱신 (progress/stage/error 필드 포함)
          │
          ▼
   manager.broadcast(...)  (§4.0에서 채널 키 불일치 수정)
          │
          ▼
   frontend: 진행바 컴포넌트 + 전역 토스트
```

핵심 변화는 두 가지다.

1. **enqueue와 실행의 분리**: `POST /api/ingest`는 Redis에 작업을 등록하고 즉시 202(job_id, status=queued)를 반환한다. 실제 파이프라인 실행은 별도 프로세스(별도 컨테이너)의 워커가 담당한다 — API 프로세스의 이벤트루프는 등록 이상의 무거운 작업을 절대 하지 않는다.
2. **워커의 수평 확장 가능성**: 워커는 상태를 갖지 않고(작업 상태는 전부 Redis에 있음) 같은 Redis 큐를 공유하므로, 컨테이너를 N개로 늘리기만 해도 처리량이 늘어난다(오토스케일러 연동은 §1의 비목표대로 이번 범위 밖).

삭제(`delete_document`) 흐름도 동일 인프라를 재사용한다 — 현재는 backend 프로세스 안에서 동기 대기하지만(§1.2.2), Phase B에서 삭제도 워커 큐로 옮겨 진행률을 방출한다(§5.6).

---

## 3. Phase D: 큐·워커 설계

가장 상세히 다뤄야 하는 부분이다. 현재 아무 큐도 없는 상태에서 시작하므로, 자료구조부터 배포까지 전 과정을 규정한다.

### 3.1 Redis 자료구조

| 키 패턴 | 타입 | 용도 |
|---|---|---|
| `ragaas:ingest:queue` | List (`LPUSH`/`BRPOP`) | 대기 중인 job_id의 FIFO 큐. 워커가 `BRPOP`으로 블로킹 pull. |
| `ragaas:ingest:job:{job_id}` | Hash | 작업 상태 전체. 필드: `user_id, kb_id, doc_id, priority, status, progress, stage, created_at, updated_at, started_at, error, worker_id, heartbeat_at`. 상세 스키마는 §8.1. |
| `ragaas:ingest:user:{user_id}:running` | String (INCR/DECR 카운터) | 사용자별 현재 실행 중인 작업 수. 공정성 상한 체크에 사용. |
| `ragaas:ingest:status:{status}` | Set (job_id 목록) | 상태별 인덱스(`pending`/`processing`/`completed`/`failed`). `list_jobs` API가 `jobs` dict 전수 스캔 대신 이 인덱스를 사용. |
| `ragaas:ingest:kb:{kb_id}:jobs` | Set (job_id 목록) | KB별 작업 인덱스 — `GET /jobs?kb_id=...` 조회용. |
| `ragaas:ingest:stats:avg_duration_ms` | String | 최근 완료 작업들의 이동평균 소요시간(ETA 계산용, §3.4). |

Redis 사용은 재시작 시 상태가 살아남는다는 게 핵심 이점이다 — 현재 `jobs` dict(ingest.py 26행)는 프로세스 재시작 시 전부 사라지므로, 재시작 중이던 작업의 상태를 영영 알 수 없다. Redis 자체도 영속성(AOF/RDB) 설정이 필요하다(**구현 시 확인**: 현재 shared-infra Redis 인스턴스의 영속성 설정).

### 3.2 async 워커 설계

워커는 `ingest_service`와 같은 코드베이스(같은 `app/core/pipeline.py`, `app/core/milvus_connector.py` 등)를 공유하는 별도 진입점(`app/workers/ingest_worker.py`, 신규)으로 둔다. 현재 `app/workers/__init__.py`만 있는 빈 디렉터리를 이 신규 모듈로 채운다.

```
동작 개요:

async def run_worker(concurrency: int = WORKER_CONCURRENCY):
    sem = asyncio.Semaphore(concurrency)

    async def handle_one(job_id: str):
        async with sem:
            await process_ingest_job_from_queue(job_id)  # 기존 process_ingest_job을 Redis 기반으로 재작성

    while not shutdown_requested:
        job_id = await redis.brpop("ragaas:ingest:queue", timeout=5)
        if job_id:
            asyncio.create_task(handle_one(job_id))
```

- **동시성 N**: `WORKER_CONCURRENCY` 환경변수(기본값은 보수적으로 2~3). 병목은 CPU가 아니라 임베딩/LLM 호출의 외부 레이트리밋이므로, N을 크게 잡아도 스루풋이 선형으로 늘지 않는다 — 초기값은 낮게 잡고 운영 관찰 후 조정한다(**구현 시 확인**: 실제 임베딩/LLM 프로바이더의 RPM 한도).
- **graceful shutdown**: `SIGTERM` 수신 시 새 `BRPOP`을 멈추고, 진행 중인 `handle_one` 태스크들이 끝날 때까지(또는 타임아웃까지) 대기한 뒤 종료한다. Docker Compose의 기본 `stop_grace_period`를 이 타임아웃보다 길게 설정해야 한다(**구현 시 확인**: 최대 작업 소요시간 기준으로 값 산정).
- **워커 크래시 시 재큐**: 각 워커는 처리 시작 시 `job:{id}` 해시에 `worker_id`와 `heartbeat_at`을 기록하고, 처리 중 주기적으로(예: 30초) `heartbeat_at`을 갱신한다. 별도의 경량 reaper 루틴(워커 자신 또는 API 프로세스의 백그라운드 태스크)이 `status=processing`이면서 `heartbeat_at`이 임계치(예: 3분)를 초과한 작업을 찾아 `ragaas:ingest:queue`에 재푸시하고 `status=pending`으로 되돌린다 — RQ의 job timeout / visibility timeout 개념을 자체 구현하는 것과 같다. 재큐 횟수 상한(예: 3회)을 두고, 초과 시 `status=failed`로 확정해 무한 재시도를 막는다.

### 3.3 공정성 및 백프레셔

- **사용자별 동시 실행 상한**: enqueue 시점에 `ragaas:ingest:user:{user_id}:running`을 확인해 설정값(`MAX_CONCURRENT_JOBS_PER_USER`, 기본 예: 2)을 넘으면 새 작업은 큐에는 들어가되 `status=pending`으로 대기하고, 워커가 pull할 때 상한을 다시 확인해 초과 시 큐 뒤로 되돌린다(또는 별도의 사용자별 대기 큐를 두고 라운드로빈으로 pull). 어느 구현을 택하든 "한 사용자가 큐를 독점해 다른 사용자 작업이 무한정 밀리지 않는 것"이 목표다. **구현 시 확인**: 단일 List 큐 + 재큐 방식과, 사용자별 sub-queue + 라운드로빈 방식 중 운영 복잡도 대비 효과를 비교해 선택.
- **백프레셔**: `ragaas:ingest:queue`의 길이가 설정값(`MAX_QUEUE_DEPTH`)을 초과하면 `POST /api/ingest`가 신규 요청을 429로 거부하거나, 경고 메시지와 함께 수락은 하되 프론트에 "현재 대기가 많습니다"를 노출한다(**구현 시 확인**: 거부 vs 경고-후-수락 중 UX 결정).
- **user_id 전달**: §1.2.6에서 확인했듯 현재 backend→ingest_service 경로에는 `user_id`가 없다. `ingest_client.py`의 `create_ingest_job`과 `ingest_service`의 `IngestRequest`에 `user_id: Optional[str] = None` 필드를 추가하고, backend는 `platform_auth.get_user_id(request)`로 얻은 값을 채워 넘긴다.

### 3.4 큐 가시성 (대기 위치·ETA)

- enqueue 시 `ragaas:ingest:queue`에서의 순번을 근사치로 계산해 `job:{id}` 해시의 `queue_position` 필드에 기록한다(리스트 전체를 스캔하는 대신, enqueue 시점의 큐 길이를 스냅샷으로 저장 — 완벽한 실시간 값은 아니지만 근사로 충분하다. **구현 시 확인**: Redis Stream으로 바꾸면 consumer group 기반으로 더 정확한 위치 추적이 가능하나 구현 복잡도가 늘어남 — 최초 구현은 List로 충분).
- ETA는 `queue_position * avg_duration_ms`(§3.1의 `ragaas:ingest:stats:avg_duration_ms`, 완료된 작업들의 이동평균)로 근사한다.
- `GET /jobs/{job_id}` 응답에 `queue_position`, `estimated_wait_seconds`를 추가하고, WS 메시지 타입 `queue_position_update`로도 갱신을 방출한다(§8.3).

### 3.5 취소

기존 `cancel_job`(ingest.py 415-442행)은 인메모리 `jobs` dict의 `status`를 `CANCELLED`로 바꾸는 것뿐이며, 실행 중인 파이프라인이 실제로 중단되는지는 `process_ingest_job` 안에서 산발적으로 `jobs[job_id]["status"] == JobStatus.CANCELLED`를 체크하는 지점(237·249행)에 의존한다. Redis 전환 후:

- **대기 중(큐에만 있고 아직 워커가 안 집은 경우)**: `job:{id}.status`를 `cancelled`로 바꾸고 큐에서 해당 항목을 제거(List라면 `LREM`, 또는 pull 시점에 상태를 재확인해 스킵)한다 — 즉시 취소되며 워커 자원을 전혀 소모하지 않는다.
- **실행 중**: 기존 방식대로 `job:{id}.status = cancelling`으로 신호를 남기고, 파이프라인 내부의 체크포인트(청킹 후, 임베딩 후, 추출 후 — Phase B에서 추가할 progress 방출 지점과 동일한 위치)에서 이를 확인해 조기 종료한다. 완전한 즉시 취소(현재 실행 중인 LLM 호출 자체를 강제 중단)는 범위 밖으로 둔다(**구현 시 확인**: `asyncio.Task.cancel()`을 워커 태스크 단위로 걸어 강제 취소하는 것도 가능하나, 부분 저장 상태 정리가 함께 필요해 Phase C의 보상 트랜잭션(§6.10)과 연계해야 함).

### 3.6 배포

`deploy/docker-compose.yml`에 신규 서비스 `ingest-worker`를 추가한다.

```yaml
  ingest-worker:
    container_name: ragaas-ingest-worker
    build:
      context: ..
      dockerfile: deploy/images/ingest/Dockerfile   # 기존 ingest-service와 동일 이미지 재사용
    image: ragaas/ingest:latest
    restart: unless-stopped
    command: ["python", "-m", "app.workers.ingest_worker"]   # 신규 진입점
    environment:
      - PYTHONUNBUFFERED=1
      - REDIS_URL=${REDIS_URL:?required}          # 기존 ingest-service와 동일 변수, 이미 필수로 선언돼 있음
      - WORKER_CONCURRENCY=${INGEST_WORKER_CONCURRENCY:-2}
      - MAX_CONCURRENT_JOBS_PER_USER=${MAX_CONCURRENT_JOBS_PER_USER:-2}
      - MILVUS_HOST=${MILVUS_HOST:?required}
      - MILVUS_PORT=${MILVUS_PORT:?required}
      - NEO4J_URI=${NEO4J_URI:?required}
      - NEO4J_USER=${NEO4J_USER:?required}
      - NEO4J_PASSWORD=${NEO4J_PASSWORD:?required}
      - FUSEKI_URL=${FUSEKI_URL:?required}
      - SHARED_STORAGE_PATH=/data/uploads
      - MAIN_BACKEND_URL=http://backend:8000
      - ENCRYPTION_KEY=${ENCRYPTION_KEY:-}
    volumes:
      - ../data/uploads:/data/uploads
    networks: [default, shared-net]
    depends_on:
      - ingest-service
```

`ingest-service`(API, `:8001`)는 그대로 남아 `/api/ingest`, `/api/jobs/{id}`, `/api/preview` 등 HTTP 엔드포인트를 서빙하되, 무거운 파이프라인 실행 코드는 더 이상 이 프로세스 안에서 돌지 않는다 — enqueue만 하고 즉시 응답한다. `ingest-worker`는 동일 이미지를 다른 커맨드로 띄우는 것이므로 별도 Dockerfile이 필요 없다(`deploy/images/ingest/Dockerfile` 재사용). 워커를 여러 개로 늘리려면 `docker compose up --scale ingest-worker=3` 또는 서비스 정의를 복제하면 된다 — 같은 Redis 큐를 공유하므로 별도 조정 로직이 필요 없다.

### 3.7 마이그레이션 경로

1. `ingest_service/app/api/ingest.py`의 `create_ingest_job`을 `BackgroundTasks.add_task(...)` 대신 Redis enqueue(`job:{id}` 해시 생성 + `LPUSH ragaas:ingest:queue {job_id}`)로 교체하고, 즉시 `202 Accepted` + `{job_id, status: "queued"}`를 반환한다.
2. `process_ingest_job` 함수 본체는 그대로 재사용하되(로직 변경 최소화), 입력을 `IngestRequest` 객체 대신 `job:{id}` 해시에서 역직렬화한 값으로 받도록 어댑터 함수를 추가한다.
3. `jobs` dict를 참조하던 `get_job_status`/`cancel_job`/`list_jobs` 엔드포인트를 Redis 조회로 교체한다. 응답 스키마(`JobStatusResponse`)는 하위 호환을 유지하되 `queue_position`, `stage` 필드를 추가한다.
4. **하위 호환**: 마이그레이션 기간 동안 두 실행 경로(BackgroundTasks 직접 실행 vs Redis 큐)를 환경변수(`INGEST_USE_QUEUE=true/false`)로 전환 가능하게 남겨, 워커 컨테이너 배포 전에도 기존 방식으로 폴백할 수 있게 한다. 안정화 후 플래그와 구 경로를 제거한다.
5. **롤백**: 워커 컨테이너에 장애가 생기면 `INGEST_USE_QUEUE=false`로 되돌려 API 프로세스가 다시 직접 처리하도록 즉시 전환할 수 있어야 한다 — 이 폴백 경로가 살아있는 동안은 기존 `jobs` dict 코드를 삭제하지 않는다.

---

## 4. Phase A: Quick Wins

가장 먼저, 가장 적은 리스크로 배포 가능한 항목들이다. 큐/워커 전환(Phase D) 이전에도 독립적으로 적용 가능하다.

### 4.0 (신규 발견, 최우선) WS 브로드캐스트 채널 키 통일

§1.2.4에서 확인한 버그. `manager.connect`가 `kb_{kb_id}`로 등록하는 것에 맞춰, 모든 `manager.broadcast(kb_id, ...)` 호출부를 `manager.broadcast(f"kb_{kb_id}", ...)`로 통일하거나, 반대로 `websocket_endpoint.py`의 접두어 부여를 제거해 양쪽을 원본 `kb_id`로 맞춘다(어느 쪽이든 상관없지만 접두어 제거 쪽이 변경 지점이 1곳(`websocket_endpoint.py`)뿐이라 더 안전하다). **이 수정이 선행되지 않으면 이후 Phase A/B에서 추가하는 progress/에러 payload는 전부 백엔드 로그에만 남고 프론트에는 도달하지 않는다.**

### 4.1 실패 콜백 전송

`ingest_service`의 `process_ingest_job`(153-370행) `except` 블록(364-370행)과 `_save_preview_data`(765-863행) `except` 블록(857-863행)에 `await send_pipeline_status(request.callback_url, job_id, doc_id, kb_id, "FAILED")` 및 별도의 실패 전용 콜백(`status="failed", error=...`)을 추가한다. `send_pipeline_status` 함수 시그니처(133행)에 `error: Optional[str] = None` 파라미터를 추가해 페이로드에 실어 보낸다.

### 4.2 숫자 progress를 콜백/WS 페이로드에 포함

`send_pipeline_status`(133-150행)의 POST 바디에 `progress: int` 필드를 추가한다. 호출부마다 현재 `jobs[job_id]["progress"]` 값(187/248/282/309행에서 갱신되는 값)을 함께 넘긴다. backend `IngestCallback` 모델(650-657행)에 `progress: Optional[int] = None`을 추가하고, `ingest_callback`(659행~)이 이를 `Document.progress` 필드(신규, §8.2)에 저장 후 WS 페이로드(704-712행)에도 포함한다.

### 4.3 오류 상세 노출

- `ingest_service`: `jobs[job_id]["error"]`(369행, `_format_model_error_message`로 가공된 문자열)를 4.1의 실패 콜백 `error` 필드로 전달.
- backend: `Document` 모델(`backend/app/models/document.py`)에 `error: Optional[str] = None` 필드를 추가하고, `ingest_callback`의 `status == "failed"` 분기(693-694행)에서 `doc.error = payload.error`를 채운다. WS 페이로드에도 `error` 필드를 포함.
- frontend: `DocumentsTab.tsx`가 `error` 필드를 받아 배지에 툴팁 또는 확장 패널로 노출(Phase B의 토스트와 별개로, 목록에서도 바로 보이게).

### 4.4 stuck 상태 리커버리

두 가지 방식을 병행한다.

1. **조회 시 타임아웃 판정(경량, 우선 적용)**: `GET /jobs/{id}`, `GET /documents` 등 조회 API가 응답을 만들 때 `status in (processing, deleting)`이고 `updated_at`이 임계치(예: 10분, 삭제는 5분)를 초과했으면 응답에 `stale: true` 플래그를 얹어 프론트가 "응답 없음, 재시도 필요" 같은 경고를 보여줄 수 있게 한다. 상태 자체는 바꾸지 않는 읽기 전용 판정이라 리스크가 낮다.
2. **reaper(능동 복구, Phase D와 함께)**: §3.2의 heartbeat 기반 재큐 로직이 인제스트 쪽의 근본 해법이다. 삭제(`cleanup_service`)에도 동일한 개념을 적용해, `deleting` 상태가 임계치를 초과하면 관리자 알림 또는 자동 재시도(§6.11과 연계)를 수행한다.

---

## 5. Phase B: 진행률·알림 UI

### 5.1 파이프라인 단계별 progress 방출

`ingest_service/app/core/pipeline.py`의 `process()`(801행~)에서 현재 `status_callback`이 호출되는 지점은 그래프 추출 구간뿐이다(857-858/871-872/907-908/922-923행). 청킹과 임베딩 단계에는 호출이 없다. 다음과 같이 가중치를 배분해 침묵 구간을 없앤다.

| 단계 | 기존 상태 문자열 | 제안 progress 구간 |
|---|---|---|
| 파일 읽기 + subject restoration | (ingest.py 레벨, `jobs[job_id]["progress"]=10`) | 0-10 |
| 청킹 | 없음 → 신규 추가 | 10-30 |
| 임베딩 | 없음 → 신규 추가 | 30-60 |
| 엔티티/트리플 추출 (`EXTRACTING_ENTITIES`~`TRIPLE_EXTRACTED`) | 기존 텍스트만 | 60-85 |
| Milvus/그래프 저장 (`STORING`) | 기존 (ingest.py `=80`,`=90`) | 85-100 |

`status_callback`의 시그니처를 `status_callback(stage: str, progress: int)`로 확장하고, 청킹/임베딩 구간 진입·종료 시점에 신규 호출을 추가한다(**구현 시 확인**: 청킹은 보통 매우 빠르므로 단일 시작/종료 콜백으로 충분하지만, 임베딩은 배치 단위로 진행되므로 배치 루프 내부에서 `(완료 배치 수/전체 배치 수)`를 이용한 세밀한 진행률 방출이 가능한지 임베딩 서비스 구현을 확인). `ingest.py`의 `pipeline_callback`(209-210행)이 이 확장된 시그니처를 받아 `send_pipeline_status`에 `progress`를 실어 보낸다(§4.2와 연동).

### 5.2 삭제 진행률

`cleanup_service.py`의 `perform_cascading_deletion` 7단계 각각(Milvus 청크 조회, Fuseki 삭제, Neo4j 삭제, Milvus 삭제, 파일 정리, 검증, Mongo 레코드 삭제) 끝에 `manager.broadcast`(§4.0 수정 반영된 버전) 호출을 추가해 `{type: "delete_progress", doc_id, stage, progress}`를 방출한다. 대략적 가중치는 그래프 삭제 40%, 벡터 삭제 30%, 파일 정리 10%, 검증 10%, 레코드 삭제 10% 정도로 배분한다(**구현 시 확인**: 실제 소요시간 비율 관찰 후 조정).

또한 `delete_document`(document.py 605-648행)가 현재 `await cleanup_service.perform_cascading_deletion(...)`을 동기 대기(617행)하는 구조를, Phase D의 워커 큐로 옮겨 삭제도 인제스트와 동일한 job 추적 체계(`job:{id}`, `GET /jobs/{id}`)를 공유하게 한다 — 삭제 전용 큐를 분리할지, 같은 큐에 `job_type: "delete"` 필드로 구분해 넣을지는 **구현 시 확인**(운영 단순성 면에서는 같은 큐 공유가 유리하나, 삭제가 인제스트 뒤에 밀려 오래 대기하는 상황을 피하려면 우선순위 필드(§8.1의 `priority`)로 삭제를 우대하는 편이 나을 수 있음).

### 5.3 프론트 진행바 컴포넌트 + 전역 토스트

- **진행바**: `DocumentsTab.tsx`의 `getStatusBadge`(112-148행)를 확장하거나 별도 컴포넌트(`ProgressBar.tsx`, 신규)로 분리해, `document.progress`(§8.2 신규 필드)가 있으면 텍스트 배지 대신 퍼센트 바를 렌더링한다. WS 메시지(`document_status_update`, §8.3)에 `progress` 필드가 오면 로컬 상태를 갱신.
- **전역 토스트**: 외부 라이브러리 설치 없이 경량 자체 구현으로 충분하다(§1.2.3에서 확인했듯 현재 토스트 라이브러리가 전혀 없으므로 신규 의존성보다 작은 컨텍스트+컴포넌트가 적합). `ToastContext`(React Context, 신규) + `ToastContainer`(fixed 위치 렌더러, 신규)로 성공/실패 토스트를 큐잉해 순차 표시한다. `useWebSocket` 훅(현재 `frontend/src/hooks/useWebSocket.ts`, 재연결 5회·2000ms 고정 — 33·79-83행)이 수신한 `completed`/`failed`/`deleted` 타입 메시지를 토스트 큐에 넣도록 `onMessage` 콜백을 확장한다. `alert()` 호출부(예: DocumentsTab.tsx 102·106행)는 이 토스트로 교체한다.
- **KnowledgeBaseDetail.tsx의 자체 WS 연결**(146-156행)과 `useWebSocket.ts`가 각자 별도로 WS를 여는 현재 구조는 유지하되(리팩터링은 범위 밖), 두 곳 모두 동일한 `ToastContext`를 구독하게 해 알림 표시 로직은 하나로 모은다.

---

## 6. Phase C: 무결성

### 6.8 chunk_id 정합 근본 수정 (최우선, Phase A와 함께 조기 착수)

`ingest.py` `_save_preview_data`의 788행:

```python
chunks_data = [{"content": node.get_content(), "metadata": node.metadata} for node in cached["nodes"]]
```

을 직접 경로(267-271행)와 동일하게 수정한다:

```python
chunks_data = [{
    "content": node.get_content(),
    "metadata": node.metadata,
    "node_id": node.node_id
} for node in cached["nodes"]]
```

`cached["nodes"]`가 `preview_cache`에서 오든(정상 경로) `temp_storage`에서 복구되든(729-728행의 크래시 복구 경로, `TextNode(..., id_=c.get("node_id") or c.get("id"), ...)` — 689-693행에서 이미 `node_id`를 `id_`로 복원하고 있으므로 `node.node_id`는 두 경로 모두에서 값이 존재한다) 동일하게 동작한다. 이 한 줄 수정만으로 Confirm 경로의 `chunk_id` 불일치가 해소된다.

**이미 저장된 기존 데이터**(수정 이전에 Confirm 경로로 인제스트된 문서)는 이 수정으로 소급 복구되지 않는다 — 별도의 데이터 마이그레이션(Milvus `chunk_id`를 그래프 `source_node_id` 기준으로 재계산해 갱신하거나, 해당 문서를 재인제스트)이 필요하다(**구현 시 확인**: 현재 배포 환경에 Confirm 경로로 저장된 문서가 실제로 존재하는지, 존재한다면 재인제스트가 현실적인 규모인지 확인).

### 6.9 인제스트 후 검증

저장 완료 직후(§5.1의 85-100% 구간 끝) 다음 두 검증을 수행한다.

1. **벡터 수 == 청크 수**: `milvus_connector.insert_chunks`가 반환하는 삽입 개수(101행 `return len(chunks)`)와 `result["node_count"]`를 비교.
2. **reification `chunk_id` ⊆ Milvus `chunk_id`**: 그래프에 기록된 트리플의 `source_node_id` 집합이 Milvus에 실제 존재하는 `chunk_id` 집합의 부분집합인지 확인. 6.8의 수정이 선행되지 않으면 이 검증이 상시 실패하므로 순서상 6.8이 먼저다.

불일치 시 `Document.integrity_warning: bool`(신규 필드, §8.2)을 `true`로 설정하고, WS/토스트로 경고를 노출한다(자동 삭제나 차단은 하지 않는다 — 사용자가 인지하고 재시도/삭제를 선택하게 함). **구현 시 확인**: 검증 비용(Milvus 전체 조회)이 큰 문서에서 과도한 지연을 일으키지 않는지 — 필요시 샘플링 검증으로 완화.

### 6.10 부분 실패 자동 정리 (보상 트랜잭션)

인제스트가 `FAILED`로 확정되는 시점(§4.1의 실패 콜백 전송과 같은 타이밍)에 `cleanup_service.perform_cascading_deletion(kb_id, doc_id)`를 자동 호출해, 부분적으로 저장된 Milvus 벡터/그래프 트리플을 정리한다 — 지금은 실패해도 이미 저장된 부분이 orphan으로 남는다(§1.2.5). 단, 이미 `COMPLETED`였던 문서에 대해 잘못 호출되지 않도록 `Document.status`가 아직 `processing`인 경우에만 트리거하는 가드가 필요하다.

### 6.11 삭제 검증 결과 활용

`_verify_cleanup`(cleanup_service.py 370-417행)이 현재는 실패해도 로그만 남기고 넘어간다(299행 주석 처리된 `raise`). 이를 되살리되, 무조건 삭제를 막는 대신:

- 잔여 데이터가 있으면 **1회 자동 재시도**(해당 백엔드에 대해서만 삭제 쿼리 재실행).
- 재시도 후에도 잔여가 있으면 `Document.status`를 `ERROR`로 유지하되(레코드는 지우지 않음) `integrity_warning`과 구체적 잔여 위치(`garbage_info`, 이미 `_verify_cleanup`이 반환하는 값)를 저장해 사용자가 재시도 버튼을 누를 수 있게 한다.
- 완전 삭제(`raise RuntimeError`로 즉시 차단)는 채택하지 않는다 — 사용자 입장에서 "삭제가 영원히 안 되는" 상황을 만들 수 있어, 경고 후 진행이 현재 설계(299행 주석의 의도)와도 일치한다. 다만 지금처럼 **무조건 침묵 진행**이 아니라 **경고를 눈에 보이게 표면화**하는 것이 이번 변경의 핵심이다.

### 6.12 orphan 스윕 잡 (선택)

주기적으로(예: 매일 1회) Milvus 각 KB 컬렉션의 `doc_id` 집합과 Mongo `Document` 컬렉션의 `doc_id` 집합을 대조해, Mongo에 없는데 Milvus/그래프에 남아있는 데이터를 찾아 정리하는 배치 잡. 6.10(즉시 보상 트랜잭션)이 대부분의 케이스를 커버하므로 이건 안전망 성격의 선택 항목이다. **구현 시 확인**: 실행 주기, 대상 KB 범위(전체 스캔 비용), 실행 위치(워커 컨테이너의 cron 태스크 또는 별도 배치).

---

## 7. 알림 시스템 통합

세 종류의 이벤트가 하나의 채널·컴포넌트로 수렴해야 한다.

- **WS 실시간 이벤트**: `progress_update`(인제스트 단계 진행), `delete_progress`(삭제 단계 진행), `queue_position_update`(대기 순번 변경), `completed`(성공 확정), `failed`(실패 확정 + error 메시지), `deleted`(삭제 확정). 전부 §4.0에서 수정된 동일 채널(`kb_{kb_id}` 또는 통일된 키)로 전달되며, backend `ingest_callback`(및 신규 delete-progress 콜백 처리부)이 유일한 발신 지점이다.
- **프론트 토스트**: §5.3의 `ToastContext`가 `completed`/`failed`/`deleted` 타입만 토스트로 승격한다(progress성 이벤트는 진행바로만 표시, 토스트로 매번 띄우면 스팸이 됨).
- **선택적 브라우저 Notification API**: 사용자가 탭을 벗어나 있을 때(문서 `visibilitychange`가 `hidden`)만 `new Notification(...)`을 추가로 띄운다(권한 요청 UX 포함). 이번 설계에서는 훅만 마련하고(`ToastContext`에 `notifyIfHidden` 옵션) 실제 브라우저 권한 요청 플로우 구현은 후속 과제로 남긴다(**구현 시 확인**: 권한 요청 타이밍—즉시 vs 사용자 행동 후—을 UX 팀과 조율).
- **큐 완료 알림과 인제스트/삭제 알림의 공유**: Phase D의 큐 위치 갱신(`queue_position_update`)도 같은 WS 채널·같은 `ToastContext`를 사용하므로, "3번째 대기 중 → 실행 시작 → 60% 진행 → 완료" 전체 흐름이 하나의 진행바 컴포넌트 상태 전이로 자연스럽게 이어진다.

---

## 8. 데이터 모델

### 8.1 Redis `job:{id}` 해시 스키마

| 필드 | 타입 | 설명 |
|---|---|---|
| `job_id` | string (UUID) | |
| `job_type` | `"ingest"` \| `"delete"` | §5.2 참고 — 같은 큐 공유 시 구분용 |
| `user_id` | string | `platform_auth`의 `request.state.user_id` (§3.3) |
| `kb_id` | string | |
| `doc_id` | string | |
| `priority` | int (기본 0, 삭제는 높게) | |
| `status` | `queued`\|`processing`\|`completed`\|`failed`\|`cancelled`\|`cancelling` | |
| `progress` | int (0-100) | |
| `stage` | string (예: `CHUNKING`, `EMBEDDING`, `EXTRACTING_TRIPLES`, `STORING`, `VERIFYING`) | |
| `queue_position` | int, nullable | §3.4 |
| `error` | string, nullable | |
| `worker_id` | string, nullable | §3.2 재큐 판정용 |
| `heartbeat_at` | epoch ms, nullable | §3.2 |
| `created_at` / `updated_at` / `started_at` / `completed_at` | epoch ms | |

### 8.2 Mongo `Document` 모델 확장 필드

현재 `backend/app/models/document.py`(15-50행)에 없는 필드들:

| 필드 | 타입 | 용도 |
|---|---|---|
| `progress` | `Optional[int]` | §4.2 |
| `error` | `Optional[str]` | §4.3 |
| `integrity_warning` | `Optional[bool] = False` | §6.9, §6.11 |
| `integrity_detail` | `Optional[str]` | 잔여 위치 등 상세(§6.11 `garbage_info`) |
| `queue_position` | `Optional[int]` | §3.4 (일시적 값, 완료 후 의미 없음) |
| `job_id` | `Optional[str]` | 현재 Redis `job:{id}`와의 연결 키. 문서-작업 매핑을 위해 필요(현재는 `doc_id`로 간접 매핑, `ingest.py` `cancel_job`의 `doc_id` 폴백 탐색(423-427행)과 동일한 필요성) |

### 8.3 WS 메시지 타입

| `type` | 발신 시점 | 주요 필드 |
|---|---|---|
| `document_status_update` | 기존(유지) — 업로드/콜백마다 | `doc_id, status, pipeline_status` + 신규 `progress, error` |
| `progress_update` | 신규 — 파이프라인 단계 전환마다(§5.1) | `doc_id, stage, progress` |
| `delete_progress` | 신규 — 삭제 단계 전환마다(§5.2) | `doc_id, stage, progress` |
| `queue_position_update` | 신규 — 큐 위치 변동마다(§3.4) | `job_id, doc_id, queue_position, estimated_wait_seconds` |
| `completed` | 신규 — 최종 성공 확정 | `doc_id, result` |
| `failed` | 신규 — 최종 실패 확정 | `doc_id, error` |
| `deleted` | 기존(`cleanup_service.py` 343-347행, 채널 버그 수정 후 실질적으로 도달) | `doc_id` |

---

## 9. 변경 파일 목록

| 파일 | 변경 유형 | 변경 내용 요약 |
|---|---|---|
| `backend/app/api/websocket_endpoint.py` | 수정 | `channel_id` 접두어 제거(또는 반대쪽 통일) — §4.0 |
| `backend/app/core/websocket_manager.py` | 수정(선택) | 필요 시 채널명 정규화 헬퍼 추가 |
| `backend/app/api/document.py` | 수정 | `IngestCallback`에 `progress` 추가, 실패 분기에서 `doc.error` 저장(§4.1-4.3), `delete_document`를 큐 기반으로 전환(§5.2), 브로드캐스트 payload 확장 |
| `backend/app/models/document.py` | 수정 | `progress`, `error`, `integrity_warning`, `integrity_detail`, `queue_position`, `job_id` 필드 추가(§8.2) |
| `backend/app/services/ingestion/cleanup_service.py` | 수정 | 단계별 WS 브로드캐스트(§5.2), `_verify_cleanup` 실패 시 재시도+플래그(§6.11), `FAILED` 인제스트에 대한 자동 보상 트랜잭션 훅(§6.10) |
| `backend/app/services/ingestion/ingest_client.py` | 수정 | `user_id` 파라미터 추가(§3.3) |
| `backend/app/core/platform_auth.py` | 참조만(변경 없음) | `get_user_id`를 document.py에서 호출해 ingest_client로 전달 |
| `ingest_service/app/api/ingest.py` | 수정 | `send_pipeline_status`에 `progress`/`error` 추가(§4.1-4.2), `_save_preview_data` 788행 `node_id` 포함(§6.8), Redis enqueue로 전환(§3.7), `IngestRequest`에 `user_id` 추가 |
| `ingest_service/app/core/pipeline.py` | 수정 | 청킹/임베딩 구간 `status_callback` 호출 추가, `status_callback` 시그니처에 `progress` 추가(§5.1) |
| `ingest_service/app/core/milvus_connector.py` | 변경 없음(참조) | `insert_chunks`의 `node_id` 폴백 로직(80-87행)은 그대로 — 상위 호출부가 항상 `node_id`를 넘기도록 고치는 것이 올바른 수정 방향 |
| `ingest_service/app/workers/ingest_worker.py` | 신규 | async 워커 진입점(§3.2) |
| `ingest_service/app/core/redis_queue.py` | 신규 | Redis 큐/job 해시 CRUD 헬퍼(enqueue, dequeue, update_progress, heartbeat, reap) |
| `ingest_service/app/core/config.py` | 수정 | `WORKER_CONCURRENCY`, `MAX_CONCURRENT_JOBS_PER_USER`, `MAX_QUEUE_DEPTH` 등 설정 추가 |
| `frontend/src/components/DocumentsTab.tsx` | 수정 | `getStatusBadge` → 진행바 렌더링으로 확장(§5.3), `alert()` → 토스트 교체 |
| `frontend/src/components/ProgressBar.tsx` | 신규 | 퍼센트 진행바 컴포넌트 |
| `frontend/src/contexts/ToastContext.tsx` | 신규 | 전역 토스트 컨텍스트(§5.3, §7) |
| `frontend/src/components/ToastContainer.tsx` | 신규 | 토스트 렌더러 |
| `frontend/src/hooks/useWebSocket.ts` | 수정 | 신규 메시지 타입(`progress_update`/`delete_progress`/`queue_position_update`/`completed`/`failed`) 처리, `ToastContext` 연동 |
| `frontend/src/pages/KnowledgeBaseDetail.tsx` | 수정 | 자체 WS 메시지 핸들러도 동일 `ToastContext` 구독 |
| `deploy/docker-compose.yml` | 수정 | `ingest-worker` 서비스 추가(§3.6) |

---

## 10. 롤아웃·롤백·테스트 계획

### 10.1 단계별 배포

1. **1단계 (§4.0 + §6.8)**: WS 채널 키 통일, chunk_id 근본 수정. 코드 변경이 각각 몇 줄로 작고 되돌리기 쉬우므로 가장 먼저, 가장 빠르게 배포한다.
2. **2단계 (Phase A 나머지, §4.1-4.4)**: 실패 콜백/progress 필드/오류 노출/stuck 판정. 기존 응답 스키마에 필드를 추가하는 방식이라 하위 호환적이다.
3. **3단계 (Phase D, §3)**: Redis 큐 도입 + `ingest-worker` 컨테이너 배포. `INGEST_USE_QUEUE` 플래그로 즉시 롤백 가능한 상태를 유지한 채 카나리로 전환.
4. **4단계 (Phase B, §5)**: 파이프라인 세분화 progress, 삭제 진행률, 프론트 UI(진행바/토스트). Phase D 위에서 동작하므로 3단계 이후.
5. **5단계 (Phase C 나머지, §6.9-6.12)**: 인제스트 후 검증, 보상 트랜잭션, 삭제 검증 활용, orphan 스윕.

### 10.2 하위 호환

- Redis 미가용 시(장애 또는 초기 배포 누락) `INGEST_USE_QUEUE=false` 폴백으로 API 프로세스가 직접 처리하는 기존 경로가 계속 동작해야 한다(§3.7).
- 신규 WS 메시지 타입을 모르는 구버전 프론트가 붙어 있어도(배포 시차) 무시하고 넘어가게(스키마 미지 필드는 `switch`의 `default` 케이스로 무해하게 처리) 프론트 메시지 핸들러를 방어적으로 작성한다.

### 10.3 테스트 시나리오

- **멀티유저 동시 제출 부하 테스트**: 서로 다른 `user_id`로 동시에 N개(예: 10개) 인제스트 요청을 보내, (a) API 응답이 즉시(202) 오는지, (b) `MAX_CONCURRENT_JOBS_PER_USER` 상한이 지켜지는지, (c) 한 사용자가 몰아서 제출해도 다른 사용자 작업이 무한정 밀리지 않는지 확인.
- **stuck 시나리오**: 워커 프로세스를 처리 도중 강제 종료(`docker kill`)했을 때 (a) heartbeat 기반 reaper가 임계시간 내 재큐하는지, (b) 재큐 상한 초과 시 `failed`로 확정되고 사용자에게 알림이 가는지.
- **실패 시나리오**: 의도적으로 임베딩 모델 설정을 깨뜨려(`_is_model_configured` 검증 실패 유도, ingest.py 170-179행) 실패를 발생시키고, 실패 콜백 → Mongo `error` 필드 → WS `failed` 메시지 → 프론트 토스트까지 전체 체인이 도달하는지 end-to-end 확인.
- **무결성 시나리오**: Confirm(Preview 확정) 경로로 문서를 인제스트한 뒤 6.8 수정 적용 전/후 `chunk_id` 일치 여부를 비교. 6.9의 검증 로직이 의도적으로 깨뜨린 케이스(예: Milvus insert 일부만 성공하도록 mock)에서 `integrity_warning`을 정확히 세우는지 확인.
- **워커 크래시 복구 테스트**: §3.2의 heartbeat/재큐 로직에 대한 단위 테스트 — heartbeat 미갱신 job이 정확히 재큐되는지, 이미 완료된 job이 실수로 재큐되지 않는지(경합 조건 확인).
- **삭제 취소/재시도 테스트**: 삭제 중 `_verify_cleanup` 실패를 mock으로 유도해 자동 재시도 1회 후에도 실패 시 `integrity_warning` + 사용자 재시도 버튼 노출까지 확인(§6.11).

### 10.4 배포 방식

기존 관행에 따라 컨테이너 이미지 재빌드 후 `deploy/docker-compose.yml` 갱신 배포. `ingest-worker`는 신규 서비스이므로 첫 배포 시 `docker compose up -d ingest-worker`로 별도 확인 후 나머지 롤아웃을 진행한다. git 커밋 여부는 이번 설계 문서 작성 범위에 포함하지 않으며, 별도 지시를 기다린다.

---

## 11. 오늘 적용된 수정과의 관계

오늘(구현 착수 이전) 이미 적용된 수정 사항을 이 설계의 Phase 구분에 대응시키면 다음과 같다.

| 오늘 적용된 수정 | 대응 Phase | 비고 |
|---|---|---|
| Milvus 동기 `load`/`query`를 `asyncio.to_thread` + `wait_for`로 격리(5개 경로: retrieval `_fetch_chunks`, document `get_document_chunks`, `graph_viewer`, `cleanup_service` 4곳) | Phase D의 전신(임시 완화) | 이벤트루프 블로킹의 **증상**을 스레드 격리로 완화한 조치. Phase D(워커 프로세스 분리)가 적용되면 무거운 인제스트 자체가 API 프로세스 밖으로 나가므로 이 완화책의 중요도는 낮아지지만, Milvus 클라이언트 호출 자체는 여전히 동기이므로 **워커 프로세스 내부에서도 동일한 스레드 격리 패턴을 유지해야 한다**(워커도 async 루프 위에서 돈다). §3.2, 교훈은 `docs/design-query-generation-loop.md` §9.1의 "외부 I/O 격리 — 시간 격리 필수" 교훈과 동일 계열. |
| `num_entities == 0`이면 조회 스킵 | Phase C의 전신 | 빈/손상 컬렉션에 대한 방어. §6.9의 검증 로직 구현 시 동일한 빈 컬렉션 가드를 재사용해야 한다. |
| WS 복구(이벤트루프 수정의 부작용 해소) | §4.0과는 별개 층위 | 이 수정은 "연결이 유지되는가"를 고쳤을 뿐, §1.2.4/§4.0에서 확인한 "브로드캐스트가 올바른 채널로 가는가"는 별도의 미해결 버그다. 둘 다 고쳐야 WS 알림이 실제로 동작한다. |
| KB 생성 수정(`pipeline_config` 필드) | 범위 밖 | 이 설계와 직접 관련 없음. |
| 인제스트 `embed_model` 버그 수정(`active_embed_model`) | 범위 밖 | 이 설계와 직접 관련 없음. |
| B2 reification SELECT 수정 | §6.8과 연관 | reification 조회 자체는 오늘 고쳐졌으나, §1.2.5/§6.8에서 확인한 **데이터 생성 단계**(Confirm 경로 `chunk_id` 누락)의 근본 원인은 별도이며 오늘 수정으로 해소되지 않는다. §6.8을 Phase A와 함께 조기 착수해야 하는 이유. |

---

*(끝)*
