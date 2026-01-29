# RAG Management System

Milvus 기반의 다수의 RAG (Retrieval-Augmented Generation) 지식 베이스를 생성하고 관리하는 시스템입니다.

## 기술 스택

### 코어 기술
- **Backend**: FastAPI (Python)
- **Frontend**: React + TypeScript (Vite)
- **Vector DB**: Milvus
- **Metadata DB**: SQLite
- **Embeddings**: OpenAI `text-embedding-3-small`
- **Reranking**: Cross-Encoder `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Keyword Search**: BM25 (rank-bm25)

### Graph RAG 기술 스택
- **Graph Database**: 
  - Apache Jena Fuseki (TDB2) - Ontology Mode
  - Neo4j - Knowledge Graph Mode
- **Query Language**: SPARQL 1.1, Cypher
- **Entity Extraction**: 
  - OpenAI GPT-4o-mini (LLM 기반)
  - spaCy (한국어 NER: `ko_core_news_sm`)
- **Graph Format**: RDF (N-Triples)
- **Python Libraries**: SPARQLWrapper, spaCy

## 주요 기능

### 지식 베이스 관리
- 다수의 지식 베이스 생성/조회/삭제
- 메타데이터 관리

### 문서 관리
- TXT, PDF, Markdown 파일 업로드
- 3가지 청킹 전략:
  - **Size 단위**: 고정 크기 분할
  - **Parent-Child**: 계층적 청크 구조
  - **Context Aware**: 의미 단위 분할

### 검색 전략 (4가지)
모든 검색 방식은 **코사인 유사도 (0~1)** 로 통일된 점수를 제공합니다.

- **ANN (Vector Search)**: 고속 벡터 유사도 검색
- **Keyword Search**: BM25 기반 키워드 매칭 검색
- **2-Stage Retrieval**: ANN 후보 검색 + Cross-Encoder 정밀 재평가 (자동으로 **L2 Flat Index** 검증 포함)
- **Hybrid (ANN + BM25)**: 벡터 검색과 키워드 검색을 결합 (Sequential/Parallel 모드 지원, 사용자 사전 `user_dic.txt` 지원)
- **Hybrid (+Graph / +Ontology)**: 지식 그래프의 관계를 탐색하여 숨겨진 연관 문서를 발견하는 고급 검색 (Graph Mode 활성화 시)

### 고급 검색 기능
- **선택적 리랭커**: Cross-Encoder 기반 의미적 관련성 재평가
- **NER 필터**: 엔티티 매칭 기반 점수 조정으로 정확도 향상
- **Flat Index (L2)**: 정밀 L2 거리 계산을 통한 최고 정확도 검색
  - 후보군에 대해 정확한 유클리드 거리 계산
  - L2 거리 임계값 필터링 (0.0-2.0)
  - Score와 L2 거리를 모두 표시하여 투명성 제공
- **Graph RAG (Beta)**: 지식 그래프 기반 관계 탐색 검색
  - **멀티 백엔드 지원**:
    - **Apache Jena Fuseki**: RDF 기반, SPARQL 추론 및 질의
    - **Neo4j**: Property Graph 기반, Cypher 질의 및 고성능 탐색
  - 이중 엔티티 추출: LLM (GPT-4o-mini) + spaCy NER
  - **의미 기반 쿼리 분석**: Multi-hop 관계 자동 감지 (예: "A의 B의 C")
  - **엔티티 자동 확장**: 관련 엔티티를 그래프에서 탐색하여 검색 범위 확대
  - SPARQL/Cypher 쿼리를 통한 유연한 엔티티 관계 탐색
  - 설정 가능한 그래프 탐색 깊이 (1-5 hops)
  - **Relation Filter (Neo4j)**: 관계 키워드 필터링 옵션 제공 (정밀도 vs 재현율 조절 가능)
  - **스코어 부스팅**: 그래프 검색 결과에 1.5x 가중치 적용
  - **Entity-Guided Retrieval (New)**: 그래프 검색으로 발견된 엔티티(Duke, 오일남 등)를 활용하여 원본 문서를 2차 검색하는 지능형 전략
  - **Text-to-SPARQL**: LLM을 활용한 자연어 질의 -> SPARQL 변환 지원 (Ontology Mode)
  - **향상된 디버깅**: 상세한 Trace Log, 타임스탬프, 소요 시간, 단계별 실행 내역 제공 (Debug Mode)
  - **Hybrid 검색 통합**: 그래프 지식과 문맥 기반 벡터 검색의 완벽한 조화
  - 추출된 엔티티, SPARQL/Cypher 쿼리, 트리플 메타데이터 표시

### 데이터 관리
- **Cascading Delete**: 지식 베이스 삭제 시 관련 문서 및 벡터 자동 삭제
- **실시간 상태 추적**: WebSocket을 통한 문서 처리 상태 업데이트

### 청크 뷰어
- 문서 클릭 시 청크 목록 조회

## 시작하기

### 1. Milvus 및 Fuseki 시작

```bash
docker-compose up -d
```

이 명령은 다음 서비스를 시작합니다:
- **Milvus**: 벡터 데이터베이스 (포트 19530)
- **Apache Jena Fuseki**: Graph RAG용 RDF 스토어 (포트 3030)
  - Fuseki UI: http://localhost:3030
- **Neo4j**: Knowledge Graph용 Graph DB (포트 7474, 7687)
  - Neo4j Browser: http://localhost:7474

### 2. Backend 설정

```bash
cd backend

# 가상환경 생성 (선택사항)
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# Graph RAG을 위한 spaCy 한국어 모델 다운로드 (선택사항)
python -m spacy download ko_core_news_sm

# 환경 변수 설정
cp .env.example .env
# .env 파일에서 OPENAI_API_KEY 설정

# 실행
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend 실행

```bash
cd frontend
npm install
npm run dev
# Vite 개발 서버 포트: 5173
```

### 4. 접속

- Frontend: http://localhost:5173
- Backend API Docs: http://localhost:8000/docs

## Docker를 사용한 배포

### 개발/테스트 환경

```bash
# 전체 스택 시작 (Milvus + Backend + Frontend)
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 중지
docker-compose down
```

### 폐쇄망(Air-Gapped) 환경 배포

인터넷이 차단된 폐쇄망 환경에 배포하는 방법:

**1. 인터넷 연결 환경에서 패키지 준비**:
```bash
# Docker 이미지와 애플리케이션을 하나의 패키지로 export
./export-for-airgap.sh

# 생성된 ragaas-deploy-YYYYMMDD-HHMMSS.tar.gz를 폐쇄망 서버로 전송
```

**2. 폐쇄망 서버에서 배포**:
```bash
# 패키지 압축 해제
tar -xzf ragaas-deploy-YYYYMMDD-HHMMSS.tar.gz
cd ragaas-deploy

# Docker 이미지 로드
./import-from-airgap.sh

# 환경 설정
vi .env  # OpenAI API Key 등 설정

# 서비스 시작
docker-compose up -d
```

**자세한 가이드**: [AIRGAP-DEPLOY.md](AIRGAP-DEPLOY.md) 참조

접속:
- Frontend: http://서버IP:5173
- Backend API: http://서버IP:8000/docs
- Fuseki Admin UI: http://localhost:3030 (Graph RAG 사용 시)

## 문서

- [서비스 가동 및 트러블슈팅 가이드](docs/startup_guide.md) **(추천)**
- [시스템 사양서](docs/specification.md)
- [구현 계획](docs/implementation_plan.md)
- [구현 완료 보고서](docs/walkthrough.md)
- [설정 가이드](SETUP.md)

## 프로젝트 구조

```
RAGaaS/
├── backend/              # FastAPI 백엔드
│   ├── app/
│   │   ├── api/         # API 라우터
│   │   ├── core/        # 설정 및 연결
│   │   ├── models/      # 데이터 모델
│   │   └── services/    # 비즈니스 로직
│   └── main.py
├── frontend/            # React 프론트엔드
│   └── src/
│       ├── pages/       # 페이지 컴포넌트
│       └── services/    # API 클라이언트
├── docs/                # 프로젝트 문서
├── docker-compose.yml   # Milvus 설정
└── README.md
```

## 라이선스

MIT
