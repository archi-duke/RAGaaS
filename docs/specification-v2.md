# RAGaaS 시스템 사양서 v2 (현행)

> **상태**: ✅ 현행 · **최종 검증**: 2026-07-15 (코드 전수 조사 기반)
> v1(초기 사양, SQLite/모놀리스 전제)은 [`_archive/specification-v1.md`](_archive/specification-v1.md) 로 아카이브됨.
> 배포·플랫폼 연계는 [`PLATFORM-INTEGRATION.md`](PLATFORM-INTEGRATION.md), 모델 설정·파이프라인 계약은
> [`architecture/model-config-and-pipeline-contract.md`](architecture/model-config-and-pipeline-contract.md) 참조.

## 1. 시스템 개요

RAGaaS는 다수의 지식 베이스(KB)를 생성·관리하고, 벡터 검색과 지식 그래프 검색을 **스테이지 기반 검색 파이프라인**으로 조합·실험할 수 있는 RAG 관리 플랫폼이다.

- **배포 형태**: NETRIX 플랫폼 셸(GoJIRA platform-app)의 **Module Federation remote 앱**. 게이트웨이(`:44300`) 경유로 `/ragaas/`(프론트), `/ragaas/api/`(백엔드) 라우팅.
- **인프라**: 자체 DB 컨테이너를 띄우지 않고 **shared-infra**(외부 호스트)의 Mongo/Milvus/Fuseki/Neo4j/Redis 를 참조.
- **독립 실행(dev)**: `npm run dev`(base `/`) + vite proxy 로도 동작.

## 2. 서비스 구성

| 서비스 | 기술 | 포트(내부) | 역할 |
|---|---|---|---|
| **backend** | FastAPI | 8000 (expose) | KB/문서/검색/프로바이더 API, WebSocket 진행률 |
| **ingest-service** | FastAPI + LlamaIndex | 8001 (expose) | 문서 인제스트 (청킹→임베딩→트리플 추출→저장), 비동기 잡 + 콜백 |
| **frontend** | React 19 + Vite + MF remote, nginx | 80 (expose) | UI. `/api/`→backend, `/ingest-api/`→ingest 를 nginx 프록시 |
| **samsung-ds-proxy** | FastAPI | 8010 | 사내 API Gateway용 OpenAI 호환 프록시 (`/v1/embeddings`, `/v1/chat/completions`) |

- 컨테이너는 `deploy/docker-compose.yml` (호스트 포트 미발행, `shared-net` 조인). 게이트웨이가 컨테이너명으로 라우팅.
- backend ↔ ingest-service 는 **HTTP + 콜백** (`POST /api/ingest` → 완료 시 `POST /api/knowledge-bases/ingest/callback`). 메시지 브로커 없음 — [ADR-002](adr/ADR-002-http-ingest-service.md).
- 원본 파일은 shared storage `/data/uploads/{kb_id}/` 를 두 서비스가 공유.

### shared-infra 접속 (deploy/.env, 미추적)

Mongo `:44370`(authSource=admin, DB=ragaas) · Redis `:44375` · Milvus `:44380` · Fuseki `:44390` · Neo4j `:44395/44396`.
`ENCRYPTION_KEY` 는 저장된 API 키 복호화용 — **환경 이전 시 기존 값 유지 필수**.

## 3. 기술 스택 (현행)

| 영역 | 스택 | 비고 |
|---|---|---|
| 메타데이터 | **MongoDB + Beanie ODM** (`beanie<2`, `motor<4` 핀) | v1의 SQLite 계획을 대체 — [ADR-003](adr/ADR-003-mongodb-metadata-store.md) |
| 벡터 | Milvus (`kb_{kb_id 하이픈→_}` 컬렉션) | dim 1536 |
| 그래프(온톨로지) | Apache Jena Fuseki TDB2, SPARQL | 문서별 named graph |
| 그래프(KG) | Neo4j + APOC, Cypher | |
| 인제스트 | LlamaIndex (Splitter/PathExtractor) | |
| 한국어 키워드 | Kiwi 형태소 분석 + BM25 | `backend/user_dic.txt` 사용자 사전 |
| LLM/임베딩 | **프로바이더 레지스트리** (builtin: openai/anthropic/google + custom 임의 OpenAI 호환) | API 키 Fernet 암호화 저장 |
| 프론트 | React 19, Vite, `@module-federation/vite`, Kendo UI | 셸과 react singleton 공유 |

## 4. 데이터 모델

### 4.1 MongoDB 컬렉션 (Beanie)

| 컬렉션 | 모델 | 핵심 필드 |
|---|---|---|
| `knowledge_bases` | KnowledgeBase | id(uuid), name, chunking_strategy/config, metric_type(COSINE), enable_graph_rag, graph_backend(`ontology`\|`neo4j`), is_promoted, promotion_metadata, sparql_prompt_template, **pipeline_config{stages:[]}**, embedding_provider/model/provider_id, **llm_model_config{}** |
| `documents` | Document | id(uuid), kb_id, filename, status(pending/processing/completed/error/deleting), pipeline_status, file_path, 추출 옵션들(extractor_type, enable_subject_restoration, enable_entity_normalization, normalization_*, max_sample_size, custom_prompt…), chunk/entity/triple_count |
| `custom_providers` | CustomProvider | provider_id(uuid), name, base_url, **encrypted_key**, model_list[], provider_type(llm/embedding/both), extra_headers{}, embedding_request_format(openai/minimal) |
| `builtin_provider_configs` | BuiltinProviderConfig | provider_id(openai/anthropic/google), **encrypted_key**, cached_models_llm/embedding[], cached_at |
| `prompts` | PromptTemplate | name, content, version, type |

암호화: `cryptography.Fernet`(`ENCRYPTION_KEY`). 키 미설정 시 프로세스마다 임시 키 생성 → 재시작 후 복호화 불가(경고 로그).

### 4.2 Milvus

필드: `doc_id`, `chunk_id`, `content`(≤65535), `metadata`(JSON), `vector`(FLOAT_VECTOR, dim=1536).

> ⚠️ **구현 2벌 주의**: backend(`app/core/milvus.py`)는 `id INT64 auto_id` PK + KB metric_type/인덱스 파라미터화,
> ingest_service(`milvus_connector.py`)는 **`chunk_id` VARCHAR PK** + COSINE/HNSW 고정. 실제 쓰기는 ingest 쪽.
> 스키마 정합은 ingest 기준으로 유지할 것.

### 4.3 Fuseki (graph_backend=ontology)

- 데이터셋: `kb_{kb_id}` (TDB2), **named graph `urn:doc:{doc_id}`** — 문서 삭제 = 그래프 DROP.
- 네임스페이스(현행): 엔티티 `http://rag.local/inst/`, 관계 `http://rag.local/rel/`.
  (레거시 경로 일부에 `entity/`/`relation/` 잔존 — §9 참조)
- 트리플: 본 트리플 + 각 URI의 `rdfs:label` + (source_node_id 있으면) reification statement(`stmt/{hash}`: subject/predicate/object + meta:sourceNodeId/docId/confidence).
- 역관계: 한국어 매핑 사전(스승↔제자 등) 우선, 없으면 `inverse_{predicate}` 기계 생성.

### 4.4 Neo4j (graph_backend=neo4j)

- 노드: `(:Entity {name, kb_id})` — kb_id 로 KB 격리. 관계: predicate 원문을 APOC 동적 타입으로, 속성 `doc_id`/`is_inverse`/`source_node_id` — doc_id 로 문서별 삭제.

## 5. 모델 / 프로바이더 체계

- **builtin** 3종(openai/anthropic/google — `app/config/models.json`의 base_url) + **custom**(임의 이름/base_url/키/모델목록/extra_headers).
- 모델 설정 dict `{provider, provider_id, provider_name, model, base_url}` 이 KB·스테이지·요청 곳곳에서 쓰이며, `resolve_model_config()` 가 최종 `{model, api_key, base_url, extra_headers, embedding_request_format}` 로 해석:
  custom(provider_id가 UUID) → CustomProvider 조회·복호화 / builtin → models.json + BuiltinProviderConfig 복호화 / 이후 config 명시값이 오버라이드. **env 폴백 없음** — 설정 없으면 api_key=None.
- 해석 우선순위 체인(요청 > 스테이지 > KB)과 소비자별 주의사항은 **model-config-and-pipeline-contract.md** 가 정본.

## 6. 인제스트 파이프라인 (ingest_service)

업로드(`POST /{kb_id}/documents`) → backend 가 KB/폼에서 설정 병합·모델 해석(`ingest_llm`, `subject_restoration_llm` 등 필수 검증) → ingest 잡 생성 → 콜백으로 상태 갱신 (`UPLOADED → EXTRACTING_TRIPLES → COMPLETED/FAILED`, WebSocket `/api/ws/{kb_id}` 브로드캐스트).

처리 순서(`IngestPipeline.process`): Step0 텍스트 정제(옵션) → Phase1 전역 엔티티 사전(정규화 옵션 시) → Phase2 청킹 → Phase3 임베딩 + 트리플 병렬 추출 → Phase4 후처리 정규화 → Milvus 삽입 + Fuseki/Neo4j 삽입(+ 파일시스템에 chunks/triples/metadata JSON 보존).

- **청킹 전략(실구현 enum)**: `fixed_size`, `sliding_window`, `hierarchical`, `context_aware`(LLM 필요), `parent_child`. (모듈 docstring의 markdown/semantic 은 **미구현** — §9)
- **추출기**: `simple` / `dynamic` / `schema` / `none`(벡터 전용 KB).
- 부가 기능: 주어 복원(subject restoration, LLM), 엔티티 정규화(embedding/string/llm), 역관계 생성, 프리뷰-확정 플로우(`/preview` → `/confirm`), 단일 청크 추출 테스트(`/extract-chunk`).

## 7. 검색 (backend)

### 7.1 파이프라인 모드 (권장 — [ADR-001](adr/ADR-001-pipeline-based-retrieval.md))

`/chat` 은 요청 `pipeline` 필드 또는 KB 저장 `pipeline_config.stages` 가 있으면 **PipelineExecutor** 로 실행. 스테이지를 순차 적용하며 `score_history` 로 스테이지별 점수 추적.

| 스테이지 | 주요 params (기본값) |
|---|---|
| `ann` | top_k=10, threshold=0.5, index_type=IVF_FLAT, merge_mode=union, rescore=True |
| `bm25` | top_k=50, use_multi_pos=True, merge_mode |
| `brute_force` | top_k=3, threshold=1.5 (L2) |
| `graph` | hops=2, top_k=10, use_relation_filter, enable_inverse, inverse_mode, use_schema_mode, use_dynamic_schema, custom_query_prompt, enable_entity_expansion, sparql_prompt_template, **llm_model**(스테이지 전용 모델; 없으면 컨텍스트 llm_model_config 폴백) |
| `rerank` | top_k=5, threshold=0.0, use_llm=False, llm_strategy=full |
| `ner_filter` | penalty=0.3, tokenizer=regex, mode=nnp |

### 7.2 레거시 모드

파이프라인이 없으면 전략 기반: `keyword` / `hybrid` / `2-stage`(CrossEncoder ms-marco-MiniLM-L-6-v2) / `graph`·`hybrid_graph`·`hybrid_ontology` / 기타→`vector`. KB가 `enable_graph_rag` 이면 그래프 자동 활성 + ann/vector→hybrid 전환. 이후 선택적 리랭커·NER·brute_force 후처리.
**`/retrieve` 엔드포인트는 레거시 전용** (파이프라인 미지원).

### 7.3 그래프 검색 내부

질의 → LLM 엔티티 추출 → (Fuseki) Intent+Slots 기반 SPARQL 생성(동적 스키마 주입, `guide-sparql-generation.md`) 또는 (Neo4j) Cypher 생성 → 실행 → 트리플→청크 매핑 → Milvus 에서 본문 회수 → (결과 없으면 entity-guided fallback). Chat 은 검색 결과를 컨텍스트로 chat-prompt 기반 LLM 답변 생성.

## 8. API 표면 (2026-07-15 전수 조사, HTTP 54 + WS 1)

**backend** (`/api/knowledge-bases` 등 40):

- KB: `POST|GET /`, `GET|DELETE /{kb_id}`, `GET|PUT /{kb_id}/pipeline`, `POST /{kb_id}/promote`
- 프롬프트/규칙: `extraction-rules/{content,validate,save}`, `query-prompt/{content,save}`, `extraction-prompt/{content,save}`, `settings/{rerank-prompt,chat-prompt}(GET|PUT)`
- 문서: `POST /{kb_id}/documents`, `POST /{kb_id}/documents/upload-text`, `GET /{kb_id}/documents`, `DELETE /{kb_id}/documents/{doc_id}`, `GET .../chunks`, `GET .../pipeline/data`, `POST /ingest/callback`(ingest→backend 콜백)
- 검색: `POST /{kb_id}/retrieve`, `POST /{kb_id}/chat`, `GET /{kb_id}/chunks/{chunk_id}`
- 그래프 뷰어(`/api/graph`): `expand`, `schema`, `schema/instances`, `triples/{kb_id}`
- 프로바이더(`/api/providers`): `GET /`, `PUT /builtin/{id}/key`, `POST /fetch-models`, `POST|PUT|DELETE /custom…`, `GET /custom/{id}/key`
- WebSocket: `/api/ws/{kb_id}` (인제스트 진행률)

**ingest_service** (`/api`, 11): `POST /ingest`, `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `POST /preview`, `POST /confirm/{preview_id}`, `DELETE /preview/{preview_id}`, `POST /extract-chunk`, `POST /save-chunk-triples`, `GET /health`, `GET /`

**proxy** (3): `POST /v1/embeddings`, `POST /v1/chat/completions`, `GET /health`

## 9. 알려진 불일치 / 기술 부채 (조사 시점)

1. **backend 진입점 2벌**: `backend/main.py`(운영, Dockerfile CMD) vs `backend/app/main.py`(비활성 사본, `/api/health` 존재·태그 상이). 드리프트 위험 — 통합 필요.
2. **Milvus 컬렉션 생성 코드 2벌**: PK·인덱스 정책 상이 (§4.2). ingest 쪽이 실효.
3. **RDF 네임스페이스 불일치**: 현행 `inst:`/`rel:` vs 레거시 경로(`app/services/ingestion/graph.py` 등)의 `entity:`/`relation:`.
4. **청킹 docstring 과대 표기**: markdown/semantic 미구현.
5. **Fuseki 인증 하드코딩**: `admin/admin` (fuseki_connector).
6. `/retrieve` 가 파이프라인 미지원 — `/chat` 과 기능 격차.

## 10. 관련 문서

- [`docs/README.md`](README.md) — 문서 색인·상태
- [`PLATFORM-INTEGRATION.md`](PLATFORM-INTEGRATION.md) — 셸 연계·배포·함정
- [`architecture/model-config-and-pipeline-contract.md`](architecture/model-config-and-pipeline-contract.md) — 모델 해석 체인·스테이지 계약
- [`architecture/ingestion_pipeline_reference.md`](architecture/ingestion_pipeline_reference.md), [`architecture/kb_isolation_and_storage.md`](architecture/kb_isolation_and_storage.md)
- [`adr/`](adr/) — 결정 기록 (ADR-001~003)
