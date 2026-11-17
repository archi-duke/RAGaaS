# 2026-11-05 ~ 06 의사결정 로그

> 11/17 복원 — PR #41~#44 에서 옮겼다.

## D1. 사내 DRM docx/pptx 는 사용자 PC 에서 변환 후 `upload-text` (PR #41, #44)

- Go 단일 exe `ragaas-converter` 가 Office COM 으로 추출, GoJIRA 런처 게이트웨이(127.0.0.1:5599)가 서비스 계약(`X-Svc-Secret`)으로 호출 — 브라우저 직접 호출 거부.
- 서버는 DRM 헤더면 `415 drm_protected`, docx/pptx 면 `415 local_conversion_required`.
- **기각**: 서버 측 변환(보안 도구 설치 불가), `minLauncher` 0.1.39 로 낮추기(되돌림 — 런처가 요구 수준을 맞춘다).
- **미검증**: 회사 PC `verify-drm.ps1`, 인제스트까지 전체 흐름. 설계는 GoJIRA `design-launcher-gateway.md`.

## D2. 사라진 플랫폼 계약 복원 (PR #42)

- PR #37 첫 커밋이 구버전 컨테이너 소스로 backend/ingest 를 덮어써, squash 머지에서 `/api/v2`·platform_auth·`X-Service-Token`·사내 게이트웨이 `extra_headers`·env.js 가 조용히 사라짐 → revert 로 복원. 하드코딩 `/api` 는 `config.RAGAAS_API`/`wsBase()` 로.
- **폐기**: "운영 컨테이너 상태로 소스를 일괄 동기화" 하는 방식.

## D3. 노출된 OpenAI 키 — placeholder 교체, 실질 조치는 폐기(revoke) (PR #43)

- 이력 재작성은 선택. 키 폐기 여부는 사용자 확인 대상 (11/14 인수인계에서도 미결).
