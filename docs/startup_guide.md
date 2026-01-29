# 서비스 가동 및 트러블슈팅 가이드 (Startup & Troubleshooting Guide)

이 문서는 RAGaaS 시스템의 백엔드, 인제스트 서비스, 프론트엔드를 안정적으로 가동하는 방법과 발생할 수 있는 주요 문제 해결 방법을 기록합니다.

## 1. 서비스 가동 전 필수 체크 (좀비 프로세스 정리)

서버 재시도나 비정상 종료 후 포트가 점유되어 있는 경우 서비스가 시작되지 않습니다. 아래 명령어로 기존 프로세스를 정리합니다.

```bash
# 8000(Back), 8001(Ingest), 5173(Front) 포트 점유 프로세스 종료
lsof -ti :8000,8001,5173 | xargs kill -9 || true
```

## 2. 권장 서비스 시작 순서

모든 서비스는 `0.0.0.0` 호스트로 실행하여 IPv4/IPv6 접속 문제를 방지합니다.

### 1) 인프라 서비스 (Docker)
```bash
docker-compose up -d
```

### 2) 백엔드 (Backend) - Port 8000
```bash
cd backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3) 인제스트 서비스 (Ingest Service) - Port 8001
```bash
cd ingest_service
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 4) 프론트엔드 (Frontend) - Port 5173
```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

## 3. 주요 문제 및 해결 방안

### 문제 1: "Address already in use" 에러 (8000 포트 등)
*   **원인**: 이전 프로세스가 비정상 종료되어 포트를 잡고 있음.
*   **해결**: 상단의 '좀비 프로세스 정리' 명령어를 실행한 후 다시 시작.

### 문제 2: 프론트엔드에서 백엔드 접속 실패 (Connection Refused)
*   **원인**: 
    1. 서버가 `127.0.0.1`로만 바인딩되어 있는데 브라우저가 `localhost`를 IPv6(`::1`)로 호출하는 경우.
    2. CORS 설정 문제.
*   **해결**: 
    *   서버 실행 시 `--host 0.0.0.0` 옵션 사용.
    *   브라우저에서 `http://127.0.0.1:5173`으로 직접 접속 시도.

### 문제 3: 문서 처리(Ingestion) 중 에러 또는 무한 대기
*   **원인**: 인제스트 서비스(8001)가 죽어있거나 백엔드와 통신이 안 됨.
*   **해결**: `ingest_service` 로그를 확인하고, `backend/.env` 파일의 `INGEST_SERVICE_URL`이 정확한지 확인.
