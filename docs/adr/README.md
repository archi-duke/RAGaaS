# ADR — 아키텍처 결정 기록

초기 설계(`../arch/`)와 실제 구현이 달라진 지점을 공식 기록한다.
새로운 구조적 결정(채택/번복)이 생기면 여기에 ADR을 추가하고 [`../README.md`](../README.md) 색인을 갱신할 것.

**ADR 과 결정 로그의 역할 (2026-11-17)**
- ADR: 큰 구조 결정 — 저장소, 서비스 경계, 외부 계약. 되돌리기 비싼 것.
- [`../decisions/`](../decisions/) 날짜별 로그: 그 밖의 기술 선택·폐기. 주제별 색인은 [`../technical-decisions.md`](../technical-decisions.md) (ADR 도 함께 가리킴).
- 결정 로그를 쓰다 ADR 감이 나오면 여기로 올리고 로그에는 ADR 번호를 단다.

| ID | 제목 | 상태 | 대체하는 결정 |
|---|---|---|---|
| [ADR-001](ADR-001-pipeline-based-retrieval.md) | 스테이지 기반 검색 파이프라인 채택 | Accepted | arch CA-102 기각 결정 번복 |
| [ADR-002](ADR-002-http-ingest-service.md) | 인제스트를 브로커+워커 대신 HTTP 마이크로서비스로 | Accepted (2026-07-17 큐 재도입 설계 — 미구현, 현행 유지) | arch CA-203 |
| [ADR-003](ADR-003-mongodb-metadata-store.md) | 메타데이터 저장소 SQLite → MongoDB(Beanie) | Accepted | specification v1 §2.1 |
| [ADR-004](ADR-004-agent-query-plan-contract.md) | 외부 에이전트 계약 = query_plan 하나 (클라이언트 SPARQL 직접 생성 기각) | Accepted (2026-11-16) | — |

**형식**: 상태(Accepted/Superseded) · 관련(대체 대상) · 맥락 · 결정 · 결과(긍정+부정 필수) · 참조 파일.
