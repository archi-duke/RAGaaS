"""외부 에이전트용 조회 (docs/design/agent/design-mcp-agent-query.md).

에이전트가 스키마를 받아(describe) → 값·엔티티를 맞추고(values/entities) → 질의 계획을 보내면(plan, P2)
RAGaaS 는 LLM 없이 검증·변환·실행만 한다. 이 패키지의 출력 형식은 그래프 백엔드(Fuseki/Neo4j)와 무관하게 유지한다.
"""
