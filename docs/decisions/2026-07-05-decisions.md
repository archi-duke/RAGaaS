# 2026-07-05 의사결정 로그

> 11/17 복원 — `docs/_archive/arch-2026-02/decision/llm-invocation.md` (2026-07-05 작성) 에서 옮겼다. 원본은 그 문서.

## D1. LLM 프록시 제거, 게이트웨이 직접 호출 (LLM-01)

- **결정**: `proxy/` 서비스와 `PROXY_SERVICE_URL` 삭제, 앱이 직접 호출.
- **기각**: 프록시 완성(디버깅 곤란·장애점), GoJIRA Platform-API 경유(프로젝트 간 강결합, KB별 프로바이더 선택 상실).

## D2. 챗 호출은 단일 함수 `achat`/`chat`(raw HTTP), 임베딩만 SDK (LLM-02)

- **이유**: 인증·엔드포인트·파싱·오류 처리를 한 경로로. SDK 는 헤더 전용 인증·reasoning 파싱을 깔끔히 못 함.
- **남은 것**: graph2ontology 의 LLM 호출 4곳은 통일 안 됨.

## D3. LLM 실패를 숨기지 않는다 (LLM-03, fail-loud)

- **결정**: 네트워크·4xx/5xx·빈 응답·설정 누락은 모두 `LLMError`. 임의 기본 모델(gpt-4o)·예외 삼키는 폴백 제거 (사용자 지시).
- **기각**: 빈 결과·원문으로 계속 진행 — 데이터 오염.

## D4. 응답 파싱·인증·시크릿·사내 모델 (LLM-04~07)

- `content` 가 비면 `reasoning_content` → `reasoning` (gpt-oss 정상 형식).
- 헤더 인증 우선, Bearer 는 키가 있을 때만.
- `${ENV}` 치환으로 시크릿을 DB 에 평문 저장하지 않음.
- 사내 모델은 `internal_models.json` 에 등록해 합성 프로바이더로 노출. **기각**: 모델마다 CustomProvider DB 등록 (N번 등록·시크릿 DB 저장).
