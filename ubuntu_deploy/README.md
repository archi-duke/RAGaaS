# Ubuntu 폐쇄망 배포 패키지

이 디렉토리는 인터넷이 차단된 Ubuntu 폐쇄망 환경에 RAG Management System을 설치하기 위한 패키지입니다.

## 특징

- ✅ **Docker 없이 Backend/Frontend 실행** (소스 코드 수정 가능)
- ✅ **Milvus/Fuseki만 Docker 사용** (인프라 관리 편의성)
- ✅ **완전 오프라인 설치** (인터넷 불필요)
- ✅ **개발 환경 구성** (코드 수정 후 재시작만)

## 빠른 시작

### 1. 인터넷 환경 (패키지 준비)

```bash
# 패키지 다운로드 (20-30분 소요)
./prepare-package.sh

# 생성된 tar.gz를 폐쇄망 서버로 전송
# 파일명: ragaas-ubuntu-offline-YYYYMMDD-HHMMSS.tar.gz
```

### 2. 폐쇄망 환경 (설치)

```bash
# 압축 해제
tar -xzf ragaas-ubuntu-offline-*.tar.gz
cd ubuntu_deploy

# 설치 실행
sudo ./install.sh

# 환경 설정
sudo vi /opt/ragaas/backend/.env  # OpenAI API Key 설정

# 서비스 시작
sudo /opt/ragaas/start.sh
```

### 3. 접속

- Frontend: http://서버IP:5173
- Backend: http://서버IP:8000/docs
- Fuseki: http://서버IP:3030

## 파일 구조

```
ubuntu_deploy/
├── prepare-package.sh    # 패키지 준비 스크립트 (인터넷 환경용)
├── install.sh           # 설치 스크립트 (폐쇄망 환경용)
├── UBUNTU-DEPLOY.md     # 상세 배포 가이드
├── README.md            # 이 파일
└── packages/            # 다운로드된 패키지 (생성됨)
    ├── python/          # Python wheel 파일
    ├── nodejs/          # Node.js 패키지
    ├── docker/          # Docker 이미지
    └── system/          # 시스템 패키지 목록
```

## 시스템 요구사항

### 준비 환경 (인터넷 연결)
- Ubuntu 20.04 / 22.04 (x86_64)
- Python 3.11, Node.js 18.x
- Docker
- 디스크 공간: 20GB

### 폐쇄망 환경 (배포 대상)
- Ubuntu 20.04 / 22.04 (x86_64)
- **준비 환경과 동일한 OS/아키텍처 필수**
- Python 3.11, Node.js 18.x
- Docker
- 최소 디스크: 30GB
- 최소 메모리: 8GB

## 주요 명령어

### 서비스 관리

```bash
# 시작
sudo /opt/ragaas/start.sh

# 중지
sudo /opt/ragaas/stop.sh

# 상태 확인
sudo /opt/ragaas/status.sh
```

### 개발 작업

```bash
# Backend 코드 수정
sudo vi /opt/ragaas/backend/app/api/retrieval.py
sudo systemctl restart ragaas-backend

# Frontend 코드 수정
cd /opt/ragaas/frontend
npm run build
sudo systemctl restart ragaas-frontend
```

### 로그 확인

```bash
# Backend 로그
sudo journalctl -u ragaas-backend -f

# Docker 로그
cd /opt/ragaas
docker-compose logs -f
```

## 상세 문서

전체 가이드는 [UBUNTU-DEPLOY.md](UBUNTU-DEPLOY.md)를 참조하세요.

주요 내용:
- 사전 준비 및 패키지 다운로드
- 폐쇄망 환경 설치 단계
- 서비스 시작 및 관리
- 개발 및 코드 수정 방법
- 백업 및 복원
- 트러블슈팅
- 완전 폐쇄망 대응 (OpenAI API 불가 시)

## 문의

설치 중 문제 발생 시:
1. 로그 수집: `sudo /opt/ragaas/status.sh > status.log`
2. 내부 지원팀에 문의
