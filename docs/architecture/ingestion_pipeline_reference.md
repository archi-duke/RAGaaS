# Ingestion Pipeline Architecture Reference

이 문서는 RAGaaS의 문서 인제스션(Ingestion) 파이프라인의 구조, 각 단계별 기능, 그리고 전/후 처리 로직을 상세히 기술합니다.
향후 작업 시 이 파이프라인 구조와 책임 분리 원칙을 준수해야 합니다.

---

## 🏗️ Pipeline Overview (파이프라인 개요)

문서가 업로드되어 Vector DB와 Graph DB에 적재되기까지의 전체 흐름입니다.
명확한 책임 분리(Separation of Concerns)를 위해 **정제(Cleaning)**, **추출(Extraction)**, **정규화(Normalization)**, **추론(Inference)** 단계가 분리되어 있습니다.

```mermaid
graph TD
    A[📄 Raw Document] --> B(Step 1: Text Extraction)
    B --> C{Enable Text Cleaning?}
    C -- Yes --> D[Step 2: Text Pre-processing\n(Remove #, Bullets, Whitespace)]
    C -- No --> E
    D --> E(Step 3: Chunking)
    E --> F(Step 4: Embedding Generation)
    F --> G{Enable Graph RAG?}
    G -- Yes --> H[Step 5: Graph Extraction\n(LLM / Schema)]
    G -- No --> L
    H --> I{Enable Entity Normalization?}
    I -- Yes --> J[Step 6: Entity Normalization\n(Canonical Form Conversion)]
    I -- No --> K
    J --> K[Triples Ready]
    K --> L(Step 7: Data Loading & ER)
    L --> M[Vector DB (Milvus)]
    L --> N[Graph DB (Neo4j/Fuseki)]
    N --> O{Enable Inference?}
    O -- Yes --> P[Step 8: Relation Inference\n(Rule-based Relation Creation)]
    O -- No --> Q[Done]
    P --> Q
```

---

## 🛠️ Step-by-Step Detail (단계별 상세)

### Step 1: Raw Text Extraction
*   **기능**: 업로드된 파일(PDF, TXT, MD)에서 원본 텍스트를 추출합니다.
*   **위치**: `ingest_service/app/api/ingest.py`
*   **비고**: PDF는 `pypdf`를 사용하여 텍스트만 추출합니다.

### Step 2: Text Pre-processing (Cleaning)
*   **기능**: 청킹 및 임베딩 품질을 저해하는 노이즈를 제거합니다. **(청킹 전 단계)**
*   **모듈**: `ingest_service/app/core/text_cleaner.py`
*   **작업 내용**:
    *   문단 번호 제거 (예: "1. 서론", "(a) 항목")
    *   불릿 포인트 기호 제거 (예: "•", "-", "*")
    *   과도한 공백 및 개행 문자 정규화
*   **제어 옵션**: `enable_text_cleaning` (Boolean)

### Step 3: Chunking
*   **기능**: 긴 텍스트를 LLM 처리에 적합한 크기로 분할합니다.
*   **모듈**: `ingest_service/app/core/pipeline.py` (LlamaIndex `SentenceSplitter`, `SemanticSplitter` 등)
*   **설정**: Chunk Size, Overlap, Strategy(Fixed, Semantic, etc.)

### Step 4: Embedding Generation
*   **기능**: 분할된 각 청크에 대한 벡터 임베딩을 생성합니다.
*   **모듈**: `ingest_service/app/core/pipeline.py` (OpenAI Embedding 등)

### Step 5: Graph Extraction
*   **기능**: 텍스트 청크에서 `(Subject)-[Predicate]->(Object)` 형태의 트리플을 추출합니다.
*   **모듈**: `ingest_service/app/core/pipeline.py`
*   **방식**:
    *   **Simple LLM**: 프롬프트 기반 자유 추출
    *   **Schema-based**: 정의된 온톨로지 스키마 기반 추출
    *   **Dynamic**: 동적 스키마 생성 및 추출

### Step 6: Entity Normalization (Phase 1)
*   **기능**: 추출된 트리플의 엔티티 이름을 표준형(Canonical Form)으로 변환합니다. **(적재 직전 단계)**
*   **모듈**: `ingest_service/app/core/entity_normalizer.py`
*   **작업 내용**:
    *   이름에 포함된 잔여 번호 제거 (예: "4. 성기훈" → "성기훈")
    *   따옴표, 괄호 제거 및 공백 정규화
    *   중복 트리플 제거
*   **시점**: 그래프 추출 후, DB 적재 전
*   **제어 옵션**: 내부 Config (`enable_entity_normalization`)

### Step 7: Data Loading & Entity Merging (Phase 2)
*   **기능**: 벡터 및 그래프 데이터를 데이터베이스에 저장합니다.
*   **모듈**: 
    *   `ingest_service/app/core/milvus_connector.py` (Vector)
    *   `ingest_service/app/core/neo4j_connector.py` (Graph)
*   **Entity Merging (ER)**:
    *   재 적재 시 Neo4j의 `MERGE` 구문을 활용하여 **중복 노드 생성을 방지**합니다.
    *   동일한 `name`과 `kb_id`를 가진 노드는 하나로 유지됩니다.

### Step 8: Relation Inference (Phase 3)
*   **기능**: 저장된 그래프 데이터를 바탕으로 새로운 관계를 추론하여 추가합니다. **(적재 후 단계)**
*   **모듈**: `ingest_service/app/core/inference_engine.py`
*   **방식**: 규칙(Rule) 기반 패턴 매칭
    *   예: `(A)-[스승]->(B)-[스승]->(C)`  ⟹  `(A)-[사조]->(C)`
*   **제어 옵션**: `enable_inference` (Boolean)

---

## 📂 Code Map (코드 맵)

| Role | File Path | Class / Function |
|------|-----------|------------------|
| **Entry Point** | `ingest_service/app/api/ingest.py` | `process_ingest_job` |
| **Orchestrator** | `ingest_service/app/core/pipeline.py` | `IngestPipeline.process` |
| **Cleaner** | `ingest_service/app/core/text_cleaner.py` | `TextCleaner` |
| **Clean Integration** | `ingest_service/app/core/pipeline.py` | (process 메서드 내부 Step 0) |
| **Chunks & Embed** | `ingest_service/app/core/pipeline.py` | `_get_splitter`, `embed_model` |
| **Graph Extract** | `ingest_service/app/core/pipeline.py` | `extract_graph` |
| **Normalizer** | `ingest_service/app/core/entity_normalizer.py` | `EntityNormalizer` |
| **Norm Integration** | `ingest_service/app/core/pipeline.py` | (process 메서드 내부 Step 4) |
| **Graph Loader** | `ingest_service/app/core/neo4j_connector.py` | `insert_triples` (MERGE 사용) |
| **Inference Engine** | `ingest_service/app/core/inference_engine.py` | `InferenceEngine` |
| **Infr Integration** | `ingest_service/app/api/ingest.py` | (적재 완료 후 호출) |

---

## 📝 Design Principles (설계 원칙)

1.  **청크 가공 vs ER 책임 분리**:
    *   **Text Cleaner**: 물리적인 텍스트 노이즈 제거 (Chunking 전)
    *   **Entity Resolution**: 의미적인 엔티티 통합 (Graph 추출 후/적재 시)
    
2.  **적재 시점 Merging**:
    *   그래프 DB 적재 시 항상 `MERGE`를 사용하여 데이터 중복을 방지한다.
    
3.  **사후 추론(Post-Inference)**:
    *   복잡한 관계 추론은 추출 단계가 아닌, 데이터가 온전히 적재된 후(Post-Load) 그래프 쿼리를 통해 수행한다.

---

## 🔧 Extensibility (확장 가이드)

*   **새로운 정제 규칙 추가**: `TextCleaner.clean()` 메서드에 정규식 추가.
*   **새로운 추론 규칙 추가**: `InferenceEngine.DEFAULT_RULES` 리스트에 `InferenceRule` 객체 추가.
    ```python
    InferenceRule(
        name="new_rule",
        pattern=["relation1", "relation2"],
        inferred_relation="new_inferred_relation"
    )
    ```
