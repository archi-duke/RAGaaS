# 그래프 검색 쿼리 생성 개선 설계: Inner/Outer Loop 도입

> 상태: 구현·테스트 완료 (Implemented & Tested, 2026-07-16) — 구현 결정 사항 및 구현 중 개정 내역은 §9 참조
> 관련 문서: `docs/guide-cypher-generation.md` (Cypher Vibe Coding 프롬프트 가이드)

---

## 1. 배경 및 문제 정의

현재 그래프 검색(Graph RAG)은 두 백엔드(Neo4j / Fuseki)에서 공통적으로 **Fast Path 템플릿 우선 + LLM 폴백**의 하이브리드 구조를 취한다.

- `backend/app/services/retrieval/graph_backends/neo4j.py`의 `Neo4jBackend.query()` (11-458행)와
- `backend/app/services/retrieval/graph_backends/fuseki.py`의 `FusekiBackend.query()` (328-1065행)

모두 (1) 질문에서 엔티티를 추출해 결정적 템플릿 쿼리(Fast Path, Pattern 1/2/3)를 먼저 실행하고, (2) Fast Path가 실패하거나 관련성 체크(Relevance Check)를 통과하지 못하면 `CypherGenerator`(`backend/app/services/retrieval/cypher_generator.py`) 또는 `SPARQLGenerator`(`backend/app/services/retrieval/sparql_generator.py`)를 통해 LLM이 쿼리를 생성하도록 폴백한다.

이 하이브리드 구조 자체는 안정적이지만, **LLM 생성 쿼리 경로**에는 다음과 같은 구조적 문제가 있다.

### 1.1 생성된 쿼리를 검증·재시도 없이 그대로 실행

- Neo4j: `neo4j.py` 399행 `records = neo4j_client.execute_query(cypher_query, {"kb_id": kb_id})` — 생성된 Cypher가 문법 오류거나 존재하지 않는 관계 타입을 참조해도 예외 또는 0건 결과를 그대로 반환한다. 422-430행에서 `inv_mode == "none"`이고 결과가 0건이면 즉시 빈 배열을 반환할 뿐, 재생성 시도는 없다.
- Fuseki: `fuseki.py` 846행 `results = fuseki_client.query_sparql(kb_id, full_query)` — 마찬가지로 결과가 0건이면(858행 `if bindings:` 분기의 else, 1033-1045행) 그대로 실패로 처리된다.
- 더 심각한 것은, `graph.py`의 `GraphRetrievalStrategy.search()`에서 **폴백 검색(하이브리드 벡터/키워드 검색)이 "Strict Mode"로 완전히 비활성화**되어 있다는 점이다. 161-169행:

  ```python
  if not results or (len(results) == 1 and results[0].get("chunk_id") == "GRAPH_METADATA_ONLY"):
       # [MODIFIED] Fallback Removed as per user request
       # ...
       log(f"DEBUG: Strict Mode - Fallback search disabled. Returning empty/metadata-only results.")
  ```

  즉 LLM이 생성한 Cypher/SPARQL이 잘못되어 0건이 나오면, 재시도도 없고 대체 검색도 없이 **곧바로 빈 답변**으로 이어진다.

### 1.2 Fuseki의 문자열 f-string 직접 삽입 — SPARQL 인젝션 위험

`fuseki.py`는 사용자 질문에서 추출한 엔티티 텍스트를 이스케이프 없이 f-string으로 SPARQL 쿼리 문자열에 직접 삽입한다. 대표 위치:

- `_resolve_entity_to_uri()` (58-111행): 76행 `FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{entity_text}")))`, 94행 `FILTER(CONTAINS(LCASE(STR(?uri)), LCASE("{entity_text}")))`
- `query()` 내 Fast Path 쿼리들 (464-683행 구간):
  - Pattern 1 양방향 쿼리 (464-494행): 473행 `LCASE("{entity_name}")` (incoming), 481행 `LCASE("{entity_name}")` (outgoing)
  - Pattern 3 양방향 쿼리 (535-565행): 544행, 552행 — 동일하게 `entity_name`을 직접 삽입
  - Pattern 2 두 엔티티 간 관계 쿼리 (609-642행): 619-620행, 630-631행에서 `entity1_name`, `entity2_name`을 직접 삽입

`entity_name`/`entity_text`는 사용자 질문에서 정규식·조사 제거 휴리스틱으로 뽑아낸 토큰이므로(예: `fuseki.py` 404-420행의 조사 제거 로직), 질문에 큰따옴표(`"`)가 포함되면 SPARQL 문자열 리터럴을 조기 종료시켜 FILTER 조건을 임의로 변형할 수 있다. 실제 악용 난이도는 낮지 않지만(질문 텍스트 경유), 코드 리뷰 관점에서 명백한 미이스케이프 삽입 지점이다.

참고로 **Neo4j Fast Path는 이미 파라미터 바인딩**을 사용해 안전하다. 예: `neo4j.py` 134-137행 `neo4j_client.execute_query(cypher_query, {"kb_id": kb_id, "entity_name": entity_name})` — Cypher 쿼리문 자체는 `$entity_name`을 사용하고(109행 등), 값은 별도 파라미터로 전달된다. 단, Neo4j **LLM 폴백 경로**는 LLM이 생성한 Cypher 텍스트 안에 엔티티 값이 리터럴로 직접 포함되는 구조라(예: `MATCH (n:Entity {name: "성기훈"})`) 완전한 파라미터화는 아니다. 다만 이는 사용자 입력을 우리 코드가 직접 문자열 결합하는 것이 아니라 LLM이 판단해 생성한 텍스트라는 점에서 Fuseki의 직접 f-string 삽입과는 위험 프로파일이 다르다. 이번 설계에서는 **Fuseki의 직접 삽입만 수정 범위**로 하고, Neo4j LLM 폴백의 리터럴 임베딩은 범위 밖으로 남겨둔다(향후 검토 대상).

### 1.3 기본값 불일치 — `use_dynamic_schema`

동적 스키마 주입(라이브 그래프의 관계 타입/라벨을 프롬프트에 포함시키는 기능) 기본값이 계층마다 다르다.

| 위치 | 기본값 | 비고 |
|---|---|---|
| `sparql_generator.py` 293행 `use_dynamic_schema: bool = True` | True | 생성기 자체 기본값 |
| `cypher_generator.py` 110행 `use_dynamic_schema: bool = False` | False | 생성기 자체 기본값 |
| `neo4j.py` 347행 `dynamic_schema_enabled = kwargs.get("use_dynamic_schema", False)` | False | 백엔드가 kwargs에서 못 찾으면 False |
| `fuseki.py` 378행 `dynamic_schema_enabled = kwargs.get("use_dynamic_schema", False)` | False | 백엔드가 kwargs에서 못 찾으면 False |
| `pipeline_executor.py` 270행 `use_dynamic_schema = params.get("use_dynamic_schema", True)` | True | 파이프라인 경유 시 명시적으로 True를 백엔드에 전달 (296행) |
| `app/api/retrieval.py` 133행 `use_dynamic_schema: bool = False` | False | 비-파이프라인 Chat API 요청 모델 기본값 |

즉 파이프라인 실행(`pipeline_executor._execute_graph`)을 거치면 `use_dynamic_schema=True`가 명시적으로 전달되어 문제없지만, **파이프라인을 거치지 않는 경로**(예: `ChatRequest.pipeline`이 없는 단순 `strategy="hybrid"` 호출)에서는 API 기본값(False) → kwargs에 키 자체가 안 실림 → 백엔드 내부 기본값(False)로 이어져 Neo4j LLM 폴백이 라이브 스키마를 전혀 받지 못한 채 쿼리를 생성하게 된다. Fuseki도 동일한 구조적 위험이 있으나(378행), 브리프에서 지정한 수정 대상은 Neo4j(347행)이다 — Fuseki 쪽 정합성은 4.3에서 함께 언급한다.

### 1.4 정적 few-shot만 사용, 성공 사례 재활용 없음

`cypher_generator.py`와 `sparql_generator.py`는 각각 `data/prompts/cypher_vibe_prompt.txt`, `data/prompts/sparql_vibe_prompt.txt`라는 **고정 파일**을 시스템 프롬프트로 읽어들일 뿐(120-128행, 308-317행), 특정 KB에서 과거에 성공했던 질문-쿼리 쌍을 예시로 재사용하는 메커니즘이 없다. 매 요청이 스키마 지식 없이 "0에서부터" 생성을 시도하는 것과 같다.

---

## 2. 목표 및 비목표

### 목표

1. **Inner Loop** — 쿼리 생성 → 실행 → 실패 시 에러를 되먹임해 재생성하는 런타임 재시도 루프 도입 (최대 2회)
2. **보안 수정** — Fuseki의 SPARQL 문자열 리터럴 이스케이프 적용
3. **기본값 통일** — `neo4j.py:347`의 `use_dynamic_schema` 기본값을 `True`로 변경
4. **Level 1: 관측성** — 모든 생성 시도(성공/실패 무관)를 MongoDB에 로깅
5. **Level 2: 예시 메모리** — 성공한 질문-쿼리 쌍을 Milvus에 저장하고, 유사 질문 발생 시 동적 few-shot으로 프롬프트에 주입

### 비목표 (Out of scope — 향후 Level 3)

- 실패 로그를 분석해 프롬프트 자체를 자동으로 개정하는 것
- LLM 판사(judge)를 이용한 배치 품질 분석
- 골든 셋 기반 자동 평가 게이트 및 승격 파이프라인
- 온톨로지 리즈너(reasoner) 도입을 통한 스키마 정합성의 사전 검증

---

## 3. 전체 아키텍처

```
[Inner Loop — 런타임, 요청당 즉시 실행]

  질문
    │
    ▼
  (ExampleMemory에서 동적 few-shot 조회·주입)  ← Level 2
    │
    ▼
  쿼리 생성 (CypherGenerator / SPARQLGenerator)
    │
    ▼
  실행 (neo4j_client.execute_query / fuseki_client.query_sparql)
    │
    ├─ 성공(1건 이상) ──────────────► 결과 반환 + AttemptLogger 기록(성공)
    │
    └─ 실패(예외 또는 0건)
          │
          ▼
     에러 메시지 + 실패 쿼리 원문 + 라이브 스키마를 프롬프트에 추가
          │
          ▼
     재생성 (최대 2회, QueryGenerationLoop.max_retries)
          │
          └── 재시도 소진 시 최종 실패 반환 + AttemptLogger 기록(실패, 각 시도별)


[Outer Loop — 비동기/자동 축적, 요청 간 지식 이전]

  Inner Loop의 모든 시도
    │
    ├─► Mongo `query_gen_logs`  (전 시도 기록: 성공/실패 무관, Level 1)
    │
    └─► 성공한 시도만
           │
           ▼
        관련성/결과 수 조건 통과 시
           │
           ▼
        Milvus `query_gen_examples`  (질문 임베딩 + 쿼리 텍스트 저장, Level 2)
           │
           ▼
        다음 유사 질문의 Inner Loop 진입 시 few-shot으로 재사용
```

Inner Loop는 **LLM 폴백 경로에만 적용**된다. Fast Path(결정적 템플릿, `neo4j.py` 85-322행 / `fuseki.py` 396-797행)는 이미 확정적 쿼리라 재시도 대상이 아니다. Inner Loop가 개입하는 지점은 정확히:

- Neo4j: `neo4j.py` 325-443행("[FALLBACK] Use LLM-based CypherGenerator" ~ 반환문)의 `generator.generate(...)` 호출(370-377행)과 `neo4j_client.execute_query(...)` 호출(399행)
- Fuseki: `fuseki.py` 725-846행의 `active_generator.generate(...)` 호출(728-737행)과 `fuseki_client.query_sparql(kb_id, full_query)` 호출(846행)

---

## 4. 컴포넌트 설계

### 4.1 QueryGenerationLoop (신규, `backend/app/services/retrieval/query_gen_loop.py`)

두 백엔드에서 공통으로 쓸 수 있는 얇은 래퍼 클래스. 백엔드별 `generate_fn`(질문+컨텍스트 → 쿼리 텍스트)과 `execute_fn`(쿼리 텍스트 → 결과 레코드)을 주입받아 실행한다.

```python
class QueryGenerationLoop:
    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries

    async def run(self, question, generate_fn, execute_fn, ...) -> dict:
        """
        generate_fn(question, retry_context) -> {"query": str, "raw": dict}
        execute_fn(query) -> {"records": [...], "count": int} 혹은 예외 발생

        반환: {"query": str, "results": [...], "attempts": [AttemptLog, ...], "succeeded": bool}
        """
```

- 1차 생성 → 실행. 예외 발생 또는 결과 0건이면 실패로 간주.
- 실패 시 `retry_context`(직전 실패 쿼리 원문, DB 에러 메시지 또는 `"0 results"` 문자열, 가능하면 라이브 스키마)를 다음 `generate_fn` 호출에 전달해 재생성. **"수정된 쿼리만 출력하라"**는 지시를 재시도 프롬프트에 명시적으로 포함.
- 최대 `max_retries`(기본 2)회까지 반복. 소진 시 마지막 시도 결과를 실패로 반환.
- 매 시도마다 `AttemptLog`(4.4의 스키마와 1:1 대응)를 리스트에 축적.

**구현 시 고려사항 (확인 필요)**:
- `CypherGenerator.generate()`와 `SPARQLGenerator.generate()`는 이미 `custom_prompt` 파라미터를 받아 시스템 프롬프트에 append한다(`cypher_generator.py` 162-164행, `sparql_generator.py` 337-342행). 이 기존 파라미터를 재시도 지침 주입 통로로 재사용할 수 있다. 다만 `custom_prompt`는 현재 사용자가 KB 설정에서 지정한 커스텀 지침(`custom_query_prompt` kwargs)에도 이미 쓰이고 있으므로, 두 용도가 충돌하지 않도록 재시도 지침은 별도 섹션으로 이어붙이는 방식을 권장한다(예: `f"{user_custom_prompt}\n\n{retry_feedback}"`).
- Fuseki의 `query()`는 Fast Path·관련성 체크·LLM 생성·후처리(프리픽스 제거, UnionGraph 주입, 결과 파싱)가 700행 넘게 하나의 메서드에 섞여 있다(328-1065행). Inner Loop를 깔끔하게 적용하려면 "LLM 생성 + 실행" 구간(대략 725-856행)을 별도 헬퍼 함수로 분리하는 리팩터링이 선행되어야 한다. 이는 본 설계 문서의 범위이나, 실제 구현 시 나머지 로직(Fast Path, 트리플 추출, reification 조회)과의 상호작용을 재확인해야 한다.

### 4.2 SPARQL 이스케이프 (`fuseki.py` 수정)

`_escape_sparql_string(s: str) -> str` 유틸을 추가한다. 큰따옴표(`"`), 백슬래시(`\`), 개행(`\n`, `\r`)을 이스케이프한다(SPARQL 1.1 문자열 리터럴 이스케이프 규칙).

```python
def _escape_sparql_string(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r")
    return s
```

**참고**: `graph.py`의 `_expand_entities()` 396-401행에 있는 `sparql_escape()`는 이것과 **목적이 다르다** — 그것은 `regex(?label, "(패턴)", "i")` FILTER에 넣을 정규식 메타문자(`.*+?^${}()|[]\`)를 이스케이프하는 함수이지, 문자열 리터럴 구분자(따옴표)를 이스케이프하는 함수가 아니다. 따라서 단순히 재사용할 수 없고, 두 함수를 별도 유틸 모듈(예: `backend/app/services/retrieval/sparql_utils.py`)에 `escape_sparql_literal()`(신규, 리터럴용)과 `escape_sparql_regex()`(기존 로직 이동, 정규식용) 두 함수로 나란히 정의해 공통화하는 것을 권장한다. `graph.py` 396-401행은 이 신규 모듈의 `escape_sparql_regex`를 import해 대체할 수 있다.

적용 대상(모두 `fuseki.py`, `{entity_text}` / `{entity_name}` / `{entity1_name}` / `{entity2_name}` 삽입부):

| 위치 | 함수/블록 | 삽입 변수 |
|---|---|---|
| 76행 | `_resolve_entity_to_uri` label_query | `entity_text` |
| 94행 | `_resolve_entity_to_uri` uri_query | `entity_text` |
| 473행 | Pattern 1 bidirectional_query (incoming) | `entity_name` |
| 481행 | Pattern 1 bidirectional_query (outgoing) | `entity_name` |
| 544행 | Pattern 3 bidirectional_query (outgoing) | `entity_name` |
| 552행 | Pattern 3 bidirectional_query (incoming) | `entity_name` |
| 619-620행 | Pattern 2 direct_triple_query (entity1→entity2) | `entity1_name`, `entity2_name` |
| 630-631행 | Pattern 2 direct_triple_query (entity2→entity1) | `entity1_name`, `entity2_name` |

각 위치에서 `LCASE("{entity_name}")` → `LCASE("{_escape_sparql_string(entity_name)}")` 형태로 치환한다.

### 4.3 기본값 통일

- `neo4j.py` 347행: `kwargs.get("use_dynamic_schema", False)` → `kwargs.get("use_dynamic_schema", True)`
- (연계 검토, 브리프 범위 외이나 함께 확인 권장) `fuseki.py` 378행도 동일한 구조적 문제를 가지고 있음(`kwargs.get("use_dynamic_schema", False)`). 이번 설계의 필수 변경 대상은 아니지만, 파이프라인을 거치지 않는 호출 경로(`app/api/retrieval.py` 133행 `ChatRequest.use_dynamic_schema: bool = False`)까지 감안하면 Fuseki도 함께 True로 맞추는 것이 정합적이다. 구현 시 결정.

### 4.4 AttemptLogger (신규) — Mongo 컬렉션 `query_gen_logs`

Inner Loop의 모든 시도(성공/실패 무관)를 기록해 Level 1 관측성을 확보한다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `kb_id` | str | 대상 지식베이스 ID |
| `backend` | `"neo4j"` \| `"fuseki"` | 그래프 백엔드 |
| `question` | str | 원본 질문 |
| `generated_query` | str | 생성된 Cypher/SPARQL |
| `attempt_no` | int | 1부터 시작, 재시도 순번 |
| `error` | str \| null | 실행 예외 메시지 (없으면 null) |
| `result_count` | int | 실행 결과 레코드 수 |
| `elapsed_ms` | int | 생성+실행 소요 시간 |
| `model` | str | 사용된 LLM 모델명 |
| `few_shot_used` | list[str] | 이번 시도에 주입된 ExampleMemory 항목 ID들 |
| `succeeded` | bool | 최종 성공 여부 (attempt_no 기준 해당 시도의 성공 여부) |
| `created_at` | datetime | 기록 시각 |

**DB 접속 방식**: 앱은 Beanie ODM을 사용하며, `backend/app/core/database.py` 12-26행에서 `init_beanie(database=client[settings.MONGO_DB], document_models=[KnowledgeBase, PromptTemplate, Document, CustomProvider, BuiltinProviderConfig])`로 문서 모델을 명시적으로 등록한다. `AttemptLogger`는 단순 insert-only 로거이므로 두 가지 구현 방식이 가능하다.

1. **Motor 직접 사용** (권장): `database.py`에 이미 전역으로 유지되는 `client: AsyncIOMotorClient`를 import해 `client[settings.MONGO_DB]["query_gen_logs"].insert_one(...)`로 기록. Beanie `Document` 서브클래스 정의·`document_models` 리스트 수정이 불필요해 변경 범위가 작다.
2. **Beanie Document로 등록**: `app/models/`에 `QueryGenLog(Document)`를 신규 정의하고 `database.py`의 `document_models` 리스트에 추가. 스키마 검증과 인덱스 정의(예: `kb_id`, `created_at`에 대한 TTL/복합 인덱스)를 선언적으로 관리할 수 있는 대신 변경 범위가 넓어진다.

**구현 시 확인**: 위 두 방식 중 어느 쪽을 택할지는 로그 조회 UI(관리자 화면 등) 필요 여부와 인덱스 요구사항에 따라 결정한다. 본 설계에서는 방식만 제시하고 최종 선택은 구현 단계로 남긴다.

### 4.5 ExampleMemory (신규) — Milvus 컬렉션 `query_gen_examples`

| 필드 | 타입 |
|---|---|
| `id` | INT64, auto_id, primary |
| `kb_id` | VARCHAR |
| `backend` | VARCHAR (`neo4j`/`fuseki`) |
| `question` | VARCHAR |
| `question_vector` | FLOAT_VECTOR |
| `query_text` | VARCHAR |
| `created_at` | INT64 (unix timestamp) |
| `use_count` | INT64 |

컬렉션 생성 패턴은 `backend/app/core/milvus.py`의 `create_collection()`(11-68행)을 참고해 `FieldSchema`/`CollectionSchema`/`create_index` 흐름을 그대로 따르되, KB별로 나뉘는 기존 `kb_{kb_id}` 컬렉션과 달리 **여러 KB가 공유하는 단일 컬렉션**으로 두고 `kb_id` 스칼라 필드로 필터링하는 것을 기본안으로 한다(질문 예시 재사용은 KB 범위를 넘지 않게 `expr=f'kb_id == "{kb_id}"'`로 항상 제한).

**미해결 이슈 (구현 시 확인 필요)**: 기존 `milvus.py` 62행은 `FLOAT_VECTOR, dim=1536`을 `# Assuming OpenAI embedding dim` 주석과 함께 하드코딩하고 있다. KB마다 `embedding_provider`/`embedding_model`(참고: `backend/app/models/knowledge_base.py` 21-23행)이 달라 임베딩 차원이 다를 수 있는데, 단일 공유 컬렉션은 고정 차원 벡터 필드를 요구하므로 이 경우 컬렉션 분리(예: 차원별 컬렉션 또는 KB별 컬렉션)가 필요할 수 있다. 본 설계에서는 이 제약을 명시만 하고, 실제 배포 환경에서 사용 중인 임베딩 모델들의 차원이 통일되어 있는지 확인 후 방식을 확정한다.

**저장 조건(성공 정의)**:
- 실행 성공(예외 없음) AND `result_count >= 1`
- AND 관련성 체크 통과 — `neo4j.py` 274-310행 / `fuseki.py` 685-722행에 이미 존재하는 "질문 키워드가 predicate/object에 포함되는지" 확인하는 Relevance Check 로직을 재사용(현재는 Fast Path 결과에만 적용되고 있으나, 이 로직 자체를 함수로 추출해 LLM 생성 쿼리 결과에도 동일하게 적용)

**중복 제거**: 신규 질문 임베딩으로 동일 `kb_id` 범위 내 top-1 검색 후 코사인 유사도 ≥ 0.95면 신규 저장을 생략하고 기존 항목의 `use_count`만 증가시킨다. **구현 시 확인**: Milvus는 필드 단위 in-place 업데이트를 기본 지원하지 않는 버전이 많아(pymilvus 버전에 따라 `upsert` API 지원 여부 상이), `use_count` 증가는 (a) 해당 레코드를 delete 후 재insert하거나 (b) `use_count`/`created_at`처럼 자주 바뀌는 필드만 별도로 Mongo에 두고 Milvus는 벡터 검색 전용으로 쓰는 하이브리드 구조 중 택일이 필요하다.

**상한 및 퇴출**: KB당 200쌍 상한. 신규 저장 시 해당 `kb_id`의 레코드 수가 200을 넘으면 `use_count` 오름차순 → `created_at` 오름차순으로 정렬해 초과분을 삭제(`Collection.delete(expr=...)`).

**임베딩**: KB의 기존 임베딩 모델 설정을 그대로 재사용한다. `backend/app/services/embedding.py`의 `EmbeddingService.get_embeddings()`(61행)를 `graph.py`가 이미 `_fetch_chunks()`(511행)에서 하듯 동일한 패턴으로 호출한다.

### 4.6 동적 few-shot 주입

쿼리 생성 직전, `ExampleMemory`에서 해당 `kb_id`·`backend` 범위 내 질문 임베딩 top-3를 검색하고 유사도 ≥ 0.7인 것만 채택한다.

- **Cypher**: `cypher_generator.py`의 `generate()`에서 `user_content = f"사용자 질문: {question}"`(166행) 조립부를 확장해 `few_shot_examples: Optional[List[Dict]] = None` 파라미터를 추가하고, 존재 시 `"[참고 예시]\n질문: ...\nCypher: ...\n"` 형태의 섹션을 167-168행(컨텍스트 append) 다음에 이어붙인다.
- **SPARQL**: `sparql_generator.py`의 `_build_user_message()`(138-200행)가 이미 `entity_index`, `property_index` 등을 조립하는 구조이므로, 동일한 방식으로 `few_shot_examples` 파라미터를 추가해 176-184행의 `user_content` 조립부 뒤에 "[참고 예시]" 섹션을 추가한다. `generate()`(282-295행) 시그니처에도 `few_shot_examples` 파라미터를 추가해 353-360행 `_build_user_message(...)` 호출에 전달한다.

---

## 5. 안전장치

- **성공 정의 엄격화** (4.5): 단순 "예외 없음"이 아니라 결과 1건 이상 + 관련성 체크 통과를 성공 조건으로 삼아, Fast Path의 Relevance Check(`neo4j.py` 274-310행/`fuseki.py` 685-722행)와 동일한 엄격도를 LLM 생성 경로에도 적용한다. 이렇게 하지 않으면 무관한 쿼리가 예시로 축적되어 향후 few-shot 품질을 오염시킬 수 있다.
- **예시 메모리 오염 방지**: 중복 제거(dedupe, 유사도 ≥0.95 시 재사용)와 KB당 200쌍 상한으로 무한 누적을 막는다. 사용자가 답변에 "안 맞다"고 피드백할 수 있는 훅(예: 채팅 UI의 부정 피드백 버튼과 연동해 해당 예시를 즉시 강등/삭제)은 이번 범위에서는 자리만 마련하고 실제 연동은 하지 않는다.
- **재시도 무한루프 방지**: `QueryGenerationLoop.max_retries=2`로 총 3회(최초 1회 + 재시도 2회) 시도 후 종료. 백엔드 LLM 호출 자체도 이미 180초 타임아웃이 걸려 있으므로(`cypher_generator.py` 192행, `sparql_generator.py` 381행), 재시도를 포함한 전체 소요 시간이 과도해지지 않도록 Inner Loop 레벨에서 총 타임아웃(예: 120초)을 추가로 두는 것을 권장한다.
- **로깅 실패 격리**: `AttemptLogger.log(...)` 호출은 반드시 try/except로 감싸 Mongo 쓰기 실패가 검색 응답 자체를 막지 않도록 한다. `graph.py`의 기존 로깅 패턴(예: 242-243행, 273-274행에서 각 추출 단계를 개별 try/except로 감싸는 방식)과 일관되게 구현한다.

---

## 6. 변경 파일 목록

| 파일 | 변경 유형 | 변경 내용 요약 |
|---|---|---|
| `backend/app/services/retrieval/query_gen_loop.py` | 신규 | `QueryGenerationLoop`, `AttemptLog` — 생성→실행→에러 되먹임 재시도(최대 2회) |
| `backend/app/services/retrieval/query_gen_attempt_logger.py` | 신규 | `AttemptLogger` — Mongo `query_gen_logs` insert (motor 직접 또는 Beanie, 4.4 참고) |
| `backend/app/services/retrieval/query_gen_example_memory.py` | 신규 | `ExampleMemory` — Milvus `query_gen_examples` 저장/검색/dedupe/eviction |
| `backend/app/services/retrieval/sparql_utils.py` | 신규 | `escape_sparql_literal()`(문자열 리터럴 이스케이프), `escape_sparql_regex()`(기존 `graph.py` 396-401행 로직 이동) |
| `backend/app/services/retrieval/graph_backends/fuseki.py` | 수정 | 76·94·473·481·544·552·619-620·630-631행에 `escape_sparql_literal()` 적용; 725-846행 "LLM 생성+실행" 구간을 `QueryGenerationLoop` 연동 가능하도록 헬퍼로 분리; 378행 `use_dynamic_schema` 기본값 검토(선택) |
| `backend/app/services/retrieval/graph_backends/neo4j.py` | 수정 | 347행 `use_dynamic_schema` 기본값 `False`→`True`; 325-443행 LLM 폴백 구간을 `QueryGenerationLoop` 연동 |
| `backend/app/services/retrieval/cypher_generator.py` | 수정 | `generate()`에 `few_shot_examples` 파라미터 추가, 166-168행 user_content 조립부에 예시 섹션 추가 |
| `backend/app/services/retrieval/sparql_generator.py` | 수정 | `generate()`/`_build_user_message()`에 `few_shot_examples` 파라미터·섹션 추가 |
| `backend/app/services/retrieval/graph.py` | 수정 | 396-401행 `sparql_escape`를 `sparql_utils.escape_sparql_regex`로 교체(중복 제거) |
| `backend/app/core/milvus.py` | 수정(선택) | `query_gen_examples` 컬렉션 생성 헬퍼 추가 (기존 `create_collection()`과 별도 함수) |
| `backend/app/core/database.py` | 수정(선택, 4.4 방식 2 채택 시) | `document_models` 리스트에 `QueryGenLog` 추가 |

---

## 7. 테스트 계획

### 7.1 단위 테스트

- `sparql_utils.escape_sparql_literal()`: 큰따옴표/백슬래시/개행 포함 문자열이 올바르게 이스케이프되는지, 이스케이프 후 문자열을 SPARQL 리터럴에 삽입해도 FILTER 구조가 깨지지 않는지
- `QueryGenerationLoop`: (a) 첫 시도 성공 시 재시도 없이 종료, (b) 첫 시도 0건/예외 시 재시도 프롬프트에 에러 메시지가 포함되는지, (c) `max_retries` 소진 시 정확히 3회(1+2) 시도 후 실패 반환하는지
- `ExampleMemory` dedupe 로직: 유사도 ≥0.95인 질문 재입력 시 신규 insert가 발생하지 않고 `use_count`만 증가하는지(모킹 기반)

### 7.2 통합 테스트

컨테이너(`ragaas-backend`)에 변경 파일을 hot-patch(`docker cp`)한 뒤, 실제 KB `fff43d25-97fd-4932-aa2a-2b17a20b884b`("test ot", `graph_backend=ontology`)를 대상으로 다음 시나리오를 검증한다. **구현 시 확인**: 위 KB ID가 현재 환경에 실제 존재하는지, 그리고 promoted 여부(`is_promoted`)에 따라 정적 스키마 주입 경로가 달라질 수 있으므로 사전 확인 필요.

1. **정상 질문**: 기존과 동일하게 정상 응답이 나오는지 (회귀 확인)
2. **스키마에 없는 관계를 묻는 질문** (예: 존재하지 않는 predicate를 유도하는 질문): LLM이 잘못된 SPARQL을 생성하도록 유도하고, `query_gen_logs`에 attempt_no=1(실패, error 또는 result_count=0) → attempt_no=2(재시도) 로그가 기록되는지, 최종적으로 재시도가 결과를 개선하는지 또는 정직하게 실패로 끝나는지 확인
3. **따옴표 포함 엔티티 질문** (예: 질문 안에 `"` 문자를 포함): Fast Path 및 LLM 경로 모두에서 SPARQL 구조가 깨지지 않고 정상 실행되는지(인젝션 안전성 확인) — 이스케이프 적용 전/후 비교로 회귀 여부도 함께 확인

### 7.3 배포

현재 관행에 따라 `docker cp`로 변경 파일을 컨테이너에 복사 후 재시작하는 핫패치 방식을 사용한다. git 커밋은 이번 설계 문서 작성 범위에 포함하지 않으며, 별도 지시를 기다린다.

---

## 8. 향후 확장 (Level 3 스케치)

Level 1(전 시도 로깅)과 Level 2(성공 예시 메모리)가 안정화된 이후에는, `query_gen_logs`에 누적된 실패 사례를 주기적으로 배치 분석해 실패 패턴(예: 특정 관계 타입 혼동, 특정 질문 유형에서 반복 실패)을 추출하고, 이를 근거로 시스템 프롬프트(`data/prompts/cypher_vibe_prompt.txt`, `data/prompts/sparql_vibe_prompt.txt`)의 개정안을 LLM이 초안 작성하도록 하며, 개정안은 곧바로 반영하지 않고 사전에 구축한 골든 셋(질문-기대 쿼리/결과 쌍) 평가에서 기존 프롬프트 대비 유의미한 개선이 확인될 때만 승격(promote)하는 자동 평가 게이트를 두는 것을 고려할 수 있다.

---

## 9. 구현 결정 사항 (리뷰 확정)

본 문서의 "구현 시 확인" 항목에 대한 최종 결정:

| 항목 | 결정 | 근거 |
|---|---|---|
| 4.4 Mongo 로거 접속 방식 | **방식 1: motor 직접 사용** | insert-only 로거에 Beanie 등록은 과잉. `database.py`의 전역 `client` 재사용 |
| 4.5 Milvus 임베딩 차원 | **단일 컬렉션, dim=1536 고정** | 기존 `milvus.py:62`가 이미 모든 KB 컬렉션을 dim=1536으로 하드코딩 — 현 배포 환경과 동일 가정. 차원 다변화는 기존 컬렉션 포함 별도 과제 |
| 4.5 use_count 갱신 | **(b)안: Mongo+Milvus 하이브리드** | 예시 원본(question, query_text, use_count, created_at)은 Mongo `query_gen_examples` 컬렉션이 source of truth, Milvus는 `example_id`+벡터만 저장해 검색 전용. dedupe/eviction/카운트 갱신 모두 Mongo에서 처리 |
| 4.3 fuseki.py:378 기본값 | **True로 함께 변경** | neo4j.py:347만 고치면 백엔드 간 비대칭이 남음. 비파이프라인 경로 정합성 확보 |

### §9.1 구현 중 개정 (테스트 과정에서 확정)

| 항목 | 개정 내용 | 사유 |
|---|---|---|
| 4.5 ExampleMemory 저장소 | **Milvus 제거, Mongo 단일 저장 + 인메모리(numpy) 코사인 검색으로 전환** | 이 배포 환경의 Milvus 서버(192.168.219.115:44380)는 신규 컬렉션의 load/flush가 타임아웃됨(기존 `kb_*` 컬렉션은 정상). 첫 통합 시 `collection.load()` 행이 **이벤트 루프 전체를 동결**시키는 사고 발생. 예시 메모리는 KB당 ≤200행이라 Mongo 전수 코사인 비교로 충분하며, dim=1536 제약·이중 저장 정합성 문제도 함께 해소 |
| 4.5 저장 게이트 관련성 체크 | `_extract_relevance_keywords(query_text, [])` (엔티티 미제외) + `include_subject=True` 로 s/p/o 전체 매칭 | 엔티티 제외+p/o 매칭(Fast Path 의미론)을 저장 게이트에 그대로 쓰면 "성기훈은 누구랑 관계있어?"처럼 엔티티가 subject 로만 매칭되는 정답 쿼리가 저장에서 탈락. Fast Path 폴백 판정은 기본값(엔티티 제외, p/o만)으로 불변 |
| (범위 외 발견) `retrieval.py` `_write_model_to_kb_storage` | base_url/provider_id 는 새 선택에 값이 없으면 **명시적으로 None 으로 클리어** | 기존 코드는 None/"" 값을 skip 하여, 커스텀 프로바이더(z.ai)→빌트인(OpenAI) 전환 시 이전 base_url 이 잔존 → "gpt 모델을 z.ai 로 전송" 설정 오염이 반복 재발 (test ot, test n4 KB에서 실제 발생·데이터 수정 완료) |
| (교훈) 외부 I/O 격리 | 이벤트 루프에서 실행되는 블로킹 클라이언트 호출은 예외 격리만으로 부족 — **시간 격리(타임아웃/스레드 오프로딩)** 필수 | Milvus 동결 사고의 직접 교훈. Mongo(motor)는 진성 async 라 해당 없음 |
