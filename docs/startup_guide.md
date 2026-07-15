# 서비스 가동 및 트러블슈팅 가이드

> **상태**: ✅ 현행 · **최종 검증**: 2026-07-15 · 배포 상세·MF 함정은 [`PLATFORM-INTEGRATION.md`](PLATFORM-INTEGRATION.md) 참조.
> 구(로컬 인프라 + venv) 방식 가이드는 폐기됨 — 인프라는 이제 **shared-infra**(외부 호스트)를 참조한다.

## 1. 운영 기동 (Docker — 표준)

```bash
cd deploy
# 최초 또는 코드 변경 시
docker compose build            # frontend(MF 빌드) + backend + ingest
docker compose up -d            # shared-net 외부 네트워크 필요 (GoJIRA 스택이 생성)
```

전제:
- `deploy/.env` 존재 (shared-infra 엔드포인트 + **기존 `ENCRYPTION_KEY`** — PLATFORM-INTEGRATION §3 템플릿).
- 컨테이너 재생성 후 게이트웨이가 새 IP를 못 잡으면, GoJIRA deploy 에서 `docker compose restart gateway`.

### 기동 검증

```bash
docker compose ps                                   # 3서비스 Up
docker logs ragaas-backend | grep Startup           # "MongoDB Connected", "Milvus Connected" 확인
curl -s http://<gateway-host>:44300/ragaas/api/knowledge-bases/ | head -c 200   # KB 목록 응답
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
- ingest-service 중단 시 콜백 유실로 상태가 고착된다 ([ADR-002](adr/ADR-002-http-ingest-service.md) 알려진 한계).
  `docker logs ragaas-ingest` 확인 → 필요 시 문서 삭제 후 재업로드.

### API 키 복호화 실패 (`ENCRYPTION_KEY may have changed`)
- `deploy/.env` 의 `ENCRYPTION_KEY` 가 데이터를 암호화했던 값과 다름. **기존 키로 복원** (새로 생성하면 저장된 프로바이더 키 전부 무효).

### 커스텀 LLM(예: z.ai) 401/타임아웃/모델 오류
- [`architecture/model-config-and-pipeline-contract.md`](architecture/model-config-and-pipeline-contract.md) §4 함정 목록 참조 (api_base, 모델 화이트리스트, coding 플랜 엔드포인트, thinking 모델 주의).

### 배포했는데 프론트가 옛 버전으로 동작
- MF 청크 캐시 문제. JS/CSS 는 no-cache 로 서빙 중이나, 과거 immutable 캐시가 남은 브라우저는 1회 수동 클리어 필요 (PLATFORM-INTEGRATION §4.2).
