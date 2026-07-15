# ADR — 아키텍처 결정 기록

초기 설계(`../arch/`)와 실제 구현이 달라진 지점을 공식 기록한다.
새로운 구조적 결정(채택/번복)이 생기면 여기에 ADR을 추가하고 [`../README.md`](../README.md) 색인을 갱신할 것.

| ID | 제목 | 상태 | 대체하는 결정 |
|---|---|---|---|
| [ADR-001](ADR-001-pipeline-based-retrieval.md) | 스테이지 기반 검색 파이프라인 채택 | Accepted | arch CA-102 기각 결정 번복 |
| [ADR-002](ADR-002-http-ingest-service.md) | 인제스트를 브로커+워커 대신 HTTP 마이크로서비스로 | Accepted | arch CA-203 |
| [ADR-003](ADR-003-mongodb-metadata-store.md) | 메타데이터 저장소 SQLite → MongoDB(Beanie) | Accepted | specification v1 §2.1 |

**형식**: 상태(Accepted/Superseded) · 관련(대체 대상) · 맥락 · 결정 · 결과(긍정+부정 필수) · 참조 파일.
