# 모델 설정 해석 체인 · 검색 파이프라인 스테이지 계약 · LLM 연동 함정

> **상태**: ✅ 현행 · **최종 검증**: 2026-07-15
> 이 문서는 2026-07-15 세션에서 그래프 파이프라인을 마비시켰던 **연쇄 버그 6건**의 수정
> (backend 커밋 `93fc5ed` + ingest_service 수정)을 계기로, 재발 방지를 위해 계약을 명문화한 것이다.
> **LLM/임베딩을 호출하는 코드를 추가·수정하기 전에 반드시 §4 함정 목록을 확인할 것.**

---

## 1. 모델 설정(ModelConfig) dict — 공용 형태

UI(ModelSelector)·KB·스테이지·요청 전반에서 쓰이는 형태:

```json
{
  "provider":      "openai | anthropic | google | <custom provider_id UUID>",
  "provider_id":   "<custom일 때 CustomProvider UUID>",
  "provider_name": "표시명 (예: 'Z.ai GLM')",
  "model":         "glm-5.2",
  "base_url":      "https://api.z.ai/api/coding/paas/v4"
}
```

- custom 프로바이더는 `provider` 와 `provider_id` 에 **같은 UUID** 가 들어간다 (ModelSelector `handleConfirm` 참조).
- `_has_model_selection()`: `provider/provider_id/model/api_key/base_url` 중 하나라도 있으면 "지정됨".

## 2. `resolve_model_config()` — 최종 해석 (backend/app/core/models_resolver.py)

입력 ModelConfig → `{model, api_key, base_url, extra_headers, embedding_request_format}` 반환.

1. config 없음 → `model=gpt-4o-mini, api_key=None` (즉시 반환).
2. `provider_id` 가 builtin(openai/anthropic/google)이 **아니면** → `CustomProvider` 조회: base_url/extra_headers/embedding_request_format + `encrypted_key` **Fernet 복호화**.
3. 아니고 `provider` 가 builtin 이면 → `models.json` 의 base_url + `BuiltinProviderConfig.encrypted_key` 복호화.
4. config 에 명시된 `api_key`/`base_url`/`embedding_request_format` 이 있으면 **최종 오버라이드**.

**철칙: 환경변수 폴백 없음.** `OPENAI_API_KEY` env 는 이 경로에서 절대 읽지 않는다. 키가 없으면 `api_key=None` → 호출부가 명시적 에러를 내야 한다. 복호화 실패(`ENCRYPTION_KEY` 변경)는 `ValueError` — 환경 이전 시 ENCRYPTION_KEY 를 반드시 기존 값으로 유지해야 하는 이유.

## 3. 검색 경로의 해석 우선순위 체인

### 3.1 요청 → KB 레벨 (backend/app/api/retrieval.py `_resolve_retrieval_model_configs`)

```
default 모델 = request.pipeline_model_config ?? request.frontend_model_config   (요청)
             ?? KB 저장값(_read_model_from_kb_storage "default")
             ?? kb.llm_model_config                                             (KB)
keyword 모델 = request.model_config_keyword ?? KB 저장값("keyword") ?? default
```

`/chat` 은 `persist=True` — **요청에 실린 모델 설정이 KB 에 저장된다** (플레이그라운드에서 모델을 바꾸면 KB 설정이 바뀜을 의미. 의도된 동작).

### 3.2 파이프라인 스테이지 레벨 (pipeline_executor)

- executor 는 `execute(..., llm_model_config=, embedding_service=)` 로 받은 값을 `ctx.metadata` 에 담는다.
- **graph 스테이지**: `params["llm_model"]`(스테이지 전용, UI 파이프라인 빌더가 저장) **우선** → 없으면 `ctx.metadata["llm_model_config"]` 폴백.

> ⚠️ **키 이름이 계층마다 다르다 — 이것이 버그 #1 의 원인이었다.**
> 스테이지 params 키는 `llm_model`, 전략 `search()` kwargs 키는 `llm_model_config`.
> executor 가 이 변환을 담당한다. 새 스테이지를 추가하면 이 배선을 명시적으로 해야 한다
> (2026-07-15 이전에는 아무 스테이지도 배선하지 않아 그래프 검색이 전부 죽어 있었다).

### 3.3 스테이지 → 전략/백엔드 레벨

`GraphRetrievalStrategy.search()` 는 `kwargs["llm_model_config"]` **필수** (없으면 `Graph search model is not configured`). resolve 후:

| 소비자 | 클라이언트 | base_url 전달 방식 |
|---|---|---|
| graph.py 엔티티 추출/분석 | openai SDK `AsyncOpenAI` | `base_url=` ✅ 그대로 |
| fuseki.py → SPARQLGenerator | raw `requests` | `llm_endpoint = base_url + "/chat/completions"` + `llm_model` **명시 전달 필수** |
| neo4j.py → CypherGenerator | raw `requests` | 동일 |

생성기 기본값은 OpenAI 주소 + gpt-4o — **api_key 만 넘기면 커스텀 키가 OpenAI 로 날아가 401** (버그 #2).

## 4. 함정 목록 (실제 장애 이력 기반 — 필독)

### 4.1 LlamaIndex (ingest_service) — `base_url` 이 조용히 무시된다

`llama_index.llms.openai.OpenAI` / `OpenAIEmbedding` 의 파라미터는 **`api_base`** 다.
`base_url=` 로 넘기면 **에러 없이 무시**되고 기본 OpenAI 주소로 간다 (버그 #5 — z.ai 키가 OpenAI 로 가서 401).

```python
OpenAI(model=..., api_key=..., api_base=base_url)   # ✅
OpenAI(model=..., api_key=..., base_url=base_url)   # ❌ 조용히 무시됨
```

### 4.2 LlamaIndex — 모델명 화이트리스트

`llama_index.llms.openai` 는 모델명을 하드코딩 목록과 대조한다. 커스텀 모델(glm-5.2 등)은
`ValueError: Unknown model` (버그 #4). 등록으로 우회:

```python
from llama_index.llms.openai import utils as oai_utils
oai_utils.ALL_AVAILABLE_MODELS.setdefault(model, 128000)
oai_utils.CHAT_MODELS.setdefault(model, 128000)
```

(`ingest_service/app/core/pipeline.py::_get_llm` 이 base_url 이 OpenAI 가 아닐 때 자동 수행.)

### 4.3 추론(thinking) 모델의 타임아웃·빈 출력

- SPARQL/Cypher 생성기 timeout 은 **180초** (60초였을 때 glm-5.2 가 read timeout — 버그 #3). 대형 스키마 프롬프트 + thinking 모델 조합은 60초를 훌쩍 넘긴다.
- **Subject Restoration 등 "텍스트 재작성" 보조 단계에 thinking 모델을 쓰지 말 것** — glm-5.2 가 3,436자 입력에 **0자**를 반환해 빈 청크→임베딩 400 으로 잡 전체가 실패했다 (버그 #6). 보조 단계는 gpt-4o-mini 급 안정 모델 권장. 파이프라인에 빈 출력 가드 추가는 남은 개선 과제.

### 4.4 z.ai 엔드포인트 이원화

| base_url | 용도 |
|---|---|
| `https://api.z.ai/api/coding/paas/v4` | **Coding 플랜 키** 전용 — 현재 등록된 "Z.ai GLM" 프로바이더가 사용 |
| `https://api.z.ai/api/paas/v4` | 일반 크레딧 — coding 키로 호출 시 `1113 Insufficient balance` |

키와 엔드포인트가 짝이 맞아야 한다. 유효 모델 ID: `glm-5.2`, `glm-5.1`, `glm-5-turbo`, `glm-5` 등.

### 4.5 인제스트 업로드의 모델 키맵 (backend/app/api/document.py `_UPLOAD_LLM_KEYMAP`)

업로드 `chunking_config`(JSON form 필드)로 단계별 모델을 지정하며, KB `chunking_config` 에 persist 된다:

| 용도 | 키 접두 |
|---|---|
| 트리플 추출 (ingest) | `llm_provider / llm_model / llm_base_url / llm_provider_id` |
| 청크 그루핑 (context_aware 시 필수) | `chunk_grouping_llm_*` |
| 주어 복원 | `subject_restoration_llm_*` |
| 명사 추출 (정규화 시) | `noun_extraction_llm_*` |

각 단계는 `require_llm()` 으로 **모델+키 존재를 업로드 시점에 검증** (실패 시 500 "모델 지정이 안되었습니다").

### 4.6 스테이지 계약 요약 (새 스테이지 추가 시 체크리스트)

1. `pipeline_executor._handlers` 에 등록, `meta.phases`… 아님 — `schemas/pipeline.py` 의 `Literal` 타입에도 추가.
2. LLM 이 필요하면 `params.get("llm_model") or ctx.metadata.get("llm_model_config")` 배선.
3. 임베딩이 필요하면 `ctx.metadata.get("embedding_service")` 를 kwargs 로 전달 (None 이면 키 생략 — 전략의 default 폴백 유지).
4. 하위 함수에서 상위 지역변수를 참조하지 말 것 — `graph._fetch_chunks` 의 `emb_service` NameError (버그 #2') 사례.
5. 결과는 `_update_results_with_history(..., merge_mode)` 로 병합해 `score_history` 를 남길 것.

## 5. 버그 이력 (이 문서의 근거)

| # | 위치 | 증상 | 수정 |
|---|---|---|---|
| 1 | pipeline_executor `_execute_graph` | llm_model_config 미전달 → "model is not configured" | 스테이지 `llm_model` 우선 + 컨텍스트 폴백 배선 |
| 2 | graph_backends fuseki/neo4j | 생성기에 api_key 만 전달 → 커스텀 키가 OpenAI 로 401 | `llm_endpoint`(base_url+`/chat/completions`)+`llm_model` 전달 |
| 2' | graph.py `_fetch_chunks` | 타 함수 지역변수 `emb_service` 참조 NameError → 결과 폐기 | 파라미터로 전달 |
| 3 | sparql/cypher_generator | timeout 60s — thinking 모델 read timeout | 180s |
| 4 | ingest pipeline `_get_llm` | LlamaIndex 모델 화이트리스트 → Unknown model 'glm-5.2' | ALL_AVAILABLE_MODELS 등록 |
| 5 | ingest pipeline `_get_llm`/`_get_embedding_model` | `base_url=` 무시 → 키가 OpenAI 로 401 | `api_base=` 로 수정 |
| 6 | subject_restoration + glm-5.2 | thinking 모델이 0자 반환 → 빈 청크 임베딩 400 | 보조 단계는 안정 모델 사용 (운영 지침, §4.3) |

backend 1~3 은 커밋 `93fc5ed` (`fix(retrieval): repair graph pipeline...`), ingest 4~5 는 `ingest_service/app/core/pipeline.py` 수정.
