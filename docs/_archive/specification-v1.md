> 🗄️ **아카이브 (2026-07-15)** — 이 문서는 초기 설계 시점(v1)의 사양이며 현행 시스템과 다르다
> (SQLite→MongoDB, 고정 임베딩→프로바이더 레지스트리, 모놀리스→3서비스+MF, strategy→파이프라인 등).
> **현행 사양은 [`../specification-v2.md`](../specification-v2.md), 결정 이력은 [`../adr/`](../adr/) 참조.**

# RAG 관리 시스템 사양서 (Milvus 기반)

## 1. 개요
본 문서는 Milvus를 기반으로 하는 RAG (Retrieval-Augmented Generation) 관리 시스템의 사양을 정의합니다. 이 시스템은 사용자가 다수의 지식 베이스(Knowledge Base)를 생성 및 관리하고, 문서를 업로드하며, 검색 전략을 구성할 수 있도록 지원합니다. 디자인과 기능은 Dify의 Knowledge 기능을 참고하여 설계되었습니다.

## 2. 기술 스택

### 2.1 코어 기술
-   **프론트엔드**: React (Vite)
-   **백엔드**: FastAPI (Python)
-   **벡터 데이터베이스**: Milvus
-   **메타데이터 데이터베이스**: SQLite (간편함을 위해 선택, 추후 PostgreSQL로 확장 가능)
-   **임베딩 모델**: OpenAI `text-embedding-3-small`
-   **리랭킹 모델**: Cross-Encoder `cross-encoder/ms-marco-MiniLM-L-6-v2`
-   **키워드 검색**: BM25 (rank-bm25)

### 2.2 Graph-Enhanced RAG 기술 스택

**그래프 백엔드 옵션 1: Using Ontology (Jena+Fuseki) - Beta**
-   **그래프 데이터베이스**: Apache Jena Fuseki (TDB2 스토어)
-   **쿼리 언어**: SPARQL 1.1
-   **그래프 포맷**: RDF (N-Triples)
-   **Python 라이브러리**: SPARQLWrapper, spaCy
-   **네임스페이스**:
    -   엔티티: `http://rag.local/entity/`
    -   관계: `http://rag.local/relation/`
    -   소스: `http://rag.local/source/`

**그래프 백엔드 옵션 2: Using Knowledge Graph (Neo4j)**
-   **그래프 데이터베이스**: Neo4j
-   **쿼리 언어**: Cypher
-   **그래프 포맷**: 속성 그래프 (Property Graph)
-   **Python 라이브러리**: neo4j, spaCy

**공통**:
-   **엔티티 추출**: 
    -   OpenAI GPT-4o-mini (LLM 기반 관계 추출)
    -   spaCy NER (한국어 모델: `ko_core_news_sm`)
    -   이중 추출로 정확도 향상

## 3. 핵심 기능

### 3.1 지식 베이스 관리 (Knowledge Base Management)
-   **지식 베이스 생성**: 이름과 설명을 입력하여 새로운 지식 베이스 생성.
-   **지식 베이스 목록 조회**: 문서 수, 크기, 마지막 업데이트 시간 등의 메타데이터와 함께 목록 조회.
-   **지식 베이스 삭제**: 지식 베이스 삭제 시 관련된 모든 문서와 Milvus 컬렉션을 자동으로 삭제 (Cascading Delete).
-   **설정**: 기본 검색 설정 구성 (Top K, Score Threshold), 청킹 전략 및 유사도 측정 방식(COSINE/L2/IP) 선택.

### 3.2 문서 관리 (Document Management)
-   **문서 업로드**: TXT, PDF, Markdown 파일 지원.
-   **데이터 처리**:
    -   **청킹 (Chunking)**: 3가지 방식 지원
        -   **Size 단위**: 고정된 문자 수 또는 토큰 수로 분할 (오버랩 지원).
        -   **Parent-Child**: 문서를 큰 청크(Parent)와 작은 청크(Child)로 나누어 저장. 검색은 Child로 하되, 컨텍스트는 Parent를 참조.
        -   **Context Aware**: 문맥을 고려하여 의미 단위로 분할 (예: 섹션, 문단 기준).
    -   **정제 (Cleaning)**: 기본적인 텍스트 정제.
-   **인덱싱 (Indexing)**: 청크를 벡터 임베딩으로 변환하여 Milvus에 저장.
-   **문서 목록**: 지식 베이스 내 문서 목록 조회.
-   **청크 조회**: 문서의 개별 청크 내용 확인.
-   **상태 추적**: 인덱싱 상태 실시간 확인 (대기 중, 처리 중, 완료, 실패).

### 3.3 검색 전략 (Retrieval Strategy)
시스템은 4가지 검색 전략을 지원하며, 모든 전략은 **코사인 유사도 (0~1 범위)**로 통일된 점수를 제공합니다.

-   **ANN (Approximate Nearest Neighbor)**: 벡터 유사도 기반 고속 검색. KB 설정(COSINE/L2/IP)에 관계없이 최종 점수는 코사인 유사도로 재계산됩니다.
-   **키워드 검색 (Keyword Search)**: Milvus LIKE 연산자를 이용한 텍스트 매칭. 매칭된 결과에 대해 코사인 유사도를 계산하여 점수를 부여합니다.
-   **2단계 검색 (Two-Stage Retrieval)**:
    -   **1단계 (Candidate Generation)**: ANN으로 상위 25개 후보 검색.
    -   **2단계 (Reranking)**: Cross-Encoder 모델(`cross-encoder/ms-marco-MiniLM-L-6-v2`)로 정밀 평가 후 순위 재정렬.
    -   **UI 동작**: 2단계 검색 선택 시 자동으로 **Flat Index (L2)** 가 활성화되어, 최종 결과에 대해 정밀 거리 계산 검증을 수행합니다.
    -   **최종 점수**: 재정렬된 순서를 유지하되, 점수는 코사인 유사도로 표시.
-   **하이브리드 검색 (Hybrid Search - ANN + BM25)**:
    -   BM25 통계 기반 키워드 검색과 ANN 벡터 검색 결과를 결합.
    -   **Sequential Mode (기본)**: BM25로 후보군(Top-K)을 먼저 추출한 뒤, 해당 후보들에 대해 벡터 유사도를 계산하여 정렬합니다. 정확한 키워드 매칭을 보장하면서 의미적 정렬을 수행합니다.
    -   **Parallel Mode (옵션)**: BM25와 ANN 검색을 독립적으로 병렬 수행한 후, Reciprocal Rank Fusion (RRF) 알고리즘으로 순위를 통합합니다. 다양한 관점의 문서를 폭넓게 찾을 때 유리합니다.
    -   **토크나이저 (Kiwi)**: 한국어 형태소 분석기 Kiwi를 사용하여 명사, 동사, 형용사 등을 기반으로 정확한 토큰 매칭을 지원합니다.
        -   **사용자 사전 지원**: `backend/user_dic.txt` 파일을 통해 고유명사나 복합명사를 사용자 정의 단어로 등록하여 분절 오류를 방지할 수 있습니다.
    -   키워드 정확도와 의미적 유사성을 모두 고려한 최적의 검색 정확도 제공.
-   **하이브리드 그래프 검색 (Hybrid Search + Graph/Ontology)**:
    -   **Hybrid (+Graph)**: Neo4j 기반의 지식 그래프 탐색 결과를 통합하여 검색.
    -   **Hybrid (+Ontology)**: Jena Fuseki 기반의 온톨로지 추론 결과를 통합하여 검색.
    -   검색 쿼리에서 추출된 엔티티의 관계를 그래프에서 탐색하여, 텍스트 유사도만으로는 찾기 힘든 연관 문서를 발견합니다.

**통일된 점수 체계**: 모든 검색 전략은 Score Threshold (0~1)를 동일하게 적용할 수 있으며, 검색 결과 비교가 용이합니다.

### 3.4 선택적 리랭커 (Optional Reranker)

**2단계 검색을 제외한** 모든 검색 전략(ANN, 키워드, 하이브리드)에서 선택적으로 Cross-Encoder 리랭킹을 후처리 단계로 적용할 수 있습니다:

1. **초기 검색**: 선택한 전략으로 후보 결과 검색
2. **리랭킹**: Cross-Encoder(`cross-encoder/ms-marco-MiniLM-L-6-v2`)로 의미적 관련성 재평가
3. **필터링**: Reranker Top-K 및 Reranker Score Threshold 적용
4. **최종 결과**: 리랭커 순서 유지, 점수는 정규화된 리랭커 점수(0-1)

**파라미터**:
- `use_reranker`: 리랭커 사용 여부 (boolean, 기본값: false)
- `reranker_top_k`: 리랭킹 후 반환할 결과 수 (1-20, 기본값: 5)
- `reranker_threshold`: 리랭커 최소 점수 임계값 (0-1, 기본값: 0.0)

**참고**: 2단계 검색은 이미 Cross-Encoder를 내부적으로 사용하므로, 선택적 리랭커는 비활성화됩니다.

### 3.5 NER 필터 (Named Entity Recognition Filter)

질문에서 추출한 **개체명(엔티티)**이 검색 결과 청크에 포함되어 있는지 확인하여 점수를 조정합니다:

1. **엔티티 추출**: 질문에서 인명, 지명, 조직명 등을 추출
2. **매칭 확인**: 각 청크에 엔티티가 포함되어 있는지 확인
3. **점수 페널티**: 엔티티가 없는 청크는 점수에 0.3 곱셈 (70% 감소)
4. **재정렬**: 조정된 점수로 다시 정렬

**패턴 기반 한국어 NER**:
- 2-4글자 한국어 이름 패턴 인식
- "씨", "배우", "감독" 등 접미사 제거
- 정규식 기반 간단한 추출 (향후 spaCy 모델 업그레이드 가능)

**사용 예시**:
- 질문: "오영수 배우의 역할은?"
- 추출 엔티티: ["오영수"]
- 효과: "오영수"가 없는 청크 점수 대폭 하락 → "오영수"가 있는 청크만 상위 랭크

### 3.6 Flat Index (L2) 정밀 검색

**Flat Index (L2)** 는 초기 검색 결과(후보군)에 대해 **정확한 L2 거리 계산**을 수행하여 벡터 근접도를 정밀하게 측정하는 재순위화(Re-ranking) 방식입니다.

**동작 방식**:
1. **초기 검색**: 선택한 전략(ANN, Keyword, Hybrid 등)으로 후보 청크 검색
2. **L2 거리 계산**: 각 후보 청크와 질의 벡터 사이의 유클리드 거리(L2) 정밀 계산
3. **필터링**: L2 거리가 Threshold 이하인 청크만 선택 (낮을수록 유사)
4. **점수 변환**: L2 거리를 유사도 점수로 변환: `score = 1 / (1 + distance)`
5. **정렬 및 선택**: 변환된 점수 기준 내림차순 정렬 후 상위 Top-K개 반환

**파라미터**:
- `use_brute_force`: Flat Index 사용 여부 (boolean, 기본값: false)
- `brute_force_top_k`: 최종 반환 결과 수 (1-20, 기본값: 1)
- `brute_force_threshold`: 최대 L2 거리 임계값 (0.0-2.0, 기본값: 1.5)
  - 낮을수록 엄격 (예: 0.5 = 매우 유사한 것만 허용)
  - 높을수록 관대 (예: 2.0 = 넓은 범위 허용)

**UI 표시**:
- 검색 결과에 **Score**와 **L2 거리**를 모두 표시
- 예: `Score: 0.4449 (L2: 1.2475)`
- Score는 높을수록 유사, L2는 낮을수록 유사

**사용 사례**:
- 매우 정확한 벡터 매칭이 필요한 경우
- 초기 검색이 넓게 잡은 후보군 중 가장 정밀한 상위 1개만 선택하고 싶을 때
- L2 거리 임계값으로 명확한 유사도 기준을 적용하고 싶을 때

**참고**:
- Graph Search와 상호 배타적 (동시 사용 불가)
- 연산 비용이 높으므로 초기 후보 수를 적절히 제한하는 것이 좋음

### 3.8 Graph-Enhanced RAG (그래프 기반 검색)

**Graph-Enhanced RAG**는 문서로부터 자동으로 엔티티와 관계를 추출하여 그래프를 구축하고, 그래프 쿼리로 관련 엔티티를 탐색하는 고급 검색 기능입니다. 사용자는 두 가지 그래프 백엔드 중 하나를 선택할 수 있습니다:

#### 3.8.1 그래프 백엔드 옵션

**옵션 1: Using Ontology (Jena+Fuseki) - Beta**
- **설명**: RDF 기반 온톨로지를 구축하여 의미적 추론과 SPARQL 쿼리를 지원합니다. 향후 OWL/RDFS 온톨로지 스키마 기능이 추가될 예정입니다.
- **기술**: Apache Jena Fuseki, RDF, SPARQL
- **용도**: 온톨로지 기반 검색, 의미적 관계 추론

**옵션 2: Using Knowledge Graph (Neo4j)**
- **설명**: 속성 그래프(Property Graph) 기반 지식 그래프를 구축하여 Cypher 쿼리를 지원합니다.
- **기술**: Neo4j Graph Database, Cypher
- **용도**: 네이티브 그래프 검색, 고성능 관계 탐색

**중요**: 두 옵션은 **상호 배타적**입니다. Knowledge Base 생성 시 하나만 선택하거나, 둘 다 선택하지 않을 수 있습니다.

#### 3.8.2 공통 동작 방식

**1. 그래프 구축 (인덱싱 단계)**:
   - 문서 업로드 시 각 청크에서 엔티티와 관계 추출
   - 이중 추출 방식:
     - **LLM 기반** (GPT-4o-mini): 텍스트에서 Subject-Predicate-Object 트리플 추출
     - **spaCy NER**: 한국어 개체명 인식 및 조사 제거
   - 백엔드별로 저장:
     - **Fuseki**: RDF N-Triples 형식으로 저장
     - **Neo4j**: Cypher CREATE 문으로 노드와 관계 저장

**2. 검색 단계**:
   - **의미 기반 쿼리 분석** (LLM 활용):
     - Multi-hop 관계 쿼리 자동 감지 (예: "A의 B의 C")
     - 관계 타입 추출 (master, student, 스승, 제자 등)
   - 사용자 쿼리에서 엔티티 추출 (LLM + spaCy)
   - **엔티티 자동 확장**: 추출된 엔티티와 연결된 관련 엔티티 탐색
   - 그래프 탐색 (1-5 hops, 기본값 2):
     - **Fuseki**: SPARQL 쿼리 실행
     - **Neo4j**: Cypher 쿼리 실행
   - **스코어 부스팅**: 그래프 발견 청크에 1.5x 가중치 적용
   - **Hybrid 통합 및 Fallback**: 그래프 + BM25/Vector 병합

**3. 메타데이터 표시**:
   - 추출/확장된 엔티티
   - 실행된 쿼리 (SPARQL 또는 Cypher)
   - 발견된 트리플 또는 관계
   - 쿼리 분석 결과

#### 3.8.3 Fuseki 백엔드 상세 사양

**그래프 포맷**: RDF (N-Triples)

**RDF 트리플 구조 예시**:
```turtle
<http://rag.local/entity/Elon_Musk> <http://rag.local/relation/is_CEO_of> <http://rag.local/entity/SpaceX> .
<http://rag.local/entity/Elon_Musk> <http://rag.local/relation/hasSource> <http://rag.local/source/chunk_123> .
```

**네임스페이스**:
- 엔티티: `http://rag.local/entity/`
- 관계: `http://rag.local/relation/`
- 소스: `http://rag.local/source/`

**기술 스택**:
- **그래프 데이터베이스**: Apache Jena Fuseki (TDB2 스토어)
- **쿼리 언어**: SPARQL 1.1
- **Python 라이브러리**: SPARQLWrapper

#### 3.8.4 Neo4j 백엔드 상세 사양

**그래프 포맷**: 속성 그래프 (Property Graph)

**노드 및 관계 구조 예시**:
```cypher
CREATE (e:Entity {name: 'Elon Musk', type: 'PERSON'})
CREATE (c:Entity {name: 'SpaceX', type: 'ORG'})
CREATE (e)-[:IS_CEO_OF]->(c)
CREATE (e)-[:HAS_SOURCE {chunk_id: 'chunk_123'}]->(s:Source {id: 'chunk_123'})
```

**기술 스택**:
- **그래프 데이터베이스**: Neo4j
- **쿼리 언어**: Cypher
- **Python 라이브러리**: neo4j (공식 Python 드라이버)

#### 3.8.5 파라미터

- `graph_backend`: KB 생성 시 선택 (enum: "none", "ontology", "neo4j", 기본: "none")
- `enable_graph_search`: 검색 시 사용 (boolean, 기본: false)
- `graph_hops`: 탐색 깊이 (1-5, 기본: 2)
- `use_relation_filter`: (Neo4j 전용) 관계 키워드 필터링 사용 여부 (boolean, 기본: true). True일 경우 관계 키워드(예: "스승", "제자")를 포함하여 더 정밀한 검색, False일 경우 관계 검색 없이 엔티티 연결성만으로 더 넓은 검색 수행.

#### 3.8.6 사용 사례

- 질문: "일론 머스크가 CEO인 회사는?"
- 추출 엔티티: ["일론 머스크", "CEO"]
- 그래프 탐색으로 "일론 머스크" → "is_CEO_of" → "SpaceX" 관계 발견
- 해당 관계의 소스 청크 반환

**장점**:
- 단순 키워드 매칭을 넘어 관계 기반 검색 가능
- 메타데이터로 검색 과정 투명성 제공
- 강력한 그래프 쿼리 언어 활용 (SPARQL/Cypher)

**제한사항**:
- Beta 기능으로 성능 최적화 진행 중
- 대량 문서에서는 그래프 구축 시간 소요
- Flat Index (L2)와 동시 사용 불가

### 3.9 검색 테스트 (Retrieval Testing)
-   **플레이그라운드**: 특정 지식 베이스에 대해 검색 쿼리를 테스트할 수 있는 UI.
-   **디버그 정보**: 검색된 청크, 유사도 점수, 메타데이터 표시.

### 3.8 API 통합
-   **외부 API**: 외부 애플리케이션에서 지식 베이스를 조회할 수 있는 엔드포인트 제공.

## 4. API 설계 (FastAPI)

### 지식 베이스 (Knowledge Base)
-   `POST /api/knowledge-bases`: 지식 베이스 생성.
-   `GET /api/knowledge-bases`: 지식 베이스 목록 조회.
-   `GET /api/knowledge-bases/{kb_id}`: 특정 지식 베이스 상세 정보 조회.
-   `DELETE /api/knowledge-bases/{kb_id}`: 지식 베이스 삭제.

### 문서 (Documents)
-   `POST /api/knowledge-bases/{kb_id}/documents`: 문서 업로드 및 인덱싱.
-   `GET /api/knowledge-bases/{kb_id}/documents`: 지식 베이스 내 문서 목록 조회.
-   `DELETE /api/knowledge-bases/{kb_id}/documents/{doc_id}`: 문서 삭제.
-   `GET /api/knowledge-bases/{kb_id}/documents/{doc_id}/chunks`: 문서의 청크 목록 조회.

### 검색 (Retrieval)
-   `POST /api/knowledge-bases/{kb_id}/retrieve`: 관련 청크 검색.
    -   Body: 
        ```json
        { 
          "query": "...", 
          "top_k": 5, 
          "score_threshold": 0.5, 
          "strategy": "ann" | "keyword" | "2-stage" | "hybrid",
          "enable_graph_search": false,
          "graph_hops": 1,
          "use_relation_filter": true
        }
        ```
    -   Response: 
        ```json
        [{ 
          "chunk_id": "...", 
          "content": "...", 
          "score": 0.87, 
          "metadata": {...},
          "graph_metadata": {
            "sparql_query": "...",
            "extracted_entities": [...],
            "triples": [...]
          }
        }]
        ```

## 5. 데이터베이스 스키마

### 5.1 관계형 DB (Metadata)
**테이블: knowledge_bases**
-   `id`: UUID (Primary Key)
-   `name`: String
-   `description`: String
-   `graph_backend`: String (Graph 백엔드 타입: "none", "ontology", "neo4j", 기본값: "none")
-   `created_at`: Timestamp
-   `updated_at`: Timestamp

**테이블: documents**
-   `id`: UUID (Primary Key)
-   `kb_id`: UUID (Foreign Key)
-   `filename`: String
-   `file_type`: String (pdf, txt, md)
-   `status`: Enum (pending, processing, completed, error)
-   `created_at`: Timestamp

### 5.2 Milvus (Vector Data)
**컬렉션: knowledge_base_{kb_id}** (또는 파티션 키를 사용한 단일 컬렉션)
-   `id`: Int64 (Primary Key)
-   `doc_id`: String (Metadata)
-   `chunk_id`: String (Metadata)
-   `content`: String (실제 텍스트 청크)
-   `vector`: FloatVector (임베딩)

### 5.3 그래프 데이터 저장소

각 Knowledge Base는 `graph_backend` 설정에 따라 다른 그래프 DB를 사용합니다.

#### 5.3.1 Jena Fuseki (Ontology Backend)

**데이터셋**: `kb_{kb_id}` (각 Knowledge Base마다 별도 데이터셋)

**RDF 트리플 구조**:
1. **엔티티 정의**:
   ```turtle
   <http://rag.local/entity/Elon_Musk> rdf:type <http://rag.local/type/PERSON> .
   <http://rag.local/entity/Elon_Musk> rdfs:label "Elon Musk" .
   ```

2. **관계 트리플**:
   ```turtle
   <http://rag.local/entity/Elon_Musk> <http://rag.local/relation/is_CEO_of> <http://rag.local/entity/SpaceX> .
   ```

3. **소스 링크 (Provenance)**:
   ```turtle
   <http://rag.local/entity/Elon_Musk> <http://rag.local/relation/hasSource> <http://rag.local/source/chunk_abc123> .
   ```

**주요 네임스페이스**:
-   **엔티티**: `http://rag.local/entity/` - 추출된 엔티티 (인명, 조직, 개념 등)
-   **관계**: `http://rag.local/relation/` - 엔티티 간 관계 및 속성
-   **소스**: `http://rag.local/source/` - 청크 ID로 출처 추적
-   **타입**: `http://rag.local/type/` - 엔티티 타입 (PERSON, ORG, GPE 등)

**SPARQL 엔드포인트**: `http://fuseki:3030/kb_{kb_id}/query`

#### 5.3.2 Neo4j (Knowledge Graph Backend)

**데이터베이스**: 각 Knowledge Base마다 별도 라벨 또는 데이터베이스 사용

**노드 및 관계 구조**:
1. **엔티티 노드**:
   ```cypher
   CREATE (e:Entity:KB_{kb_id} {
     name: 'Elon Musk',
     type: 'PERSON',
     normalized: 'elon_musk'
   })
   ```

2. **관계**:
   ```cypher
   CREATE (e1:Entity)-[:IS_CEO_OF]->(e2:Entity)
   ```

3. **소스 링크**:
   ```cypher
   CREATE (e:Entity)-[:HAS_SOURCE {chunk_id: 'chunk_abc123'}]->(s:Source {id: 'chunk_abc123'})
   ```

**Cypher 엔드포인트**: Neo4j Bolt 프로토콜 (`bolt://neo4j:7687`)

## 6. UI/UX (React)

### 6.1 대시보드 (Home)
-   **헤더**: "RAG Management System"
-   **메인 영역**: 지식 베이스 그리드/리스트 뷰.
-   **액션**: "지식 베이스 만들기" 버튼 (모달 열기).

### 6.2 지식 베이스 상세 (Knowledge Base Detail)
-   **사이드바**: 네비게이션 (문서, 설정, 테스트).
-   **문서 탭**:
    -   "문서 추가" 버튼 (Drag & Drop 영역).
    -   문서 테이블 (이름, 상태, 날짜, 작업).
-   **설정 탭**:
    -   이름, 설명 입력 필드.
    -   Top K, Score Threshold 슬라이더.
-   **테스트 탭**:
    -   쿼리 입력을 위한 채팅 스타일 인터페이스.
    -   결과 표시 (텍스트 청크 + 점수).

## 7. 구현 계획
1.  **설정**: React 및 FastAPI 프로젝트 초기화.
2.  **백엔드 코어**: 데이터베이스 (SQLite) 및 Milvus 연결 설정.
3.  **API 구현**: 지식 베이스 및 문서 CRUD 구현.
4.  **수집 파이프라인**: 파일 파싱, 청킹, 임베딩 로직 구현.
5.  **프론트엔드**: 대시보드 및 상세 화면 구축.
6.  **통합**: 프론트엔드와 백엔드 API 연동.
