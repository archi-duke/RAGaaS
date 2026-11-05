# ragaas-converter

사용자 PC 에서 **docx/pptx → 텍스트** 변환을 하는 로컬 서비스. 사내 DRM(NASCA) 문서는 DRM 에이전트가 붙은
로컬 Office 로만 열리므로, 서버가 아닌 사용자 PC 에서 Office COM 으로 텍스트를 뽑아 RAGaaS `upload-text` 로 등록한다.

GoJIRA 런처 게이트웨이의 첫 외부 서비스다 — 설계: GoJIRA `docs/design-launcher-gateway.md` (§9 서비스 계약, §12.2 명세).

```
[RAGaaS 업로드 화면] docx/pptx 선택 → 선두 32바이트로 DRM 판정(표시용)
   → POST http://127.0.0.1:5599/v1/docs/{docx|pptx}/text   (런처: Origin·토큰 검증 후 중계)
      → ragaas-converter: 임시 파일 저장 → convert.ps1 (Word/PowerPoint COM, 숨김·읽기 전용) → 삭제 → {text}
   → POST /api/v2/knowledge-bases/{kb}/documents/upload-text  (source_filename/format/drm 포함)
```

## API

| 메서드/경로 | 설명 |
|---|---|
| `POST /v1/docs/docx/text`, `POST /v1/docs/pptx/text` | 본문 = 원본 바이트(`application/octet-stream`), `X-File-Name`(URL 인코딩, 로그용). 응답 `{text, format, units, unit, drm, chars, elapsedMs}` |
| `GET /health` | `{version, ready, busy, requirements:{windows, powershell, word, powerpoint}}` |
| `POST /shutdown` | 진행 중 변환 마무리(최대 10초) 후 종료 |

오류: `401` 시크릿 불일치 · `403` 브라우저 직접 호출 · `404` 미지원 형식 · `413` 크기 초과 · `415` OOXML/DRM 아님 ·
`422 convert_failed`(손상·암호·DRM 미복호화, DRM 이면 `hint` 포함) · `424 requirement_missing` · `504 timeout`.

## 런처 계약 (서비스 모드)

| 환경변수 | 의미 |
|---|---|
| `SVC_PORT` (필수) | listen 포트 (127.0.0.1) |
| `SVC_SECRET` (필수) | 런처가 주입하는 비밀값 — `X-Svc-Secret` 불일치 요청 거부 |
| `SVC_DATA_DIR` | 변환 스크립트·임시 파일 위치 (기본 `%TEMP%\ragaas-converter`) |
| `SVC_LOG_DIR` | 로그 파일 위치 (없으면 stderr) |
| `SVC_MAX_MB`, `SVC_TIMEOUT_SEC` | 크기 상한(기본 200), 변환 시간 상한(기본 240) |

- `Origin` 헤더가 있는 요청은 거부한다(런처는 Origin 을 제거해 중계 — 브라우저 직접 호출 차단).
- Office 자동화는 **한 번에 하나**(PowerPoint 단일 인스턴스). 사용자가 이미 띄운 PowerPoint 는 종료하지 않는다.
- 시간 초과 시 이번 변환 중 새로 뜬 `WINWORD.EXE`/`POWERPNT.EXE` 만 강제 종료한다.
- 매크로 비활성(`AutomationSecurity=ForceDisable`), 암호 문서는 프롬프트 없이 실패 처리.

## 개발 모드 (런처 게이트웨이 도입 전)

```bash
cd tools/ragaas-converter
go run . -dev                                   # http://127.0.0.1:5601, CORS origin http://localhost:5173
go run . -dev -dev-origin http://localhost:5173,http://localhost:3000
```
`-dev` 는 `/launcher/health`(token `dev`)·`/launcher/capabilities` 스텁을 제공한다. 프론트는
`REACT_APP_LAUNCHER_BASE=http://127.0.0.1:5601` 로 지정하면 런처 없이 전체 흐름을 검증할 수 있다.

## DRM 사전 검증 (회사 PC 에서 1회)

변환기는 브라우저가 보낸 바이트를 **임시 경로에 새 파일로 저장**한 뒤 연다. DRM 에이전트가 이 사본도 복호화하는지 확인:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify-drm.ps1 -Path "C:\docs\암호화된문서.pptx"
```
`[temp-copy] OK` 가 나와야 한다. `[original] OK` 인데 `[temp-copy] FAILED` 면 DRM 정책이 경로/프로세스 기반이므로
변환 위치(SVC_DATA_DIR)를 DRM 허용 폴더로 지정하는 등 대응이 필요하다.

## 빌드·패키지

```bash
tools/ragaas-converter/build.sh     # vet + test + windows/amd64 빌드 → dist/ragaas-converter-<ver>-windows-amd64.zip(+.sha256)
```
zip = `ragaas-converter.exe` + `service.json`. 카탈로그 등록·서명은 GoJIRA 플랫폼 레포의 `catalog-*` 워크플로 담당.

## 테스트

```bash
go test ./...        # 라우팅·인증·CORS·DRM 판정·크기/형식 거부·타임아웃 (Office 불필요, 가짜 변환기)
```
실 Office 변환은 `-dev` 로 띄운 뒤 curl 로 확인:
```bash
curl -X POST --data-binary @sample.pptx http://127.0.0.1:5601/v1/docs/pptx/text
```
