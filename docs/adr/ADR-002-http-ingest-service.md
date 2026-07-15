# ADR-002: 인제스트를 브로커+워커 대신 HTTP 마이크로서비스로 구현

- **상태**: Accepted (2026-07-15 기록)
- **관련**: docs/arch/architecture.md CA-203(메시지 큐 기반 워커 분산) 설계를 **대체**함

## 맥락

초기 아키텍처(docs/arch/architecture.md §3.1 배치 다이어그램, CA-203)는 인제스트 처리를
"API 서버 -- AMQP/Redis --> Message Broker -- AMQP/Redis --> Ingestion Worker" 구조로
설계했다. 목적은 대량 문서 유입 시에도 API 서버가 차단되지 않도록 부하를 평준화하는 것이었다
(architecture.md 108행, 185행 CA-203 "대량 데이터 유입 시 안정성 보장").

그러나 실제 구현은 이 설계를 따르지 않았다. 대신 backend와 별도의 FastAPI
마이크로서비스(`ingest_service`, LlamaIndex 기반)를 두고, 둘 사이를 **동기 HTTP 호출 +
콜백**으로 연결했다:

- `backend/app/api/document.py` 업로드 엔드포인트가 `BackgroundTasks`로
  `call_ingest_service()`를 등록하고, `ingest_client.create_ingest_job()`
  (`backend/app/services/ingestion/ingest_client.py`)이 `POST {INGEST_SERVICE_URL}/api/ingest`를
  호출한다.
- `ingest_service/app/api/ingest.py`는 요청을 받으면 자체 `BackgroundTasks`로
  `process_ingest_job()`을 실행하고, 잡 상태를 프로세스 내 메모리 딕셔너리
  (`jobs: Dict[str, Dict[str, Any]] = {}`, 주석: "In production, use Redis or a Database")에
  기록한다. 처리 중간·완료 시점마다 `callback_url`(backend의
  `POST /api/knowledge-bases/ingest/callback`)로 상태를 통보한다.
- 문서 상태는 MongoDB `documents` 컬렉션의 `status`/`pipeline_status`로 추적된다
  (UPLOADED → PROCESSING/EXTRACTING_TRIPLES/STORING → COMPLETED/ERROR).
- Redis는 `deploy/docker-compose.yml`에 인프라로 존재하지만(`REDIS_URL`), 인제스트
  브로커로는 사용되지 않는다.
- 원본 파일은 backend·ingest-service 두 컨테이너가 공유 볼륨(`SHARED_STORAGE_PATH=/data/uploads`)을
  통해 `{kb_id}/{doc_id}_{filename}` 경로로 공유한다.
- 배포는 `deploy/docker-compose.yml`에서 `backend`, `ingest-service`를 별도 컨테이너로 기동하며,
  backend는 `INGEST_SERVICE_URL=http://ingest-service:8001`로 통신한다.

## 결정

인제스트 처리 아키텍처를 (설계 문서상 CA-203의) 메시지 브로커+워커 방식이 아니라,
**backend → ingest_service 동기 HTTP 요청 + 비동기 콜백** 방식으로 구현·운영한다.
브로커(AMQP/Redis 큐)는 도입하지 않으며, 잡 상태는 ingest_service 프로세스 메모리와
backend MongoDB 문서 레코드로 이원화하여 관리한다.

## 결과

### 긍정적
- 브로커 인프라(RabbitMQ 등) 없이 두 서비스만으로 배포·운영이 단순하다.
- 서비스 간 계약이 REST API로 명시적이며 디버깅이 쉽다(HTTP 로그, 콜백 payload 확인 가능).
- 프리뷰/컨펌 2단계 인제스트(`/api/preview`, `/api/confirm/{id}`) 같은 요청-응답 UX를
  구현하기 용이하다.

### 부정적
- **잡 내구성 없음**: ingest_service의 잡 상태(`jobs` 딕셔너리)는 프로세스 메모리에만
  존재한다. 재시작·크래시 시 진행 중이던 잡 정보가 완전히 유실되고, 재조회 시
  "Job not found"가 된다.
- **문서 상태 고착 위험**: 인제스트 도중 ingest_service가 중단되면 콜백이 전송되지 않아
  backend MongoDB 문서 `status`가 `PROCESSING`(또는 중간 `pipeline_status`)에 영구히
  머무를 수 있다. 이를 감지·정정하는 워치독/타임아웃이 없다.
- **백프레셔 제한**: 브로커 큐가 없어 대량 문서가 동시 업로드되면 ingest_service의
  `BackgroundTasks`가 무제한 누적되어 동시 처리량을 제어할 수 없다(CA-203이 해결하려던
  문제가 미해결로 남음).
- **재시도 메커니즘 부재**: HTTP 호출 실패나 ingest_service 내부 예외 시 문서 상태를
  `ERROR`로 표시할 뿐, 자동 재시도나 DLQ(dead-letter) 처리가 없어 사용자가 수동
  재업로드해야 한다.
- 프리뷰 복구 로직(`confirm_preview`)은 `preview_cache` 미스 시 디스크 임시 파일에서
  재구성을 시도하지만 프리뷰 단계 한정이며, 일반 인제스트 잡(`/api/ingest`)에는 동일한
  복구 경로가 없다.

## 향후 재검토 조건

다음 조건 중 하나라도 충족되면 메시지 큐(Redis Streams, RabbitMQ 등) 기반 워커 구조 도입을
재평가한다:

- 동시/대량 문서 업로드(예: 배치 임포트, 대규모 마이그레이션)로 ingest_service 메모리
  사용량이나 동시 처리 수가 운영상 문제를 일으킬 때.
- 문서가 `PROCESSING` 상태로 고착되는 사례가 반복적으로 보고될 때.
- ingest_service 재시작(배포, 스케일링, 장애 복구)이 빈번해져 잡 유실이 실질적 비용이 될 때.
- 서비스 간 재시도/지수 백오프/DLQ 등 신뢰성 요건이 명시적으로 요구될 때.

## 참조 파일

- `backend/app/api/document.py` (업로드 엔드포인트, `call_ingest_service`, `ingest_callback`)
- `backend/app/services/ingestion/ingest_client.py` (`IngestServiceClient`, httpx POST)
- `ingest_service/app/api/ingest.py` (`jobs` 인메모리 저장, `process_ingest_job`,
  `send_pipeline_status`, preview/confirm 복구 로직)
- `docs/arch/architecture.md` §3.1 배치 다이어그램, §5 CA-203 결정 항목(대체 대상)
- `deploy/docker-compose.yml` (backend/ingest-service 컨테이너 분리, `SHARED_STORAGE_PATH`,
  `INGEST_SERVICE_URL`, Redis 미사용 확인)
