# 2026-07-06 의사결정 로그

> 11/17 복원 — `docs/platform-contract/README.md` (v1.0-draft 2026-07-06), PR #30·커밋 a6dd85d 에서 옮겼다.

## D1. 플랫폼 통합 계약 v1.0 전제 6건

- 툴체인 Vite + TypeScript, MF 런타임 `@module-federation/vite`(MF 2.0), Kendo 는 `@platform/web-ui` 만 직접 의존.
- 인증은 셸의 `platformApp/auth` exposed 모듈, 공지는 셸 NoticeCenter 마운트만.
- 폐쇄망: 런타임 env 주입(`env.js` / `window._env_`) — 재빌드 없이 호스트 교체.
- 백엔드 계약은 언어중립(HTTP·헤더·ENV)으로만 — 백엔드가 Go·파이썬으로 갈려 코드 공유 전제 불가.
- **기각**: CRA/CRACO, remote 자체 로그인, 앱의 Kendo 직접 의존.

## D2. LLM 은 사내 게이트웨이 직접 호출 (`extra_headers` 헤더 인증)

- `app.core.llm` 경유. 사내 환경의 LLM·임베딩 호출용. (11/05 PR #42 로 복원 — `2026-11-05` D2)
