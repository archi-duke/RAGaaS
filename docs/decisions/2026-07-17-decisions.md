# 2026-07-16 ~ 17 의사결정 로그

> 11/17 복원 — `design/graph/design-query-generation-loop.md` (07-16), `design/graph/design-query-analysis-merge.md`, `design/ingest/design-ingest-queue-and-observability.md` (07-17), PR #37 (07-17 머지) 에서 옮겼다.

## D1. 쿼리 생성 Inner/Outer Loop

- Inner: LLM 폴백 경로만, 실행 실패·0건이면 오류를 되먹여 최대 3회 재시도 (Fast Path 템플릿 제외). Outer: 성공 쿼리를 동적 few-shot (top-3, 유사도 ≥ 0.7). 실측 스키마 검증·SPARQL 이스케이프. `use_dynamic_schema` 기본 True.
- **번복(구현 중)**: 예시 저장을 Mongo+Milvus 하이브리드로 정했다가 Mongo 단일 + 인메모리 numpy 코사인으로 — 신규 Milvus 컬렉션 load 가 이벤트 루프를 동결, 예시는 KB당 200행 이하.

## D2. 질문 분석 병합 — LLM 2회 → 1회 (`_analyze_and_extract`)

- 결과에 `entities[].role`(subject/object/ambiguous)을 넣어 Pattern 1/3 분류 1차 신호로, 조사 휴리스틱은 폴백으로 강등. 멀티홉은 LLM `hop_count` 우선.
- **비목표**: 게이트·쿼리 생성·답변 병합. 기존 함수는 롤백용으로 유지.

## D3. 엔티티 링킹 랭킹 (완전일치 > 접두 > 부분포함)

- 노이즈 노드를 앵커로 잡지 않게. 그래프에 없는 엔티티 칩은 UI 비활성.

## D4. 적재 큐 = async 워커 + Redis 자체 구현 (설계만, 미구현)

- Redis 리스트 큐 + `job:{id}` 해시, `ingest-worker` 별도 컨테이너(같은 이미지), 사용자별 동시 상한·백프레셔, 롤백 플래그 `INGEST_USE_QUEUE`. ADR-002 의 재검토 조건 발동.
- **기각**: RQ(동기 워커 — async 이점 상실), Celery(비목표), 스레드 격리만(근본 해결 아님).
- **상태**: 미구현 — ADR-002 가 여전히 현행.

## D5. 관측성 착수 순서 — Phase A + chunk_id 근본 수정 먼저

- Phase A(PR #37): WS 채널 키 통일(`kb_{id}`), 실패 콜백, 숫자 progress, 오류 상세, stuck 판정. 무결성 문제는 차단 대신 경고(`integrity_warning`).
- **기각**: 삭제 검증 실패 시 즉시 차단 — '영원히 삭제 안 되는' 상황.
- **상태**: B(진행률 UI)·C(무결성)·D(큐) 미구현.

## D6. 블로킹 외부 I/O 는 예외만이 아니라 시간까지 격리

- Milvus 동기 load/query 5개 경로를 `to_thread` + `wait_for`, `num_entities == 0` 이면 조회 생략.
- **계기**: 손상·신규 컬렉션 load 가 이벤트 루프 전체를 멈춤. (11/15 재발)

## D7. 프로바이더 교체 시 base_url/provider_id 를 None 으로 명시 삭제

- 빈 값을 건너뛰던 코드 때문에 z.ai → OpenAI 전환 후 base_url 이 남아 'gpt 를 z.ai 로 보내는' 오염 반복.
