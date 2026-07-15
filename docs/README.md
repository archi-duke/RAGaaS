# RAGaaS 문서 색인 (Docs Index)

> 이 파일은 `docs/` 전체의 **정본 여부와 신뢰도**를 표시하는 색인이다.
> 문서를 근거로 작업하기 전에 반드시 여기서 상태를 확인할 것.
> 새 문서를 추가하거나 상태가 바뀌면 이 색인을 함께 갱신한다.

**상태 뱃지**
- ✅ **현행** — 현재 시스템과 일치함을 검증했음. 작업 근거로 사용 가능.
- 📖 **참고** — 기술 노트/이력 기록. 사실관계는 작성 시점 기준 — 코드로 재확인 후 사용.
- 🏛️ **설계이력** — 초기 설계 산출물. 방법론·의사결정 맥락 참고용. **현행 구조와 불일치 다수** — 작업 근거로 사용 금지.
- 🗄️ **아카이브** — 폐기됨. `_archive/` 이하 보존.

---

## 시작점 (신규 합류자/에이전트는 이 순서로)

| 순서 | 문서 | 내용 |
|---|---|---|
| 1 | [`PLATFORM-INTEGRATION.md`](PLATFORM-INTEGRATION.md) | 플랫폼(NETRIX) 연계·빌드·배포·함정. **배포 관련 최우선 문서** |
| 2 | [`specification-v2.md`](specification-v2.md) | 현행 시스템 사양 (서비스 구성/API/데이터/파이프라인) |
| 3 | [`architecture/model-config-and-pipeline-contract.md`](architecture/model-config-and-pipeline-contract.md) | 모델 설정 해석 체인 + 스테이지 계약 + LLM 연동 함정 |
| 4 | [`architecture/코드_구조_분석.md`](architecture/코드_구조_분석.md) | 코드 디렉토리 맵 |

---

## 현행 문서 ✅

| 문서 | 설명 | 최종 검증 |
|---|---|---|
| `PLATFORM-INTEGRATION.md` | NETRIX 셸 MF 연계, shared-infra 참조, deploy/ 빌드·운영, 함정 6종 | 2026-07-15 |
| `specification-v2.md` | 현행 사양서 (v1은 아카이브) | 2026-07-15 |
| `architecture/model-config-and-pipeline-contract.md` | LLM 모델 설정 해석 체인, 검색 파이프라인 스테이지 계약, LlamaIndex/z.ai 함정 | 2026-07-15 |
| `architecture/ingestion_pipeline_reference.md` | 인제스트 파이프라인 단계·코드맵·정리 원칙 | 2026-07-15 |
| `architecture/kb_isolation_and_storage.md` | KB 격리 원칙, 저장소별 분리 방식(named graph 등), 삭제 정책 | 2026-07-15 |
| `architecture/processing_pipeline_principles.md` | 청크 가공 vs ER 책임 분리 원칙 | 2026-07-15 |
| `architecture/코드_구조_분석.md` | 디렉토리/모듈 구조 참조 | 2026-07-15 |
| `startup_guide.md` | 서비스 가동 가이드 (deploy/ 기준으로 재작성됨) | 2026-07-15 |
| `adr/` | 아키텍처 결정 기록 (ADR). 결정 변경 이력 포함 | 2026-07-15 |

## 참고 문서 📖 (기술 노트 — 작성 시점 기준)

| 문서 | 설명 |
|---|---|
| `guide-sparql-generation.md` | SPARQL 생성기(Intent+Slots→템플릿) 설계 가이드 |
| `guide-cypher-generation.md` | Cypher 생성기 설계 가이드 |
| `blog-bm25-keyword-search.md` | BM25 키워드 검색 동작 원리 |
| `blog-graph-extraction-optimization.md` | 그래프 추출 최적화 (청크 크기/오버랩/필터) |
| `blog-graph-fallback-policy.md` | 그래프 검색 fallback 정책 (재현율 vs 정밀도) |
| `blog-llm-graph-noise-nodes.md` | Multi-hop QA 노이즈 노드 문제 기록 |
| `graph-optimization-report.md` / `-implementation-complete.md` | 그래프 추출 최적화 적용 보고 |

## 설계 이력 🏛️ (`arch/` — 초기 아키텍처 산출물)

역할·현행과의 차이는 [`arch/README.md`](arch/README.md) 참조. 요지: ASR→QS→후보구조(CA)→결정의
추적 체계는 유지하되, SQLite/브로커+워커/헥사고날 구조/CA-102 기각 등은 **현행과 다르며 `adr/` 이 정정 기록**.

| 문서 | 역할 |
|---|---|
| `arch/architecture.md`, `arch/architecture/{style,module,deployment}.md` | 최종 아키텍처 명세 (당시) |
| `arch/asr.md`, `arch/qualities.md`, `arch/functional.md`, `arch/business.md`, `arch/System.md` | 요구사항 산출물 |
| `arch/usecase/UC-*.md` | **유스케이스 요구사항 정본** (액터/조건/대안/예외 시나리오) |
| `arch/system/UC-*.md`, `arch/system/model.md` | usecase 파생 **기술 설계**(B/C/E 시퀀스) — 같은 파일명이지만 중복 아님 |
| `arch/quality/`, `arch/candidate/`, `arch/decision/`, `arch/evaluation/` | 품질 시나리오·후보 구조·평가·결정 |

## 아카이브 🗄️ (`_archive/`)

| 문서 | 사유 |
|---|---|
| `_archive/specification-v1.md` | 초기 사양서 (SQLite/고정 임베딩/모놀리스 전제 — [specification-v2.md](specification-v2.md)로 대체) |
| `_archive/task.md` | 초기 구현 태스크 목록 (전부 완료) |
| `_archive/implementation_plan.md` | 부분 텍스트 추출 기능 계획 (구현 완료 — `_archive/walkthrough.md` 참조) |
| `_archive/walkthrough.md` | 2026-01 작업 완료 보고 |
| `_archive/pipeline-management.md` | 파이프라인 버전관리 아이디어 메모 (백로그 후보) |
