# LLM 호출 아키텍처 결정 (LLM Invocation Design Decisions)

> 이 문서는 RAGaaS의 **LLM(챗) 호출 계층**에 대한 설계 결정과 근거를 정리한다.
> 사내망(폐쇄망) 운영에서 사내 LLM 게이트웨이를 사용하기 위한 전환 결정을 담는다.
> 작성: 2026-07-05. 관련 코드: `backend/app/core/llm.py`, `backend/app/core/models_resolver.py`,
> `backend/app/config/internal_models.json`, `ingest_service/app/core/llm.py`.

---

## 1. 배경 / 문제 (Context)

- **운영 환경이 사내망(폐쇄망)** 이다. 사외 클라우드 LLM(OpenAI 등)에 접근할 수 없고,
  **사내에서 제공되는 LLM API 게이트웨이**(예: 삼성DS `gpt-oss-120b`)를 호출해야 한다.
- 사내 게이트웨이는 (a) **다중 헤더 인증**(`X-Dep-Ticket`, `Send-System-Name`, `User-Id`,
  `User-Type`, `Chat-Id`)을 요구하고, (b) `gpt-oss` 계열은 답을 `message.content` 가 아니라
  `reasoning_content` / `reasoning` 필드로 반환하며, (c) **모델마다 endpoint 가 다르다**
  (URL에 모델 경로가 박힘: `.../gpt-oss/1/gpt-oss-120b/v1/...`).
- 전환 전 RAGaaS의 상태:
  - 사외 클라우드 LLM(Bearer 인증) 전제. 사내에선 사실상 사용 불가.
  - `proxy/`(ragaas-proxy) 서비스가 사내 게이트웨이 중계용으로 있었으나 **미완성**
    (티켓 env 미사용, 공식 OpenAI로 중계, reasoning 미처리).
  - LLM 호출부가 **openai SDK**(`chat.completions.create`)와 **raw `requests`** 로 **혼재**,
    응답 파싱과 인증 방식이 제각각.
  - 실패 시 **조용히 fallback**(예외를 삼키고 `[]`/원문 반환, 모델 기본값 `gpt-4o` 주입)하는
    코드가 다수 → 잘못된 결과를 정상으로 오인할 위험.

## 2. 채택된 결정 (Accepted Decisions)

| ID | 결정 | 근거 |
| :-- | :-- | :-- |
| **LLM-01** | **프록시 제거, 프로바이더 직접 호출.** `proxy/` 서비스·compose 항목·`PROXY_SERVICE_URL` 삭제. | 별도 홉이 유지보수 부담·장애점. 인증/파싱을 앱 계층에서 직접 제어하는 편이 단순하고 투명. |
| **LLM-02** | **모든 LLM 챗 호출을 단일 함수 `achat`/`chat`(raw HTTP)로 통일.** openai SDK 챗 사용 전면 제거(임베딩만 SDK 유지). | 인증·엔드포인트·응답 파싱·오류 처리를 한 경로에 모아 일관성 확보. 헤더 전용 인증과 gpt-oss 파싱을 SDK 우회 없이 직접 제어. GoJIRA `Platform-API/llm/client.go` 와 동일 개념. |
| **LLM-03** | **Fail-loud: 실패는 숨기지 않는다.** 네트워크 오류·4xx/5xx·빈 응답·모델/자격 미설정은 모두 `LLMError` 로 올려 사용자에게 전달. 임의 모델 기본값 및 예외 삼킨 fallback 제거. | 임의 fallback 은 착오로 인한 잘못된 결과를 유발한다(사용자 지시). 실패를 드러내 조치를 유도. |
| **LLM-04** | **gpt-oss `reasoning` 파싱.** `content` 가 비면 `reasoning_content`→`reasoning` 순으로 실제 답을 읽는다. | 이는 fallback 이 아니라 해당 모델의 정상 응답 파싱. 없으면 사내 gpt-oss 응답이 빈 답이 됨. |
| **LLM-05** | **헤더 기반 인증 우선.** `extra_headers`(X-Dep-Ticket 등)를 그대로 싣고, `api_key` 가 있을 때만 Bearer 추가. 키 없으면 Authorization 미전송. | 사내 게이트웨이는 헤더 인증만 쓰고 Bearer 가 없음. 불필요한 Authorization 이 거부되는 경우까지 대비. |
| **LLM-06** | **시크릿은 `${ENV}` 치환.** `resolve_model_config` 가 base_url/api_key/extra_headers 값의 `${VAR}` 를 환경변수로 치환. | 티켓 등 시크릿을 DB 평문에 저장하지 않고 `.env` 로 주입. GoJIRA `llm.json` 방식과 동일. |
| **LLM-07** | **사내 다종 모델을 설정파일로 등록.** `config/internal_models.json` 에 모델별 `{name, endpoint, headers}` 나열. `resolve_model_config` 가 `provider_id=="internal"` 을 파일로 해석. `list_providers` 가 이를 합성 프로바이더로 노출 → 기존 모델 셀렉터가 프론트 변경 없이 표시. | 사내 모델은 호출 방식은 같고 endpoint 만 다름. 파일 참조 방식(GoJIRA `llm.json`)이 이 구조에 가장 적합하고, 모델 추가가 코드 변경 없이 파일 편집으로 끝난다. |

## 3. 기각된 대안 (Rejected Alternatives)

| 대안 | 기각 사유 | 채택안 |
| :-- | :-- | :-- |
| **프록시 서비스 완성**(ragaas-proxy 를 사내 게이트웨이 중계로 고침) | 별도 홉·장애점 유지. 인증/파싱을 원격에서 처리해 디버깅 어려움. | LLM-01 (직접 호출) |
| **openai SDK 유지 + 후처리만 추가** | SDK가 헤더 전용 인증(더미 키/Bearer 강제)·reasoning 파싱을 깔끔히 못 함. 호출부마다 파싱 후처리가 흩어짐. | LLM-02 (raw HTTP 단일화) |
| **실패 시 기본 동작으로 계속 진행**(예외 삼키고 빈 결과/원문) | 잘못된 결과를 정상으로 오인 → 데이터 오염·착오. | LLM-03 (fail-loud) |
| **사내 모델을 모델당 CustomProvider 로 등록**(DB) | 모델 N개 = 등록 N번, 시크릿 DB 저장, 관리 번거로움. 파일 대비 이점 없음. | LLM-07 (설정파일) |
| **RAGaaS LLM 호출을 GoJIRA Platform-API 로 라우팅**(공용 게이트웨이) | 프로젝트 간 강결합, KB별 프로바이더 선택 상실. | LLM-01/07 (자체 직접 호출 + 레지스트리) |

## 4. 결과 아키텍처 (Resulting Architecture)

```
KB 설정 / 요청
  llm_model_config = { provider_id | provider, model, ... }
        │
        ▼
resolve_model_config()                     # backend/app/core/models_resolver.py
  ├─ provider_id=="internal"  → internal_models.json 조회 (endpoint/headers)
  ├─ provider_id==<UUID>      → CustomProvider(mongo)
  ├─ provider in builtin      → BuiltinProviderConfig(mongo)
  └─ ${ENV} 치환(티켓 등)
        │  { model, api_key, base_url, extra_headers }
        ▼
achat() / chat()                           # backend·ingest app/core/llm.py (단일 진입점)
  ├─ chat_endpoint(base_url)  → …/chat/completions
  ├─ build_headers(api_key, extra_headers) → 헤더전용/ Bearer
  ├─ raw HTTP POST (httpx)
  └─ 응답: content → reasoning_content → reasoning  (없으면 LLMError)
        │
        ▼
   사내/사외 LLM 게이트웨이
```

- **ingest_service** 는 별도 프로세스지만 backend 가 모든 모델설정을 resolve 해서
  resolved `{model, api_key, base_url, extra_headers}` 를 넘기므로, 설정파일·resolve 는
  **backend 에만** 둔다. ingest 는 받은 cfg 로 `achat`/`chat` 만 호출한다.
- **임베딩**은 LLM 챗과 별개(`services/embedding.py`). `minimal`/`openai` 포맷 + extra_headers 로
  사내 게이트웨이를 직접 호출한다.

## 5. 핵심 파일 (Key Files)

| 파일 | 역할 |
| :-- | :-- |
| `backend/app/core/llm.py` | 단일 진입점 `achat`/`chat`, `build_headers`, `chat_endpoint`, `extract_content*`, `LLMError` |
| `ingest_service/app/core/llm.py` | 위의 사본(별도 프로세스) |
| `backend/app/core/models_resolver.py` | `resolve_model_config`(+internal 분기, `${ENV}` 치환), `load_internal_models` |
| `backend/app/config/internal_models.json` | 사내 모델 등록(모델별 endpoint/헤더) |
| `backend/app/api/providers.py` | `list_providers` — 사내 모델을 프로바이더로 노출 |

## 6. 검증 (Verification)

- 목(mock) 업스트림으로 `achat`/`chat` 9개 케이스 PASS: 정상 파싱, X-Dep-Ticket 주입,
  헤더전용 시 Authorization 미전송, reasoning fallback, Bearer 주입, 빈응답·4xx·모델미지정·자격없음 → LLMError.
- 사내 모델 해석 검증: `resolve({provider_id:"internal", model})` → endpoint/`${ENV}` 치환/헤더전용 인증 확인.
  `/api/providers` 에 "사내 게이트웨이" 노출 확인. 전 변경 파일 컴파일·컨테이너 임포트·`/docs` 200.

## 7. 남은 사항 / 주의 (Open Items)

- **실 게이트웨이 E2E 미검증**: 개발 환경에 티켓/키가 없어 실제 사내 게이트웨이 대상 호출은 배포 환경에서 확인 필요.
- **graph2ontology 서브시스템**(승격/온톨로지-QA, 현재 KB `is_promoted=false` 라 미사용)의 4개 LLM 호출은
  공용 파서(`extract_content_from_dict`)+`raise_for_status`(4xx fail-loud)만 적용. 완전한 `chat()` 통일·헤더 인증
  배선은 그 서브시스템을 사내 게이트웨이로 쓸 때 필요.
- **Authorization 수용 여부**: 실 게이트웨이가 추가 Authorization 헤더를 거부하면 프로바이더를 키 없이(헤더 전용)
  등록한다 → `build_headers` 가 Authorization 을 아예 보내지 않는다.

## 8. 배포 시 사용법 (Operational)

1. `backend/app/config/internal_models.json` 의 `models` 에 사내 모델을 `{name, endpoint, type}` 로 나열.
   헤더의 `${LLM_DEP_TICKET}`/`${LLM_USER_ID}` 는 `.env` 로 주입.
2. UI 모델 셀렉터에서 "사내 게이트웨이"의 모델을 골라 KB에 지정(코드 변경 불필요).
3. 사외 OpenAI 등은 기존대로 Built-in/Custom 프로바이더로 등록해 병행 가능.
