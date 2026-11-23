# RAGaaS

여러 지식 베이스(KB)를 만들고 문서를 적재해 **벡터·키워드·지식 그래프** 로 검색하는 RAG 서비스.
텍스트 문서는 그래프로 적재한 뒤 **온톨로지로 승격**할 수 있고, 외부 에이전트(Claude Code, GoJIRA)에는 **MCP** 로 제공한다.
NETRIX 플랫폼 셸의 Module Federation remote 로 동작하며, 운영은 사내 폐쇄망을 전제로 한다.

## 구성

| 서비스 | 역할 |
|---|---|
| `backend/` (FastAPI) | KB·문서 관리, 검색 파이프라인, 그래프 검색, 스키마 편집, MCP (`/api/mcp`) |
| `ingest_service/` (FastAPI) | 문서 파싱·청킹·임베딩·트리플 추출, 리플레이·재추출 |
| `frontend/` (React + Vite, MF remote) | KB·문서·검색·스키마 편집기 화면 |
| `skills/ragaas-query/` | 외부 에이전트용 스킬 — 스키마를 받아 질의 계획(query_plan)을 직접 작성 |
| `tools/ragaas-converter/` | 사내 DRM 문서를 사용자 PC 에서 텍스트로 변환 (GoJIRA 런처 경유) |

저장소는 GoJIRA 와 공유하는 shared-infra: Milvus(벡터), Apache Jena Fuseki(RDF·SPARQL, 주력 그래프), Neo4j, MongoDB(메타데이터), Redis.
LLM 은 KB 별로 설정한다 (현재 Z.ai GLM `glm-5.2`).

## 주요 기능

- **검색 파이프라인**: ANN · BM25(Kiwi 형태소) · 2-stage 재랭크 · 그래프 · NER 필터 스테이지를 KB 별로 조합, 에이전틱 필터, 답변 스트리밍.
- **그래프 검색**: 질문의 관계를 겨냥한 SPARQL → 트리플 → 연결 청크로 답한다 (관계 타게팅). 유형 질문은 질의 계획, 다단계 질문은 홉별 체인. 추론 과정은 Execution Log 에 리포트.
- **온톨로지 승격·스키마 편집기**: 그래프에서 스키마 유도·시드 스키마 → 검토 → 리플레이·재추출. 클래스·관계 편집, 관계 방향 검증, 중복 엔티티 정리, 트리플 이동·삭제·뒤집기·추가 규칙, KB 용어 사전(한/영·동의어·상위 개념).
- **구조화 문서(JSON/YAML)**: LLM 없이 구조 그대로 온톨로지로 매핑.
- **외부 에이전트 MCP**: 클라이언트가 query_plan JSON 을 쓰고 RAGaaS 는 검증·컴파일·실행만 (서버 LLM 0, 읽기 전용).

## 실행

운영·개발 기동과 문제 해결은 [`docs/guides/run-and-deploy.md`](docs/guides/run-and-deploy.md).
접속: `http://<gateway-host>:44300/ragaas` · API `/ragaas/api/v2/` · MCP `/ragaas/api/mcp/`.

## 문서

먼저 [`docs/README.md`](docs/README.md) (문서 지도). 왜 이렇게 만들었는지는 [`docs/technical-decisions.md`](docs/technical-decisions.md) (기술 결정 이력).

## 라이선스

[Apache License 2.0](LICENSE). 저작권 고지와 제3자 구성요소 안내는 [`NOTICE`](NOTICE) 참고.

프론트엔드가 쓰는 KendoReact(`@progress/kendo-*`)는 Progress 의 상용 소프트웨어로 이 라이선스에 포함되지 않습니다. 빌드·배포하려면 별도의 KendoReact 라이선스가 필요합니다.
