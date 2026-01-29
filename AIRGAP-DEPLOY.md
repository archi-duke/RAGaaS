# 폐쇄망(Air-Gapped) 환경 배포 가이드

이 문서는 RAG Management System을 인터넷이 차단된 폐쇄망 환경에 배포하는 방법을 설명합니다.

## 사전 준비 (인터넷 연결 환경)

### 1. Docker 이미지 빌드 및 저장

```bash
# 프로젝트 디렉토리로 이동
cd RAGaaS

# 모든 서비스 이미지 빌드
docker-compose build

# 필요한 모든 이미지 pull
docker-compose pull

# 빌드된 이미지 확인
docker images | grep -E "ragaas|milvus|etcd|minio|fuseki"
```

### 2. Docker 이미지 저장

```bash
# 이미지 목록 저장 스크립트 생성
cat > export-images.sh << 'EOF'
#!/bin/bash

# 이미지 목록
IMAGES=(
    "ragaas-backend:latest"
    "ragaas-frontend:latest"
    "milvusdb/milvus:v2.3.3"
    "quay.io/coreos/etcd:v3.5.5"
    "minio/minio:RELEASE.2023-03-20T20-16-18Z"
    "stain/jena-fuseki:latest"
    "nginx:alpine"
    "node:18-alpine"
    "python:3.11-slim"
)

# 각 이미지를 tar 파일로 저장
mkdir -p docker-images
for image in "${IMAGES[@]}"; do
    echo "Saving $image..."
    filename=$(echo $image | sed 's/:/_/g' | sed 's/\//_/g')
    docker save -o "docker-images/${filename}.tar" "$image"
done

echo "All images saved to docker-images/"
EOF

chmod +x export-images.sh
./export-images.sh
```

### 3. 전체 패키지 준비

```bash
# 배포 패키지 디렉토리 생성
mkdir -p ragaas-deploy

# 필수 파일 복사
cp -r backend ragaas-deploy/
cp -r frontend ragaas-deploy/
cp docker-compose.yml ragaas-deploy/
cp .env.example ragaas-deploy/.env
cp -r docker-images ragaas-deploy/

# 배포 가이드 복사
cp AIRGAP-DEPLOY.md ragaas-deploy/

# 압축
tar -czf ragaas-deploy.tar.gz ragaas-deploy/
```

### 4. 전송할 파일

- `ragaas-deploy.tar.gz` (전체 애플리케이션 + Docker 이미지)

**예상 크기**: 약 3-5GB (이미지 포함)

---

## 폐쇄망 환경 배포 (인터넷 차단 환경)

### 1. 사전 요구사항

폐쇄망 서버에 다음이 설치되어 있어야 합니다:
- Docker (20.10 이상)
- Docker Compose (v2.0 이상)
- 최소 디스크 공간: 20GB
- 최소 메모리: 8GB

### 2. 파일 전송

```bash
# USB, NAS 등을 통해 ragaas-deploy.tar.gz를 폐쇄망 서버로 전송
# 예: /opt/ragaas-deploy.tar.gz
```

### 3. 압축 해제

```bash
cd /opt
tar -xzf ragaas-deploy.tar.gz
cd ragaas-deploy
```

### 4. Docker 이미지 로드

```bash
# 이미지 로드 스크립트 생성
cat > load-images.sh << 'EOF'
#!/bin/bash

echo "Loading Docker images..."
for image in docker-images/*.tar; do
    echo "Loading $image..."
    docker load -i "$image"
done

echo "All images loaded successfully!"
docker images
EOF

chmod +x load-images.sh
./load-images.sh
```

### 5. 환경 설정

```bash
# .env 파일 편집
vi .env
```

**.env 파일 필수 설정**:
```env
# OpenAI API Key (필수)
OPENAI_API_KEY=sk-your-api-key-here

# Milvus 설정
MILVUS_HOST=standalone
MILVUS_PORT=19530

# Fuseki 설정
FUSEKI_URL=http://fuseki:3030

# 데이터 볼륨 디렉토리 (선택사항)
DOCKER_VOLUME_DIRECTORY=./volumes
```

**⚠️ 중요**: OpenAI API 사용이 불가능한 완전 폐쇄망의 경우, 로컬 임베딩 모델로 교체가 필요합니다. (별도 가이드 참조)

### 6. 배포 실행

```bash
# 모든 서비스 시작
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 서비스 상태 확인
docker-compose ps
```

### 7. 접근 확인

- **Frontend**: http://서버IP
- **Backend API Docs**: http://서버IP:8000/docs
- **Milvus Admin**: http://서버IP:9091
- **Fuseki**: http://서버IP:3030

---

## 완전 폐쇄망(OpenAI API 불가) 대응

### 옵션 1: 로컬 임베딩 모델 사용

`sentence-transformers`를 사용한 로컬 임베딩으로 교체:

**backend/app/services/embedding.py 수정**:
```python
from sentence_transformers import SentenceTransformer

class EmbeddingService:
    def __init__(self):
        # OpenAI 대신 로컬 모델 사용
        self.model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
    
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts)
        return embeddings.tolist()
```

**requirements.txt에 추가**:
```
sentence-transformers>=2.2.0
```

### 옵션 2: 사내 프록시 LLM API 사용

조직 내부에 OpenAI 호환 API가 있는 경우:

**.env 수정**:
```env
OPENAI_API_KEY=your-internal-api-key
OPENAI_API_BASE=http://internal-llm-proxy:8080/v1
```

---

## 데이터 볼륨 관리

### 백업

```bash
# 데이터 백업
tar -czf ragaas-backup-$(date +%Y%m%d).tar.gz volumes/

# SQLite DB만 백업
cp backend/data/rag_system.db backups/rag_system_$(date +%Y%m%d).db
```

### 복원

```bash
# 전체 복원
tar -xzf ragaas-backup-YYYYMMDD.tar.gz

# DB만 복원
cp backups/rag_system_YYYYMMDD.db backend/data/rag_system.db
```

---

## 트러블슈팅

### 1. 메모리 부족 에러

Milvus와 Backend가 메모리를 많이 사용합니다. 최소 8GB RAM 권장.

**docker-compose.yml 수정**:
```yaml
services:
  backend:
    mem_limit: 2g
  standalone:
    mem_limit: 4g
```

### 2. Docker 이미지 로드 실패

```bash
# 이미지 파일 무결성 확인
md5sum docker-images/*.tar

# 수동 로드
docker load -i docker-images/specific-image.tar
```

### 3. 포트 충돌

기본 포트가 다른 서비스와 충돌하는 경우 **docker-compose.yml** 수정:

```yaml
services:
  frontend:
    ports:
      - "8080:80"  # 80 대신 8080 사용
  backend:
    ports:
      - "8001:8000"  # 8000 대신 8001 사용
```

### 4. Milvus 연결 실패

```bash
# Milvus 컨테이너 로그 확인
docker logs milvus-standalone

# etcd, minio 상태 확인
docker-compose ps
```

---

## 업데이트 절차

1. **개발 환경**에서 새 버전 빌드 및 이미지 저장
2. 새 `ragaas-deploy.tar.gz` 생성
3. 폐쇄망으로 전송
4. 백업 수행
5. 기존 컨테이너 중지: `docker-compose down`
6. 새 이미지 로드
7. 재시작: `docker-compose up -d`

---

## 보안 고려사항

### 1. 기본 비밀번호 변경

**Fuseki Admin**:
```yaml
services:
  fuseki:
    environment:
      - ADMIN_PASSWORD=강력한비밀번호
```

**Minio**:
```yaml
services:
  minio:
    environment:
      MINIO_ACCESS_KEY: 사용자정의키
      MINIO_SECRET_KEY: 강력한시크릿키
```

### 2. 네트워크 격리

필요한 포트만 외부 노출:

```yaml
services:
  backend:
    ports:
      - "127.0.0.1:8000:8000"  # localhost만 접근 가능
```

### 3. HTTPS 설정 (선택)

Nginx에서 SSL 인증서 설정:

```bash
# nginx.conf에 SSL 설정 추가 (별도 가이드 참조)
```

---

## 성능 최적화

### 1. Docker 볼륨 위치 변경

SSD에 볼륨 저장:

```env
DOCKER_VOLUME_DIRECTORY=/mnt/ssd/ragaas-volumes
```

### 2. Milvus 메모리 설정

**docker-compose.yml**:
```yaml
services:
  standalone:
    environment:
      - MILVUS_MEMORY_QUOTA_GB=4
```

---

## 지원 및 문의

문제 발생 시:
1. `docker-compose logs > logs.txt`로 전체 로그 수집
2. `docker-compose ps` 출력 확인
3. 내부 지원팀에 문의

---

## 체크리스트

배포 전 확인사항:

- [ ] Docker 및 Docker Compose 설치 확인
- [ ] 디스크 공간 20GB 이상 확보
- [ ] 메모리 8GB 이상 확보
- [ ] 모든 이미지 파일 무결성 확인
- [ ] .env 파일 설정 완료 (OpenAI API Key 등)
- [ ] 네트워크 포트 충돌 없음 확인
- [ ] 백업 계획 수립

배포 후 확인사항:

- [ ] 모든 컨테이너 정상 실행 (`docker-compose ps`)
- [ ] Frontend 접근 가능
- [ ] Backend API 정상 응답
- [ ] Milvus 연결 정상
- [ ] 지식 베이스 생성 테스트
- [ ] 문서 업로드 및 검색 테스트

---

**문서 버전**: 1.0  
**최종 업데이트**: 2025-12-18
