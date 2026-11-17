# ADR-004: 외부 에이전트 계약 = query_plan 하나 (클라이언트 SPARQL 직접 생성 기각)

- **상태**: Accepted (2026-11-16)
- **관련**: `docs/design-mcp-agent-query.md`, `docs/decisions/2026-11-16-decisions.md` D2·D3, PR #61

## 맥락

RAGaaS 를 Claude Code·GoJIRA 같은 외부 에이전트에 MCP 로 제공하게 됐다 (운영은 사내 폐쇄망).
내부 파이프라인은 질문 분석·경로 선택에 LLM 을 쓰고, 첫 글자까지 9~14초가 걸린다. 외부 에이전트는 이미 LLM 이므로
질의를 직접 만들 수 있다. 사용자 제안은 "호출하는 에이전트가 아예 SPARQL 을 생성해서 보내면" 이었다.
그래프 저장소는 지금 Fuseki 지만 최종적으로 Neo4j 도 지원해야 한다.

## 결정

- 클라이언트 에이전트는 `describe_kb` 로 스키마(유형·경로·값)를 받아 **query_plan JSON**(조건 트리 all/any, return, aggregate)을 쓴다.
- RAGaaS 는 query_plan 을 검증하고 저장소 질의(SPARQL, 이후 Cypher)로 **컴파일·실행**만 한다 — RAGaaS 쪽 LLM 0.
- **외부 계약은 query_plan 하나**다. 원문 SPARQL 엔드포인트는 관리자·디버그 전용(`AGENT_SPARQL_ENABLED`).
- 안전장치: 읽기 전용, KB 범위 고정, 조건·결과·시간 상한, 실패는 `status: error`, 0건은 이유와 함께 `zero` (자동 완화 없음).
- MCP 는 `/api/mcp` (게이트웨이 `/ragaas/api/mcp/`), 사용법은 스킬 `skills/ragaas-query`.

## 결과

**긍정**
- 저장소를 Neo4j 로 바꾸거나 함께 써도 클라이언트는 바뀌지 않는다 (컴파일러만 추가).
- 서버가 검증할 수 있는 닫힌 형식이라 쓰기·과부하·인젝션 위험이 없다.
- RAGaaS 쪽 LLM 호출이 없어 비용·지연이 줄고, 결과가 결정적이다.

**부정**
- query_plan 이 표현할 수 없는 질의(유형 간 조인, 산술)는 클라이언트가 여러 번 조회해 조합해야 한다.
- 계약을 바꾸면 모든 클라이언트(GoJIRA style-define, 스킬)를 함께 바꿔야 한다 — 필드는 추가만 하고 의미를 바꾸지 않는다 (예: 11/17 연도 조건 `year` 는 선택 필드로 추가).
- 품질이 클라이언트 LLM 의 계획 능력에 좌우된다 (물리학사: GLM 에이전트 31 → 39/39, 스킬 보강·용어 사전 이후).

## 기각한 대안

- **클라이언트가 SPARQL 직접 생성**: 저장소 종속(Neo4j 불가), 쓰기·과부하 쿼리를 막기 어렵고 검증 불가.
- **내부 파이프라인(/chat)을 그대로 제공**: 서버 LLM 비용·지연, 클라이언트가 근거 경로를 통제할 수 없음.

## 참조 파일

`backend/app/services/agent_query/plan.py` · `catalog.py` · `backend/app/mcp_server.py` · `backend/app/services/retrieval/class_query.py` (검증·컴파일)
