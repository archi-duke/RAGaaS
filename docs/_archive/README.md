# 보관 문서

현행이 아닌 문서를 모은다. 2026-11-17 문서 정리 때 지운 문서는 **요약만** 여기 남겼다 — 원본은 git 이력에 있다:

```bash
git show 38eeae3:<원래 경로>      # 정리 직전 main
```

결정(무엇을 왜 택했나)은 [`../technical-decisions.md`](../technical-decisions.md) 로 옮겼으니, 여기서는 "무엇이었고 지금 어디에 반영됐나" 만 적는다.

## 원본을 그대로 보관한 것

| 경로 | 무엇 | 왜 남겼나 |
|---|---|---|
| [`arch-2026-02/`](arch-2026-02/README.md) | 초기 아키텍처 설계 (2026-02): 요구사항 → ASR → 품질 시나리오 → 후보 구조(CA) → 평가 → 결정 | 설계 추적 체계. 요약·현재 상태는 결정 이력 0장. 현행과 다른 점은 ADR-001~003. `decision/decisions.md` 와 `evaluation/decisions.md` 는 이름이 겹치지만 다른 분석 단계 문서다 |
| [`airgap-deploy-2026-07.md`](airgap-deploy-2026-07.md) | 폐쇄망 배포 가이드 (이미지 export/import) | 7/15 standalone 배포를 걷어낸 뒤 낡았지만, 운영이 사내 폐쇄망으로 갈 예정이고 `tools/scripts/*airgap*` 가 참조한다 — 새 폐쇄망 절차의 출발점 |
| `specification-v1.md` 외 4개 | 최초 사양·계획·작업 메모 | 7/15 정리 때 보관 (v1 사양 → `../specification-v2.md`) |

## 요약만 남긴 것 (원본 삭제, 2026-11-17)

### 로컬 실행 가이드 5종 — `DEV_RUN.md`, `LOCAL_SETUP.md`, `LOCAL-RUN.md`, `SETUP.md`, `DOCKER.md` (루트)
- 루트 `docker-compose.yml` 로 Milvus·Neo4j·Fuseki·Mongo·Redis 를 로컬에 띄우고 venv + uvicorn(8000·8001) + vite 로 실행하던 방식, OpenAI 키를 `.env` 에 넣던 설정.
- **폐기**: 7/15 shared-infra 전환과 플랫폼 MF remote 전환 (PR #35). 키는 DB 우선 (`2026-07-15` D3).
- **지금**: [`../guides/run-and-deploy.md`](../guides/run-and-deploy.md).

### `backend/architecture.md`
- `docs/architecture/backend-architecture.md` 와 글자까지 같은 중복 — 삭제.

### `.analysis/` 5개 (2026-01-27 ~ 30)
- 업로드 모달 흐름 분석, 파이프라인 문제 분석(sampling_size 미전달·청킹 설정 중첩·Docker 콜백 URL·graph_config 누락·파일 경로), 상태 업데이트·임시 파일 저장 개선 계획과 완료 보고.
- **지금**: 적재 상태·관측성은 `design-ingest-queue-and-observability.md` Phase A (2026-07-17), 적재 단계는 `architecture/ingestion_pipeline_reference.md`.

### `graph-optimization-report.md`, `graph-optimization-implementation-complete.md` (2026-01)
- 그래프 추출 최적화: UI 기본값, 대명사 해소 규칙(Rule 5), 후처리(노이즈 predicate·조사 제거·S-P-O 중복 제거), Fuseki 폴백 후처리, Doc2Onto 통합, 테스트.
- **지금**: 경위는 [`../blog/graph-extraction-optimization.md`](../blog/graph-extraction-optimization.md), 결정은 결정 이력 0장. 블로그의 "역관계 생성 안 함"·"섹션 2500/1000" 은 코드와 다르다 (결정 이력 9장).

### `refined_implementation_plan.md` (2026-07-06)
- Entity-Centric 동적 스키마 — 질문을 3패턴(`? → P → O`, `S → ? → O`, `S → P → ?`)으로 나눠 Fuseki 질의, 폴백 Global-P.
- **지금**: 11/14 관계 타게팅(`design-graph-relation-targeting.md`)과 유형 질의 계획(`design-graph-class-query.md`)이 대체. 질문 분석의 subject/object 역할(`design-query-analysis-merge.md`)에 흔적.

### `guide-sparql-generation.md`, `guide-cypher-generation.md` (2026-01)
- 자연어 → Intent + Slots → SPARQL/Cypher 템플릿 → 엔티티·속성 매핑 → 쿼리 생성 개발 지침 (바이브 코딩 가이드).
- **지금**: LLM SPARQL 생성은 C 경로(폴백)에만 남았고 재시도 루프는 `design-query-generation-loop.md`. 상위 경로는 관계 타게팅·질의 계획·체인, 외부 계약은 query_plan (ADR-004).

### 플랫폼 온보딩 통지 5개 — `platform-contract/ragaas-*.md` (2026-07-06 ~ 07)
- GoJIRA 팀의 셸 합류 작업 지시서와 통지: 게이트웨이 경로 단순화, `@platform/web-ui` tarball, frontend shared-net 조인, 셸 탭 활성화, C1~C3 합동 검증 통과(**온보딩 Phase 1 완료, 2026-07-07**), API 폴백 계약 수용(05 §5), standalone `/ragaas/` 진입 폐지, Account/Notice 앱 스코핑(조치 불필요).
- **남은 것**: Phase 2 (Kendo Grid → `@platform/web-ui` 이관) 완료 여부는 확인되지 않음.
- **지금**: 계약 본문 [`../platform-contract/`](../platform-contract/README.md) 01~06.
