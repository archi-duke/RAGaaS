# RAG Management System - Ubuntu 폐쇄망 배포 가이드

이 문서는 인터넷이 차단된 Ubuntu 폐쇄망 환경에 RAG Management System을 설치하는 방법을 설명합니다.

## 배포 구성

- **Backend/Frontend**: Docker 없이 직접 실행 (코드 수정 가능)
- **Milvus/Fuseki**: Docker로 실행
- **개발 환경**: 소스 코드 직접 수정 및 재시작 가능

---

## 사전 준비 (인터넷 연결 환경)

### 1. 시스템 요구사항

**준비 환경** (패키지 다운로드):
- OS: Ubuntu 20.04 / 22.04 (x86_64)
- 인터넷 연결 필수
- Docker 설치 (이미지 저장용)
- Python 3.11, Node.js 18.x 설치

**폐쇄망 환경** (배포 대상):
- OS: Ubuntu 20.04 / 22.04 (x86_64)
- **준비 환경과 동일한 OS 버전/아키텍처 필수**
- 최소 디스크: 30GB
- 최소 메모리: 8GB
- Docker 설치 (Milvus/Fuseki용)

### 2. 패키지 준비

```bash
cd RAGaaS/ubuntu_deploy

# 실행 권한 부여
chmod +x prepare-package.sh

# 패키지 다운로드 실행 (20-30분 소요)
./prepare-package.sh
```

**다운로드되는 항목**:
- Python wheel 패키지 (약 500MB)
- Node.js 패키지 (약 800MB)
- Docker 이미지 (Milvus, etcd, MinIO, Fuseki - 약 2GB)
- 소스 코드

**생성 파일**:
```
ragaas-ubuntu-offline-YYYYMMDD-HHMMSS.tar.gz  (약 3-4GB)
```

### 3. 폐쇄망으로 전송

생성된 `.tar.gz` 파일을 USB, NAS 등을 통해 폐쇄망 서버로 전송

---

## 폐쇄망 환경 설치

### 1. 사전 설치 (폐쇄망 서버)

#### Python 3.11 설치

Ubuntu 22.04:
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev python3-pip build-essential
```

Ubuntu 20.04 (추가 PPA 필요):
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev python3-pip build-essential
```

#### Node.js 18.x 설치

```bash
# NodeSource 저장소 추가 (오프라인이면 바이너리 직접 설치)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
```

**오프라인 설치** (권장):
```bash
# 인터넷 환경에서 다운로드
wget https://nodejs.org/dist/v18.17.0/node-v18.17.0-linux-x64.tar.xz

# 폐쇄망 서버에서 압축 해제
sudo tar -xJf node-v18.17.0-linux-x64.tar.xz -C /usr/local --strip-components=1
```

#### Docker 설치

```bash
sudo apt update
sudo apt install docker.io docker-compose
sudo systemctl enable docker
sudo systemctl start docker

# 현재 사용자를 docker 그룹에 추가
sudo usermod -aG docker $USER
```

설치 확인:
```bash
python3.11 --version  # Python 3.11.x
node --version        # v18.x.x
docker --version      # Docker 20.x+
```

### 2. 패키지 압축 해제

```bash
# 전송된 파일 압축 해제
tar -xzf ragaas-ubuntu-offline-*.tar.gz
cd ubuntu_deploy
```

### 3. 설치 실행

```bash
# 실행 권한 부여
chmod +x install.sh

# 설치 (sudo 필요)
sudo ./install.sh
```

설치 과정:
1. 시스템 요구사항 확인
2. `/opt/ragaas`에 파일 복사
3. Python 가상환경 생성 및 패키지 설치
4. Node.js 패키지 설치 및 빌드
5. Docker 이미지 로드
6. Systemd 서비스 생성
7. 관리 스크립트 생성

### 4. 환경 설정

```bash
# .env 파일 편집
sudo vi /opt/ragaas/backend/.env
```

**필수 설정**:
```env
# OpenAI API Key (필수)
OPENAI_API_KEY=sk-your-api-key-here

# Milvus 설정
MILVUS_HOST=localhost
MILVUS_PORT=19530

# Fuseki 설정
FUSEKI_URL=http://localhost:3030

# 데이터베이스
DATABASE_URL=sqlite:////opt/ragaas/backend/data/rag_system.db
```

---

## 서비스 시작

### 자동 시작 스크립트 사용

```bash
# 전체 서비스 시작
sudo /opt/ragaas/start.sh

# 상태 확인
sudo /opt/ragaas/status.sh

# 서비스 중지
sudo /opt/ragaas/stop.sh
```

### 수동 시작

```bash
# 1. Docker 인프라 시작 (Milvus, Fuseki)
cd /opt/ragaas
sudo docker-compose up -d

# 2. Backend 시작
sudo systemctl start ragaas-backend

# 3. Frontend 시작
sudo systemctl start ragaas-frontend
```

### 부팅 시 자동 시작

```bash
sudo systemctl enable ragaas-backend
sudo systemctl enable ragaas-frontend
```

---

## 접속 확인

서비스 시작 후:

- **Frontend**: http://서버IP:5173
- **Backend API**: http://서버IP:8000/docs
- **Fuseki**: http://서버IP:3030

---

## 개발 및 코드 수정

### Backend 코드 수정

```bash
# 1. 코드 수정
sudo vi /opt/ragaas/backend/app/api/retrieval.py

# 2. 서비스 재시작
sudo systemctl restart ragaas-backend

# 3. 로그 확인
sudo journalctl -u ragaas-backend -f
```

### Frontend 코드 수정

```bash
# 1. 코드 수정
cd /opt/ragaas/frontend/src
sudo vi components/ChatInterface.tsx

# 2. 재빌드
cd /opt/ragaas/frontend
npm run build

# 3. 서비스 재시작
sudo systemctl restart ragaas-frontend
```

### 개발 모드 실행

**Backend 개발 서버**:
```bash
cd /opt/ragaas/backend
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend 개발 서버**:
```bash
cd /opt/ragaas/frontend
npm run dev
```

---

## 로그 확인

### Systemd 서비스 로그

```bash
# Backend 로그
sudo journalctl -u ragaas-backend -f

# Frontend 로그
sudo journalctl -u ragaas-frontend -f
```

### Docker 로그

```bash
# 전체 로그
cd /opt/ragaas
docker-compose logs -f

# 특정 서비스 로그
docker logs ragaas-milvus -f
docker logs ragaas-fuseki -f
```

---

## 백업 및 복원

### 백업

```bash
# 데이터 백업
sudo tar -czf ragaas-backup-$(date +%Y%m%d).tar.gz \
    /opt/ragaas/backend/data \
    /opt/ragaas/volumes

# 설정 백업
sudo cp /opt/ragaas/backend/.env ~/ragaas-env-backup
```

### 복원

```bash
# 데이터 복원
sudo tar -xzf ragaas-backup-YYYYMMDD.tar.gz -C /

# 서비스 재시작
sudo /opt/ragaas/stop.sh
sudo /opt/ragaas/start.sh
```

---

## 트러블슈팅

### 1. Python 패키지 설치 실패

**증상**: `pip install` 중 에러

**해결**:
```bash
# 빌드 도구 확인
sudo apt install build-essential python3.11-dev gcc g++

# 수동 설치 시도
cd /opt/ragaas/ubuntu_deploy/packages/python
sudo /opt/ragaas/backend/venv/bin/pip install --no-index --find-links=. <패키지명>
```

### 2. Node.js 메모리 부족

**증상**: `npm run build` 실패

**해결**:
```bash
# Node.js 메모리 증가
export NODE_OPTIONS="--max-old-space-size=4096"
npm run build
```

### 3. Docker 컨테이너 시작 실패

**증상**: Milvus 또는 Fuseki 시작 안 됨

**해결**:
```bash
# 로그 확인
cd /opt/ragaas
docker-compose logs

# 컨테이너 재시작
docker-compose down
docker-compose up -d
```

### 4. 포트 충돌

**증상**: "Address already in use"

**해결**:
```bash
# 포트 사용 확인
sudo netstat -tulpn | grep :8000

# systemd 서비스 포트 변경
sudo vi /etc/systemd/system/ragaas-backend.service
# ExecStart 줄에서 --port 8000 -> --port 8001 변경

sudo systemctl daemon-reload
sudo systemctl restart ragaas-backend
```

---

## 완전 폐쇄망 대응 (OpenAI API 불가)

OpenAI API 사용이 불가능한 경우:

### 옵션 1: 로컬 임베딩 모델

`/opt/ragaas/backend/app/services/embedding.py` 수정:

```python
from sentence_transformers import SentenceTransformer

class EmbeddingService:
    def __init__(self):
        # 로컬 모델 사용
        self.model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
    
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts)
        return embeddings.tolist()
```

`requirements.txt`에 추가:
```
sentence-transformers>=2.2.0
```

재설치:
```bash
cd /opt/ragaas/backend
source venv/bin/activate
pip install sentence-transformers
```

### 옵션 2: 사내 LLM 프록시

`.env` 수정:
```env
OPENAI_API_KEY=your-internal-api-key
OPENAI_API_BASE=http://internal-llm-gateway:8080/v1
```

---

## 업데이트 절차

새 버전 배포:

```bash
# 1. 서비스 중지
sudo /opt/ragaas/stop.sh

# 2. 백업
sudo tar -czf ragaas-backup-before-update.tar.gz /opt/ragaas

# 3. 새 소스 복사
sudo rsync -av ubuntu_deploy/backend/ /opt/ragaas/backend/
sudo rsync -av ubuntu_deploy/frontend/ /opt/ragaas/frontend/

# 4. 패키지 재설치 (필요시)
cd /opt/ragaas/backend
source venv/bin/activate
pip install -r requirements.txt

cd /opt/ragaas/frontend
npm ci
npm run build

# 5. 서비스 시작
sudo /opt/ragaas/start.sh
```

---

## 디렉토리 구조

```
/opt/ragaas/
├── backend/
│   ├── app/              # 소스 코드 (수정 가능)
│   ├── venv/             # Python 가상환경
│   ├── data/             # SQLite DB
│   ├── .env              # 환경 설정
│   └── requirements.txt
├── frontend/
│   ├── src/              # 소스 코드 (수정 가능)
│   ├── dist/             # 빌드된 파일
│   └── package.json
├── volumes/              # Docker 데이터
│   ├── milvus/
│   ├── etcd/
│   ├── minio/
│   └── fuseki/
├── docker-compose.yml    # Milvus/Fuseki 설정
├── start.sh              # 시작 스크립트
├── stop.sh               # 중지 스크립트
└── status.sh             # 상태 확인
```

---

## 보안 권장사항

1. **Fuseki 비밀번호 변경**:
```yaml
# docker-compose.yml
services:
  fuseki:
    environment:
      - ADMIN_PASSWORD=강력한비밀번호
```

2. **MinIO 비밀번호 변경**:
```yaml
services:
  minio:
    environment:
      MINIO_ACCESS_KEY: 사용자키
      MINIO_SECRET_KEY: 강력한시크릿
```

3. **방화벽 설정**:
```bash
# 필요한 포트만 개방
sudo ufw allow 5173/tcp  # Frontend
sudo ufw allow 8000/tcp  # Backend

# 내부 서비스는 localhost만
# Milvus (19530), Fuseki (3030), MinIO (9000)
```

---

## 지원

문제 발생 시:
1. 로그 수집: `sudo /opt/ragaas/status.sh > status.log`
2. 시스템 정보: `uname -a; lsb_release -a`
3. 내부 지원팀에 문의

---

**문서 버전**: 1.0  
**최종 업데이트**: 2025-12-18
