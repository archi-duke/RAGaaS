# 로컬 개발 환경 실행 가이드

## 개요
개발 시에는 Backend, Frontend, Ingest Service를 **로컬에서 직접 실행**하고,
데이터베이스들(Milvus, Neo4j, Fuseki, MongoDB, Redis)만 Docker로 실행합니다.

---

## 1️⃣ 데이터베이스 시작 (Docker)

```bash
# 프로젝트 루트에서
docker-compose up -d
```

실행되는 컨테이너:
- ✅ Milvus (포트: 19530)
- ✅ Neo4j (포트: 7687, 7474)
- ✅ Fuseki (포트: 3030)
- ✅ MongoDB (포트: 27017)
- ✅ Redis (포트: 6379)
- ✅ etcd, minio (Milvus 의존성)

**확인:**
```bash
docker ps
# 위 6개 컨테이너가 Up 상태여야 함
```

---

## 2️⃣ Backend 실행

### 터미널 1:
```bash
cd backend

# 가상환경 활성화 (선택)
# python -m venv venv
# source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치 (최초 1회)
pip install -r requirements.txt

# 실행
uvicorn app.main:app --reload --port 8000
```

**확인:**
- http://localhost:8000/docs (Swagger UI)
- http://localhost:8000/api/health (응답: 404 정상 - health endpoint 없음)

---

## 3️⃣ Ingest Service 실행

### 터미널 2:
```bash
cd ingest_service

# 가상환경 활성화 (선택)
# python -m venv venv
# source venv/bin/activate

# 의존성 설치 (최초 1회)
pip install -r requirements.txt

# 실행
uvicorn app.main:app --reload --port 8001
```

**확인:**
- http://localhost:8001/health (응답: `{"status":"healthy","service":"ingest-service"}`)
- http://localhost:8001/docs (Swagger UI)

---

## 4️⃣ Frontend 실행

### 터미널 3:
```bash
cd frontend

# 의존성 설치 (최초 1회)
npm install

# 실행
npm run dev
```

**확인:**
- http://localhost:5173 (React 앱)

---

## 환경 변수 설정

### Backend (`.env`)
```env
OPENAI_API_KEY=your-key-here
MONGO_URI=mongodb://root:example@localhost:27017
MILVUS_HOST=localhost
NEO4J_URI=bolt://localhost:7687
FUSEKI_URL=http://localhost:3030
INGEST_SERVICE_URL=http://localhost:8001
SHARED_STORAGE_PATH=/Users/dukekimm/Works/RAGaaS/data/uploads
CALLBACK_BASE_URL=http://localhost:8000
```

### Ingest Service (`.env`)
```env
OPENAI_API_KEY=your-key-here
MILVUS_HOST=localhost
NEO4J_URI=bolt://localhost:7687
FUSEKI_URL=http://localhost:3030
REDIS_URL=redis://localhost:6379/0
SHARED_STORAGE_PATH=/Users/dukekimm/Works/RAGaaS/data/uploads
MAIN_BACKEND_URL=http://localhost:8000
```

---

## 문제 해결

### 1. "Address already in use" 에러
```bash
# 포트 사용 중인 프로세스 확인
lsof -i :8000  # Backend
lsof -i :8001  # Ingest Service
lsof -i :5173  # Frontend

# 프로세스 종료
kill -9 <PID>
```

### 2. Docker 컨테이너 연결 안 됨
```bash
# 컨테이너 상태 확인
docker ps

# 재시작
docker-compose restart

# 로그 확인
docker logs ragaas-mongo
docker logs milvus-standalone
```

### 3. MongoDB 연결 오류
```bash
# MongoDB 연결 테스트
mongosh "mongodb://root:example@localhost:27017"
```

### 4. 파일 권한 오류 (SHARED_STORAGE_PATH)
```bash
# data/uploads 디렉토리 권한 확인
ls -la data/uploads

# 권한 설정
chmod -R 755 data/uploads
```

---

## 배포 시 Docker로 전환

`docker-compose.yml`에서 주석 해제:
```bash
# 1. docker-compose.yml 편집
# backend, ingest-service, frontend 섹션의 주석(#) 제거

# 2. 환경 변수 변경 (Docker 네트워크 사용)
# - MILVUS_HOST=standalone (not localhost)
# - MONGO_URI=mongodb://root:example@mongo:27017 (not localhost)
# - INGEST_SERVICE_URL=http://ingest-service:8001
# - CALLBACK_BASE_URL=http://backend:8000

# 3. 실행
docker-compose up -d --build
```

---

## 현재 상태 확인

```bash
# 로컬 프로세스
ps aux | grep uvicorn
ps aux | grep node

# Docker 컨테이너
docker ps

# 포트 확인
lsof -i :8000,8001,5173,19530,3030,7687,27017,6379
```
