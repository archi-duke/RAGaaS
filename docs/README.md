# RAGaaS 문서 지도

> `docs/` 전체의 **위치와 상태**를 표시한다. 문서를 근거로 작업하기 전에 여기서 상태를 확인하고,
> 문서를 추가·이동하거나 상태가 바뀌면 함께 갱신한다. (갱신 2026-11-17 — 문서 정리)

**상태**
- ✅ **현행** — 지금 시스템과 맞음. 작업 근거로 사용.
- 📐 **설계만** — 승인됐지만 (일부) 미구현. 구현 상태를 코드로 확인.
- 📖 **참고** — 작성 시점 기준 기록. 코드로 다시 확인 후 사용.
- 🗄️ **보관** — `_archive/`. 작업 근거로 사용 금지.

---

## 시작점

| 순서 | 문서 | 내용 |
|---|---|---|
| 1 | [`guides/run-and-deploy.md`](guides/run-and-deploy.md) | 기동·빠른 반영·테스트·경로·LLM·저장소 함정 |
| 2 | [`technical-decisions.md`](technical-decisions.md) | 왜 이렇게 만들었나 — 주제별 결정·폐기·이유, 설계와 구현 불일치(9장) |
| 3 | [`architecture/model-config-and-pipeline-contract.md`](architecture/model-config-and-pipeline-contract.md) | 모델 설정 해석 순서, 스테이지 계약, LLM 연동 함정 |
| 4 | [`architecture/코드_구조_분석.md`](architecture/코드_구조_분석.md) | 코드 디렉토리 맵 |

## 결정 이력

| 경로 | 내용 |
|---|---|
| [`technical-decisions.md`](technical-decisions.md) | 주제별 색인 — ADR·날짜별 로그·설계서를 함께 가리킴 |
| [`decisions/`](decisions/) | 날짜별 의사결정 로그 (원본). 2026-07 ~ 11-16 은 11/17 복원 |
| [`adr/`](adr/README.md) | 큰 구조 결정 (ADR-001~004) |

## 설계서 (`design-*.md`)

| 문서 | 상태 | 내용 |
|---|---|---|
| `design/graph/design-graph-relation-targeting.md` | ✅ | 관계 SPARQL → 트리플 → 연결 청크 (11/14) |
| `design/graph/design-graph-class-query.md` | ✅ | 유형 질문 질의 계획 → 결정적 SPARQL (11/14) |
| `design/graph/design-graph-multihop-chain.md` | ✅ | 다단계 질문 홉별 체인 (11/15, 11/17 보정) |
| `design/graph/design-agentic-filter.md` | ✅ | 에이전틱 파이프라인 필터·스크래치패드 (11/16) |
| `design/graph/design-query-analysis-merge.md` | ✅ | 질문 분석 LLM 1회 + 엔티티 역할 (07/17) |
| `design/graph/design-query-generation-loop.md` | 📖 | LLM SPARQL 재시도·동적 few-shot (07/16) — 지금은 C 폴백 경로에만 |
| `design/schema/design-graph-promotion.md` | ✅ | 텍스트 → 그래프 → 스키마 유도·시드 → 리플레이·재추출 (11/14~15) |
| `design/schema/design-schema-mismatch.md` | ✅ | 동치 확장 + KB 매핑 규칙 (11/14) |
| `design/schema/design-schema-editor.md` | ✅ | 스키마 편집기·AI 추천·데이터 검증 (11/16) |
| `design/schema/design-year-attributes.md` | ✅ | 진술 연도 + query_plan 연도 조건 (11/17, PR #64) |
| `design/schema/design-structured-json-yaml-ontology.md` | ✅ | JSON/YAML 결정론적 매핑 — Phase 1~3·문서 간 엔티티 동일성 (PR #39) |
| `design/schema/design-ingest-entity-typing-b.md` | ✅ | 적재 시 엔티티 타입 (B안, opt-in, 기본 off) |
| `design/schema/design-ontology-schema-extraction-v2.md` | 📖 | 승격 스키마 추출 A안 (07/19) — 11/15 시드 스키마 승격으로 대체 |
| `design/ingest/design-ingest-queue-and-observability.md` | 📐 | 적재 큐(미구현) + 관측성 (Phase A 만 구현) |
| `design/agent/design-kb-lexicon.md` | ✅ | KB 용어 사전 (11/16) |
| `design/agent/design-mcp-agent-query.md` | ✅ | 외부 에이전트 MCP·query_plan (11/16, ADR-004) |
| `design/agent/design-typo-synonym-matching.md` | ✅ | 오탈자·유사어 — 자모 편집거리·라벨 임베딩 후보 + 질문 분석 교정 (11/17) |
| `design/agent/design-search-entry-and-pipeline-versions.md` | ✅ | 단일 검색 진입점·KB 검색 정책 + 파이프라인 운영/테스트 탭·Git 버전 이력 (11/17) |

## 가이드 (`guides/`)

| 문서 | 상태 | 내용 |
|---|---|---|
| [`run-and-deploy.md`](guides/run-and-deploy.md) | ✅ | 기동·트러블슈팅·운영 함정 |
| [`schema-editor.md`](guides/schema-editor.md) | ✅ | 스키마 편집기 사용 설명서 |
| [`ops-schema-quality-and-answer-risk.md`](guides/ops-schema-quality-and-answer-risk.md) | ✅ | 스키마 품질(위반·누락)과 답변 위험·체크리스트 |

## 아키텍처 참조 (`architecture/`)

| 문서 | 상태 | 내용 |
|---|---|---|
| `model-config-and-pipeline-contract.md` | ✅ (07/15 검증) | 모델 설정 해석 체인, 스테이지 계약, LLM 함정 |
| `ingestion_pipeline_reference.md` | 📖 | 적재 단계·코드맵·정리 원칙 (01월 작성) |
| `kb_isolation_and_storage.md` | 📖 | KB 격리, 저장소별 분리, 삭제 정책 ("Neo4j 기본값" 은 낡음 — 주력 Fuseki) |
| `processing_pipeline_principles.md` | ✅ | 청크 가공 vs 엔티티 해소 책임 분리 |
| `backend-architecture.md` | 📖 | 백엔드 구조 개요 (07/06) |
| `코드_구조_분석.md` | 📖 | 디렉토리·모듈 맵 (01월 작성, 07/15 확인) |
| `../specification-v2.md` | 📖 | 사양서 (07/15) — 11월 기능(그래프 검색 고도화·승격·MCP) 미반영 |

## 그 밖

| 경로 | 상태 | 내용 |
|---|---|---|
| [`platform-contract/`](platform-contract/README.md) | ✅ | NETRIX 셸 MF 연계 계약 01~06 |
| [`datasets/physics-history/`](datasets/physics-history/README.md) | ✅ | 물리학사 39문항 평가 데이터셋·평가 기록 |
| [`blog/`](blog/) | 📖 | 블로그 4편 (2026-01): BM25, 그래프 추출 최적화, Fallback 정책, 노이즈 노드 |
| [`_archive/`](_archive/README.md) | 🗄️ | 초기 설계(arch-2026-02), 폐쇄망 배포, 지운 문서의 요약 |
