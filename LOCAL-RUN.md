# 로컬 실행 가이드 (Local Run Guide)

이 가이드는 Backend, Ingest Service, Frontend를 로컬 환경에서 실행하는 방법을 설명합니다.

## 📋 사전 준비

### 1. 데이터베이스 서비스 시작 (Docker)

```bash
cd /Users/dukekimm/Works/RAGaaS
docker-compose up -d
```

실행되는 서비스:
- MongoDB (27017)
- Neo4j (7474, 7687)
- Fuseki (3030)
- Milvus (19530)
- Redis (6379)
- Minio (9000, 9001)
- Etcd (2379)

### 2. Python 가상환경 (Backend & Ingest Service)

```bash
# Python 3.11+ 필요
python --version  # 3.11 이상 확인
```

## 🚀 서비스 실행

### 1. Backend 실행

```bash
# Terminal 1
cd /Users/dukekimm/Works/RAGaaS/backend

# 의존성 설치 (처음 한 번만)
pip install -r requirements.txt

# 서버 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**실행 확인**: http://localhost:8000/docs

### 2. Ingest Service 실행

```bash
# Terminal 2
cd /Users/dukekimm/Works/RAGaaS/ingest_service

# 의존성 설치 (처음 한 번만)
pip install -r requirements.txt

# 서버 실행
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

**실행 확인**: http://localhost:8001/health

### 3. Frontend 실행

```bash
# Terminal 3
cd /Users/dukekimm/Works/RAGaaS/frontend

# 의존성 설치 (처음 한 번만)
npm install

# 개발 서버 실행
npm run dev
```

**실행 확인**: http://localhost:3002

## ✅ 실행 확인

모든 서비스가 정상 실행되면:

| 서비스 | URL | 설명 |
|--------|-----|------|
| Frontend | http://localhost:3002 | React 애플리케이션 |
| Backend | http://localhost:8000 | FastAPI 백엔드 |
| Backend API Docs | http://localhost:8000/docs | Swagger UI |
| Ingest Service | http://localhost:8001 | 문서 처리 서비스 |

## 🛑 서비스 종료

각 터미널에서 `Ctrl+C`로 종료

데이터베이스 종료:
```bash
cd /Users/dukekimm/Works/RAGaaS
docker-compose down
```

## 🔧 환경 변수 설정

### Backend (.env)
```
OPENAI_API_KEY=your_api_key
MONGO_URI=mongodb://ragaas_app:ragaas-dev-pass@localhost:27017/ragaas?authSource=ragaas
MILVUS_HOST=localhost
MILVUS_PORT=19530
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
FUSEKI_URL=http://localhost:3030
INGEST_SERVICE_URL=http://localhost:8001
```

### Ingest Service (.env)
```
OPENAI_API_KEY=your_api_key
MILVUS_HOST=localhost
MILVUS_PORT=19530
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
FUSEKI_URL=http://localhost:3030
REDIS_URL=redis://localhost:6379/0
MAIN_BACKEND_URL=http://localhost:8000
```

## 🐛 문제 해결

### 포트 충돌
다른 프로세스가 포트를 사용 중인 경우:
```bash
# macOS/Linux
lsof -ti:8000 | xargs kill -9
lsof -ti:8001 | xargs kill -9
lsof -ti:3002 | xargs kill -9
```

### MongoDB 연결 오류
```bash
docker-compose ps  # 서비스 상태 확인
docker-compose logs mongo  # MongoDB 로그 확인
```

### Milvus 연결 오류
```bash
docker compose logs milvus  # Milvus 로그 확인 (shared-infra 디렉토리에서)
```

## 📝 개발 팁

- Backend/Ingest Service는 `--reload` 옵션으로 코드 변경 시 자동 재시작
- Frontend는 Vite HMR로 실시간 업데이트
- API 문서는 http://localhost:8000/docs 에서 확인 가능

## 🚢 배포 시

배포할 때는 `docker-compose.yml`에서 주석 처리된 backend, ingest-service, frontend 섹션의 주석을 제거하고 Docker로 실행하세요.
