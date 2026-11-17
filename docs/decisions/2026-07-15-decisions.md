# 2026-07-15 의사결정 로그

> 11/17 복원 — PR #35, `docs/adr/` (이날 기록), `docs/architecture/model-config-and-pipeline-contract.md`, `docs/specification-v2.md` 에서 옮겼다.

## D1. standalone Docker → NETRIX 플랫폼 셸의 Module Federation remote

- 프론트를 MF remote(`ragaasApp`, `./App`·`./manifest`)로. React 18 → 19 (셸 singleton). 인프라는 shared-infra 참조.
- **폐기**: 루트 compose·Dockerfile·airgap 배포 일체 (`deploy/` 는 GoJIRA 방식으로 재구성).
- **참조**: PR #35, `PLATFORM-INTEGRATION.md`

## D2. 초기 설계 이탈을 ADR 로 기록 (ADR-001~003)

- CA-102 파이프라인 기각 번복(ADR-001), CA-203 브로커+워커 → HTTP 적재 서비스+콜백(ADR-002), SQLite → MongoDB+Beanie(ADR-003). 헥사고날 폴더 구조는 미채택 (arch/README 정정표).
- ADR 형식: 결과에 긍정·부정을 모두 적는다.
- **주의**: ADR-003 의 전환 동기는 ADR 스스로 "추정" 이라 밝힘.

## D3. 모델 키는 DB(프로바이더 등록값)만 — 환경변수 폴백 금지

- `resolve_model_config()`: 커스텀 provider_id → CustomProvider(Fernet 복호화), builtin → `models.json` + BuiltinProviderConfig, config 의 명시 `api_key`/`base_url` 이 최종 오버라이드. `OPENAI_API_KEY` 는 읽지 않는다.
- **운영 함정**: `ENCRYPTION_KEY` 가 바뀌면 복호화 실패 — 환경 이전 시 유지.

## D4. 검색 모델 우선순위와 스테이지 배선

- default: 요청(`pipeline_model_config` ?? `frontend_model_config`) → KB 저장값 → `kb.llm_model_config`. `/chat` 은 요청 모델을 KB 에 저장(의도).
- graph 스테이지: `params["llm_model"]` 우선, 없으면 `ctx.metadata["llm_model_config"]`. 키 이름이 계층마다 달라 executor 가 변환.
- **계기**: 배선 누락으로 그래프 검색이 전부 죽어 있었다.

## D5. LLM 연동 운영 규칙 (실제 장애 6건에서)

- LlamaIndex 에는 `api_base`, 생성기 타임아웃 60 → 180초, 텍스트 재작성 보조 단계에 thinking 모델 금지 (glm-5.2 가 0자 반환), z.ai 는 키와 엔드포인트 짝, 업로드 시 `require_llm()` 사전 검증.
