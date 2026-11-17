# 서비스 가동 및 트러블슈팅 가이드

> **상태**: ✅ 현행 · **최종 검증**: 2026-11-17 · 플랫폼(MF 셸) 계약은 [`../platform-contract/`](../platform-contract/README.md).
> `deploy/` 의 compose·Dockerfile·nginx 설정은 저장소에 있다. `deploy/.env` 는 비밀값이라 커밋하지 않는다 — `deploy/.env.example` 을 복사해 채운다.
> 구(로컬 인프라 + venv) 방식 가이드는 폐기됨 — 인프라는 이제 **shared-infra**(외부 호스트)를 참조한다.

## 1. 운영 기동 (Docker — 표준)

```bash
cd deploy
# 최초 또는 코드 변경 시
docker compose build            # frontend(MF 빌드) + backend + ingest
docker compose up -d            # shared-net 외부 네트워크 필요 (GoJIRA 스택이 생성)
```

전제:
- `deploy/.env` 존재 (`deploy/.env.example` 참고 — shared-infra 엔드포인트 + **기존 `ENCRYPTION_KEY`**).
- 컨테이너 재생성 후 게이트웨이가 새 IP를 못 잡으면, GoJIRA deploy 에서 `docker compose restart gateway`.

### 기동 검증

```bash
docker compose ps                                   # 3서비스 Up
docker logs ragaas-backend | grep Startup           # "MongoDB Connected", "Milvus Connected" 확인
curl -s http://<gateway-host>:44300/ragaas/api/v2/knowledge-bases/ | head -c 200   # KB 목록 응답 (/api/v2)
```

접속: **`http://<gateway-host>:44300/ragaas`** (셸 경유는 `/` 에서 RAGaaS 타일).

## 2. 개발 모드 (frontend 만 로컬)

```bash
cd frontend && npm install --legacy-peer-deps && npm run dev   # base '/' 로 standalone 동작
```
backend/ingest 는 Docker 를 그대로 쓰고 vite proxy(`/api`, `/ingest-api`)로 연결하거나, 로컬 uvicorn 실행 시 shared-infra env 를 직접 주입한다.

## 3. 주요 문제 및 해결

### 셸에서 "RAGaaS에 연결할 수 없습니다"
- **원인 1 — 오리진 불일치(CORS)**: 셸을 `localhost:44300` 으로 열었는데 `RAGAAS_APP_REMOTE` 가 LAN IP 로 설정된 경우, remoteEntry 교차출처 로드가 차단된다.
  **해결**: remote 와 같은 호스트로 접속 (`http://<gateway-host>:44300`).
- **원인 2**: ragaas 컨테이너가 `shared-net` 미조인 → 게이트웨이 502. `docker network inspect shared-net` 로 확인.

### backend 기동 직후 `Failed to connect to Milvus`
- 인프라 워밍업 전 기동된 경합. Milvus healthy 후 `docker compose restart backend`.
- shared-infra 자체가 죽어 있으면 해당 호스트에서 인프라 스택 확인.

### 문서가 processing 에서 멈춤
- ingest-service 중단 시 콜백 유실로 상태가 고착된다 ([ADR-002](../adr/ADR-002-http-ingest-service.md) 알려진 한계).
  `docker logs ragaas-ingest` 확인 → 필요 시 문서 삭제 후 재업로드.

### API 키 복호화 실패 (`ENCRYPTION_KEY may have changed`)
- `deploy/.env` 의 `ENCRYPTION_KEY` 가 데이터를 암호화했던 값과 다름. **기존 키로 복원** (새로 생성하면 저장된 프로바이더 키 전부 무효).

### 커스텀 LLM(예: z.ai) 401/타임아웃/모델 오류
- [`architecture/model-config-and-pipeline-contract.md`](../architecture/model-config-and-pipeline-contract.md) §4 함정 목록 참조 (api_base, 모델 화이트리스트, coding 플랜 엔드포인트, thinking 모델 주의).

### 배포했는데 프론트가 옛 버전으로 동작
- MF 청크 캐시 문제. JS/CSS 는 no-cache 로 서빙 중이나, 과거 immutable 캐시가 남은 브라우저는 1회 수동 클리어 필요 .

## 4. 빠른 반영과 확인 (2026-11 운영에서 정리)

### 이미지 빌드 없이 코드 반영 (임시)
```bash
docker cp backend/app/<경로>.py ragaas-backend:/app/app/<경로>.py && docker restart ragaas-backend
docker cp ingest_service/app/<경로>.py ragaas-ingest:/app/app/<경로>.py && docker restart ragaas-ingest
```
- 컨테이너를 다시 만들면 사라진다. 머지 후에는 반드시 main 에서 `docker compose build backend frontend ingest-service` + `up -d --no-deps …`.
- 실제 백엔드 진입점은 `backend/main.py` 다 (`app/main.py` 아님 — 라우터는 여기 등록).

### 프론트 빠른 반영
```bash
cd frontend && npm run build
docker cp dist/. ragaas-frontend:/usr/share/nginx/html
docker exec ragaas-frontend sh -c 'chown -R root:root /usr/share/nginx/html && find /usr/share/nginx/html -type d -exec chmod 755 {} + && find /usr/share/nginx/html -type f -exec chmod 644 {} +'
```
- tar 로 풀면 웹 루트 권한이 700 이 되어 **403**. 위 chown/chmod 필수.

### 테스트 (이미지에 pytest 없음)
```bash
docker exec ragaas-backend sh -c 'cd /app && python -m pip install -q pytest pytest-asyncio && python -m pytest -q tests'
docker exec ragaas-ingest  sh -c 'cd /app && python -m pip install -q pytest && python -m pytest -q tests'
```
- 백엔드 `test_noise_filtering` 1건은 기존 실패 (2026-11 기준).

### 경로
- API `/ragaas/api/v2/…` (backend·ingest 둘 다 `/api/v2`). `/ragaas/api/knowledge-bases/` 는 404.
- MCP `/ragaas/api/mcp/` — 게이트웨이 규칙 `/ragaas/api/` → `/api/` 그대로라 별도 설정 불필요.
- backend 는 호스트 8000 을 노출하지 않는다 (GoJIRA `jira-api` 와 충돌).

### LLM (Z.ai GLM)
- 모든 GLM 호출은 사고 모드를 끈다 (`thinking: disabled`) — 빠지면 호출당 30~80초.
- 호스트당 동시 4개 + 429 재시도. 동시 8개면 429. 5시간 사용 한도는 `api.z.ai/api/monitor/usage/quota/limit` 로 확인.
- KB 답변 모델은 `chunking_config.retrieval_llm_*` 가 `llm_model_config` 보다 우선한다.

### 저장소
- Milvus 는 동기 호출이 이벤트 루프를 멈출 수 있다 — 새 코드도 `to_thread` + `wait_for`. 새 컬렉션은 만들지 않는다.
- Milvus 를 초기화하면 재업로드하지 말고 `/data/uploads/<kb>/<doc>_chunks.json` 을 재임베딩해 **같은 node_id** 로 넣는다 (그래프 근거 청크 연결 유지).
