import os
import re

out_dir = "/Users/dukekimm/Works/RAGaaS/docs/arch/system"
os.makedirs(out_dir, exist_ok=True)

# UC-001
uc001 = """# UC-001-지식 베이스 생성 시스템 구조 분석

## 개요

### Use Case ID
UC-001

### 제목
지식 베이스 생성

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor Admin as 시스템 관리자

  box RAGaaS 시스템
    participant KnowledgeBaseUI@{ "type" : "boundary" }
    participant KnowledgeBaseManager@{ "type" : "control" }
    participant MetaDB@{ "type" : "entity" }
    participant VectorDB@{ "type" : "entity" }
    participant GraphDB@{ "type" : "entity" }
  end
  
  Admin->>KnowledgeBaseUI: 지식 베이스 등록 정보
  KnowledgeBaseUI->>KnowledgeBaseManager: 등록 정보 검증 요청
  KnowledgeBaseManager->>MetaDB: 지식 베이스 메타데이터
  KnowledgeBaseManager->>VectorDB: 컬렉션 할당 정보
  KnowledgeBaseManager->>GraphDB: 파티션 할당 정보
  KnowledgeBaseManager-->>KnowledgeBaseUI: 생성 결과 데이터
  KnowledgeBaseUI-->>Admin: 생성 완료 메시지
```
"""

# UC-002
uc002 = """# UC-002-지식 베이스 목록 조회 시스템 구조 분석

## 개요

### Use 제로 ID
UC-002

### 제목
지식 베이스 목록 조회

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor Admin as 시스템 관리자

  box RAGaaS 시스템
    participant KnowledgeBaseUI@{ "type" : "boundary" }
    participant KnowledgeBaseManager@{ "type" : "control" }
    participant MetaDB@{ "type" : "entity" }
  end
  
  Admin->>KnowledgeBaseUI: 목록 조회 요청
  KnowledgeBaseUI->>KnowledgeBaseManager: 목록 조회 요청
  KnowledgeBaseManager->>MetaDB: 조회 쿼리
  MetaDB-->>KnowledgeBaseManager: 조회 결과 데이터
  KnowledgeBaseManager-->>KnowledgeBaseUI: 통계 포함 목록 데이터
  KnowledgeBaseUI-->>Admin: 목록 표시 정보
```
"""

# UC-003
uc003 = """# UC-003-지식 베이스 삭제 시스템 구조 분석

## 개요

### Use Case ID
UC-003

### 제목
지식 베이스 삭제

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor Admin as 시스템 관리자

  box RAGaaS 시스템
    participant KnowledgeBaseUI@{ "type" : "boundary" }
    participant KnowledgeBaseManager@{ "type" : "control" }
    participant VectorDB@{ "type" : "entity" }
    participant GraphDB@{ "type" : "entity" }
    participant FileSystem@{ "type" : "entity" }
    participant MetaDB@{ "type" : "entity" }
  end
  
  Admin->>KnowledgeBaseUI: 삭제 대상 정보
  KnowledgeBaseUI->>KnowledgeBaseManager: 삭제 대상 정보
  KnowledgeBaseManager-->>KnowledgeBaseUI: 삭제 확인 요청 메시지
  KnowledgeBaseUI-->>Admin: 확인 팝업창
  Admin->>KnowledgeBaseUI: 승인 입력
  KnowledgeBaseUI->>KnowledgeBaseManager: 최종 삭제 요청
  KnowledgeBaseManager->>VectorDB: 컬렉션 식별자
  KnowledgeBaseManager->>GraphDB: 그래프 파티션 식별자
  KnowledgeBaseManager->>FileSystem: 파일 경로 정보
  KnowledgeBaseManager->>MetaDB: 메타데이터 식별자
  KnowledgeBaseManager-->>KnowledgeBaseUI: 삭제 결과 데이터
  KnowledgeBaseUI-->>Admin: 완료 안내 메시지
```
"""

# UC-101
uc101 = """# UC-101-비정형 문서 업로드 시스템 구조 분석

## 개요

### Use Case ID
UC-101

### 제목
비정형 문서 업로드

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor Admin as 시스템 관리자

  box RAGaaS 시스템
    participant DocumentUI@{ "type" : "boundary" }
    participant DocumentManager@{ "type" : "control" }
    participant FileSystem@{ "type" : "entity" }
    participant MetaDB@{ "type" : "entity" }
  end
  
  Admin->>DocumentUI: 업로드 대상 파일
  DocumentUI->>DocumentManager: 파일 형식/크기 정보
  DocumentManager->>FileSystem: 파일 이진 데이터
  DocumentManager->>MetaDB: 문서 메타데이터 정보
  DocumentManager-->>DocumentUI: 문서 생성 결과
  DocumentUI-->>Admin: 성공 여부 메시지
```
"""

# UC-102
uc102 = """# UC-102-지식 추출 및 인덱싱 시스템 구조 분석

## 개요

### Use Case ID
UC-102

### 제목
지식 추출 및 인덱싱

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor Admin as 시스템 관리자

  box RAGaaS 시스템
    participant DocumentUI@{ "type" : "boundary" }
    participant ExtractionManager@{ "type" : "control" }
    participant EmbedInterface@{ "type" : "boundary" }
    participant GraphInterface@{ "type" : "boundary" }
    participant VectorDB@{ "type" : "entity" }
    participant GraphDB@{ "type" : "entity" }
    participant MetaDB@{ "type" : "entity" }
  end
  
  %% secondary actors
  actor Embed as Embedding Service
  actor GraphSvc as Graph Extraction Service
  
  Admin->>DocumentUI: 추출 대상 문서 정보
  DocumentUI->>ExtractionManager: 처리 요청 정보
  ExtractionManager->>EmbedInterface: 텍스트 청크 데이터
  EmbedInterface->>Embed: 텍스트 청크 데이터
  Embed-->>EmbedInterface: 임베딩 벡터 데이터
  EmbedInterface-->>ExtractionManager: 벡터 리스트
  ExtractionManager->>GraphInterface: 텍스트 데이터
  GraphInterface->>GraphSvc: 텍스트 데이터
  GraphSvc-->>GraphInterface: 지식 트리플 데이터
  GraphInterface-->>ExtractionManager: 트리플 리스트
  ExtractionManager->>VectorDB: 인덱싱 벡터 데이터
  ExtractionManager->>GraphDB: 트리플 저장 데이터
  ExtractionManager->>MetaDB: 완료 상태 정보
  ExtractionManager-->>DocumentUI: 처리 결과 통계 데이터
  DocumentUI-->>Admin: 통계 현황 뷰
```
"""

# UC-104
uc104 = """# UC-104-온톨로지 프로모션 시스템 구조 분석

## 개요

### Use Case ID
UC-104

### 제목
온톨로지 프로모션

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor Admin as 시스템 관리자

  box RAGaaS 시스템
    participant OntologyUI@{ "type" : "boundary" }
    participant OntologyManager@{ "type" : "control" }
    participant PromoterInterface@{ "type" : "boundary" }
    participant GraphDB@{ "type" : "entity" }
  end
  
  %% secondary actors
  actor Promoter as Ontology Promoter
  
  Admin->>OntologyUI: 분석 대상 지식 베이스
  OntologyUI->>OntologyManager: 분석 요청 파라미터
  OntologyManager->>GraphDB: 통계 요청 쿼리
  GraphDB-->>OntologyManager: 트리플 통계 데이터
  OntologyManager->>PromoterInterface: 후보 스키마 요청 데이터
  PromoterInterface->>Promoter: 패턴 분석 요청 데이터
  Promoter-->>PromoterInterface: 후보 클래스/속성 데이터
  PromoterInterface-->>OntologyManager: 스키마 리스트
  OntologyManager-->>OntologyUI: 후보 제안 데이터
  OntologyUI-->>Admin: 검토용 목록 UI
  Admin->>OntologyUI: 승인/수정 정보
  OntologyUI->>OntologyManager: 최종 스키마 정보
  OntologyManager->>GraphDB: 갱신된 온톨로지 모델
  OntologyManager-->>OntologyUI: 프로모션 결과 정보
  OntologyUI-->>Admin: 완료 요약 알림
```
"""

# UC-201
uc201 = """# UC-201-하이브리드 검색 실행 시스템 구조 분석

## 개요

### Use Case ID
UC-201

### 제목
하이브리드 검색 실행

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor App as AI 애플리케이션

  box RAGaaS 시스템
    participant SearchAPI@{ "type" : "boundary" }
    participant SearchController@{ "type" : "control" }
    participant EmbedInterface@{ "type" : "boundary" }
    participant VectorDB@{ "type" : "entity" }
  end
  
  %% secondary actors
  actor Embed as Embedding Service
  
  App->>SearchAPI: 검색 쿼리 및 옵션
  SearchAPI->>SearchController: 파싱된 쿼리 데이터
  SearchController->>EmbedInterface: 임베딩 변환 요청 문자열
  EmbedInterface->>Embed: 임베딩 변환 요청 문자열
  Embed-->>EmbedInterface: 쿼리 벡터 데이터
  EmbedInterface-->>SearchController: 쿼리 벡터 데이터
  SearchController->>VectorDB: 벡터 유사도 검색 조건
  VectorDB-->>SearchController: 벡터 일치 후보 리스트
  SearchController->>VectorDB: 키워드 검색 조건
  VectorDB-->>SearchController: 키워드 일치 후보 리스트
  SearchController-->>SearchAPI: 정렬된 청크 데이터 세트
  SearchAPI-->>App: 최종 검색 응답 데이터
```
"""

# UC-202
uc202 = """# UC-202-그래프 기반 검색 실행 시스템 구조 분석

## 개요

### Use Case ID
UC-202

### 제목
그래프 기반 검색 실행

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor Admin as 시스템 관리자

  box RAGaaS 시스템
    participant SearchUI@{ "type" : "boundary" }
    participant SearchController@{ "type" : "control" }
    participant GraphDB@{ "type" : "entity" }
  end
  
  Admin->>SearchUI: 그래프 쿼리 문자열
  SearchUI->>SearchController: 파싱된 쿼리 구조체
  SearchController->>GraphDB: 구조화된 질의문
  GraphDB-->>SearchController: 관계 매칭 후보 리스트
  SearchController-->>SearchUI: 그래프 포맷 결과 세트
  SearchUI-->>Admin: 시각화된 결과 화면
```
"""

# UC-203
uc203 = """# UC-203-검색 파이프라인 실험 시스템 구조 분석

## 개요

### Use Case ID
UC-203

### 제목
검색 파이프라인 실험

## 시퀀스 다이어그램

### 주요 시나리오

```mermaid
sequenceDiagram
  %% primary actor
  actor Admin as 시스템 관리자

  box RAGaaS 시스템
    participant PlaygroundUI@{ "type" : "boundary" }
    participant PipelineController@{ "type" : "control" }
    participant VectorDB@{ "type" : "entity" }
    participant GraphDB@{ "type" : "entity" }
  end

  Admin->>PlaygroundUI: 쿼리/전략/옵션 데이터
  PlaygroundUI->>PipelineController: 파이프라인 설정 정보
  PipelineController->>VectorDB: 벡터/키워드 질의 조건
  VectorDB-->>PipelineController: 1차 후보 리스트
  PipelineController->>GraphDB: 지식 확장 질의 조건
  GraphDB-->>PipelineController: 보조 관계 데이터
  PipelineController-->>PlaygroundUI: 단계별 점수 및 최종 청크 집합
  PlaygroundUI-->>Admin: 실험 결과 대시보드
```
"""

# model.md
model_md = """# 시스템 Context 모델

## 개요

### 목적
RAGaaS 통합 관리 시스템의 기능을 제공하기 위해 외부 이해관계자(사용자, 다른 시스템)와 주고받는 데이터 및 상호 작용을 정의하고 명세한다.

### 컴포넌트 분류 체계
- **Process**: 사용자 또는 외부 시스템과의 인터페이스 및 내부 로직 처리 책임 (여기서는 시스템 전체를 단일 프로세스로 간주)
- **Data Flow**: Data의 생성, 삭제, 이동의 흐름 정의
- **Data Store**: Data의 영구적인 저장 및 관리
- **External Entity**: 외부 시스템 및 사용자 정의

## 시스템 컨텍스트 모델

```mermaid
graph LR
    %% External Entities
    Admin[시스템 관리자]
    App[AI 애플리케이션]
    Embed[Embedding Service]
    GraphSvc[Graph Extraction Service]
    Promoter[Ontology Promoter]

    %% Processes
    System([RAGaaS 시스템])

    %% Data Stores
    MetaDB[(Metadata DB)]
    VectorDB[(Vector DB)]
    GraphDB[(Graph DB)]
    FS[(File System)]

    %% Data Flows (Admin)
    Admin -- "관리/조회 요청 정보" --> System
    System -- "모니터링 현황/결과 데이터" --> Admin

    %% Data Flows (AI App)
    App -- "검색 쿼리 데이터" --> System
    System -- "검색 결과 청크 데이터" --> App

    %% Data Flows (External Services)
    System -- "텍스트/청크 데이터" --> Embed
    Embed -- "임베딩 벡터 데이터" --> System

    System -- "텍스트/청크 데이터" --> GraphSvc
    GraphSvc -- "지식 트리플 데이터" --> System

    System -- "지식 그래프 통계 데이터" --> Promoter
    Promoter -- "후보 온톨로지 스키마" --> System

    %% Data Flows (Stores)
    System -- "메타데이터 레코드" --> MetaDB
    MetaDB -- "목록/상태 조회 데이터" --> System

    System -- "벡터/키워드 질의" --> VectorDB
    VectorDB -- "매칭 청크 리스트" --> System

    System -- "그래프 쿼리 및 트리플" --> GraphDB
    GraphDB -- "온톨로지/관계 데이터" --> System

    System -- "원본 파일 바이너리" --> FS
    FS -- "파일 상태 정보" --> System
```

## Process (System)

### RAGaaS 시스템
- **역할**: 다수의 지식 기반을 중앙에서 관리하고 지식화하며, 벡터/그래프 하이브리드 검색을 제공
- **책임**: 
  - 지식 베이스 관리 및 상태 모니터링
  - 문서의 수집, 파일 저장 및 메타 통제
  - 임베딩/지식 추출 위임 및 결과물 저장/정리
  - 외부의 검색 쿼리를 받아 데이터 저장소 조회를 수행하고 파이프라인 실험 환경 관리
- **관련 Use Case**: UC-001, UC-002, UC-003, UC-101, UC-102, UC-104, UC-201, UC-202, UC-203

## External Entity

### 시스템 관리자
- **역할**: 서비스를 구성하고 데이터를 제공하며 서비스 현황을 파악하는 주체
- **교환 정보**: 지식 베이스 관리 명령, 문서/파일, 조회 및 시각화 화면
- **관련 Use Case**: UC-001, UC-002, UC-003, UC-101, UC-102, UC-104, UC-202, UC-203

### AI 애플리케이션
- **역할**: 인덱싱된 지식을 소비하여 LLM 프롬프트에 활용하는 외부 시스템
- **교환 정보**: 검색 쿼리 질문 패킷, 반환된 후보 텍스트 조각
- **관련 Use Case**: UC-201

### Embedding Service
- **역할**: 전달받은 텍스트를 고차원 숫자 벡터로 스코어링 반환
- **교환 정보**: 분할된 텍스트, 임베딩된 벡터 값
- **관련 Use Case**: UC-102, UC-201

### Graph Extraction Service
- **역할**: 자연어 문장에서 주어, 서술어, 목적어 등을 분석하여 지식의 연관성 트리플로 반환
- **교환 정보**: 원문 문서 텍스트, 엔티티/관계 데이터
- **관련 Use Case**: UC-102

### Ontology Promoter
- **역할**: 다량의 유사 트리플 데이터셋으로부터 구조적 패턴 도출
- **교환 정보**: 지식 트리플 통계 데이터, 제안 스키마 구조
- **관련 Use Case**: UC-104

## Data Store

### Metadata DB
- **역할**: 시스템에 등록된 관리 대상 요소(KB, 문서 상태 등)의 이력 보관
- **관리 데이터**: 식별자, 처리 상태값, 용량/건수 통계
- **관련 Use Case**: UC-001, UC-002, UC-003, UC-101, UC-102

### Vector DB
- **역할**: 추출된 벡터 값들의 고속 ANN 인덱싱 공간
- **관리 데이터**: 임베딩 벡터 배열 및 연관 청크 원문
- **관련 Use Case**: UC-001, UC-003, UC-102, UC-201, UC-203

### Graph DB
- **역할**: 도출된 지식 네트워크 및 스키마 관계 매핑 저장
- **관리 데이터**: 지식 트리플(Subject-Predicate-Object), 온톨로지 정의
- **관련 Use Case**: UC-001, UC-003, UC-102, UC-104, UC-202, UC-203

### File System
- **역할**: 사용자가 시스템에 최초로 위탁한 원본 문서 기록
- **관리 데이터**: 비정형 파일 형태(PDF 등)
- **관련 Use Case**: UC-003, UC-101
"""

files = {
    "UC-001-지식 베이스 생성.md": uc001,
    "UC-002-지식 베이스 목록 조회.md": uc002,
    "UC-003-지식 베이스 삭제.md": uc003,
    "UC-101-비정형 문서 업로드.md": uc101,
    "UC-102-지식 추출 및 인덱싱.md": uc102,
    "UC-104-온톨로지 프로모션.md": uc104,
    "UC-201-하이브리드 검색 실행.md": uc201,
    "UC-202-그래프 기반 검색 실행.md": uc202,
    "UC-203-검색 파이프라인 실험.md": uc203,
    "model.md": model_md
}

for filename, content in files.items():
    with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
  
print("All files generated successfully.")
