# ADR-001: 스테이지 기반 검색 파이프라인 채택 (CA-102 결정 번복)

- **상태**: Accepted (2026-07-15 기록; 실제 채택 시점은 2026-02~03 구현기)
- **관련**: `docs/arch/architecture.md` 부록 B의 CA-102 기각 결정을 **supersede** 함

## 맥락

초기 아키텍처 설계 단계(`docs/arch/architecture.md` 부록 B, 후보구조 결정 표)에서는 두 개의 검색 흐름 제어 후보가 비교되었다.

| 후보 | 이름 | 결정 | 사유 |
|---|---|---|---|
| CA-101 | 전략 기반 검색 엔진 | **채택** | 동적 검색 실험을 위한 핵심 구조 |
| CA-102 | 파이프라인 기반 흐름 제어 | **기각** | 동적 분기 처리 및 성능 오버헤드 면에서 불리함 |

이에 따라 시스템은 `strategy` enum(`ann` / `keyword` / `2-stage` / `hybrid`)을 받아 검색 로직을 통째로 선택하는 CA-101 구조로 구현되었다. 그러나 이후 실제 요구사항(스테이지별 세부 파라미터 제어, 그래프·리랭커·NER 필터 등 이질적 검색 요소의 조합, 사용자가 UI에서 검색 흐름을 직접 구성하고자 하는 니즈)이 대두되면서, 고정된 strategy enum만으로는 대응이 어려워졌다.

## 결정

CA-102 기각 결정을 번복하고, **스테이지 기반 Search Pipeline**을 도입하여 CA-101과 병행 운영한다.

- `backend/app/schemas/pipeline.py`: `PipelineStage{type, params}`, `PipelineConfig{stages}` 스키마 정의. 스테이지 타입은 `ann`, `bm25`, `brute_force`, `graph`, `rerank`, `ner_filter` 6종.
- `backend/app/services/retrieval/pipeline_executor.py`: `PipelineExecutor`가 `stage.type` 기준으로 핸들러(`_execute_ann`, `_execute_bm25`, `_execute_brute_force`, `_execute_graph`, `_execute_rerank`, `_execute_ner_filter`)를 순차 실행하며, `ExecutionContext`를 통해 스테이지 간 결과·메타데이터를 전달한다.
- KB(지식베이스) 문서에 `pipeline_config`(`{"stages": [...]}`)를 영속화한다(`backend/app/models/knowledge_base.py`). 조회/저장은 `GET/PUT /api/knowledge-bases/{kb_id}/pipeline`(`backend/app/api/knowledge_base.py`)으로 제공.
- 프론트엔드에 Search Pipeline 빌더 UI를 구현하여 사용자가 스테이지를 조합·구성할 수 있게 했다.
- **이중 모드 분기**: `POST /{kb_id}/chat`(`backend/app/api/retrieval.py`)는 요청 바디의 `pipeline` 필드가 있으면 이를 우선 사용하고, 없으면 KB에 저장된 `pipeline_config.stages`가 있는지 확인하여 있으면 파이프라인 모드로, 둘 다 없으면 기존 `strategy` 기반 레거시 모드로 폴백한다.
- 스테이지별 파라미터는 스테이지 전용 `llm_model` 설정을 가질 수 있으며(`params.get("llm_model")`), 미지정 시 실행 컨텍스트의 `llm_model_config`(KB/요청 레벨 기본값)로 폴백한다(`pipeline_executor.py` 277~299행, 2026-07-15 수정으로 배선 완료).

## 결과

**긍정적 영향**

- 검색 흐름을 코드 변경 없이 스테이지 조합으로 구성할 수 있어, 그래프 검색 → 리랭크 → NER 필터 같은 다단계 조합 실험이 가능해졌다.
- KB 단위로 파이프라인을 영속화함으로써 지식베이스별로 다른 검색 전략을 UI에서 직접 설계·저장할 수 있게 되었다.
- 스테이지 단위 LLM 모델 오버라이드(`llm_model`)로 리랭커/그래프 스테이지마다 다른 모델을 지정할 수 있어 유연성이 높아졌다.

**부정적 영향 / 부채**

- CA-102 기각 사유였던 "동적 분기 처리 및 성능 오버헤드"는 근본적으로 해소되지 않은 채, 순차 스테이지 실행 구조(`pipeline_executor.execute`)로 구현되어 있다. 스테이지 수가 늘어날수록 지연시간이 누적되는 구조적 리스크가 남아 있다.
- CA-101(전략 기반)과 파이프라인 기반이 **동시에 존재**하는 이중 구조가 되어, `strategy` enum 경로와 `PipelineExecutor` 경로 두 가지를 모두 유지·테스트해야 하는 부담이 발생했다.
- `POST /{kb_id}/retrieve` 엔드포인트는 파이프라인 모드를 지원하지 않고 레거시 `strategy` 전용으로 남아 있어, `/chat`과 `/retrieve` 간 기능 불일치가 존재한다. KB에 파이프라인이 저장되어 있어도 `/retrieve` 호출 시에는 무시된다.
- 아키텍처 문서(부록 B)가 실제 구현과 어긋난 상태로 방치되어 있었다(본 ADR 작성 시점 기준 CA-102는 여전히 "기각"으로 기록됨). 본 ADR이 이 불일치를 문서상으로 정정하는 역할을 겸한다.
- 파이프라인 모드와 레거시 모드가 결과 스키마(`ChatResponse.strategy`, `pipeline_config` 표시 문자열 등)를 공유하면서 분기 로직(`backend/app/api/retrieval.py` 364~420행)이 복잡해졌다.

## 참조 파일

- `docs/arch/architecture.md` (부록 B, CA-101/CA-102 결정 표 — 181~182행)
- `backend/app/schemas/pipeline.py`
- `backend/app/services/retrieval/pipeline_executor.py`
- `backend/app/api/retrieval.py` (`/chat` 이중 모드 분기: 134~138행, 364~420행; `/retrieve` 레거시 전용: 219행)
- `backend/app/api/knowledge_base.py` (`GET/PUT /{kb_id}/pipeline`: 90행, 105~126행)
- `backend/app/models/knowledge_base.py` (`pipeline_config` 필드: 19행)
