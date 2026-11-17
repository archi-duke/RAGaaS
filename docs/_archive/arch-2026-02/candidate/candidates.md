# 후보 구조 목록 (Candidates List)

본 문서는 식별된 아키텍처적 유의미한 요구사항(ASR) 및 품질 시나리오를 해결하기 위해 제안된 후보 구조(Candidate Architecture, CA)들의 목록을 관리합니다.

| ID | 관련 ASR/QS | 후보 구조 제목 | 설계 에이전트 | 상태 |
| :--- | :--- | :--- | :--- | :--- |
| ID | 관련 ASR/QS | 후보 구조 제목 | 설계 에이전트 | 참조 |
| :--- | :--- | :--- | :--- | :--- |
| CA-101 | ASR-101, 102 | 전략 기반 하이브리드 검색 엔진 (Strategy-based) | asr-architect | ASR-101-하이브리드-검색-수행.md |
| CA-102 | ASR-101, 102 | 파이프라인 기반 흐름 제어 (Pipe-and-Filter) | asr-architect | ASR-101-하이브리드-검색-수행.md |
| CA-103 | ASR-103, 106 | 동기식 저장소 프로비저닝 매니저 (Sync Provisioner) | asr-architect | ASR-103-저장소-오케스트레이션.md |
| CA-104 | ASR-104, 105 | 후처리 인터셉터 체인 (Interceptor Chain) | asr-architect | ASR-104-후처리-필터-구조.md |
| CA-201 | ASR-201, QS-001 | 비동기 병렬 검색 흐름 (Parallel Retrieval) | performance-architect | QS-001-하이브리드-검색-응답-시간.md |
| CA-202 | ASR-202, QS-003 | 플러그형 엔진 어댑터 (Plugin Adapters) | modifiability-architect | QS-003-엔진-교체-및-동적-설정.md |
| CA-203 | ASR-203, QS-005 | 메시지 큐 기반 워커 분산 (Queue-load leveling) | scalability-architect | QS-002-대용량-데이터-확장성.md |
| CA-204 | ASR-204, QS-007 | 런타임 전략 파라미터 컨텍스트 전파 | modifiability-architect | QS-003-엔진-교체-및-동적-설정.md |
| CA-106 | ASR-106, QS-005 | KB 네임스페이스 기반 컬렉션 분할 | scalability-architect | QS-002-대용량-데이터-확장성.md |

## 요약
- **기능적 후보**: 4건 (CA-101 ~ 104)
- **품질 기반 후보**: 4건 (CA-201 ~ 204 예정)
