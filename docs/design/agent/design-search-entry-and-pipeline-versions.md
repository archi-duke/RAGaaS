# 설계: 단일 검색 진입점 + 파이프라인 운영/테스트 분리·버전 이력

> **문서 상태 (2026-11-17)**: ✅ 현행 (구현 — S1~S4, 공용 Gitea 연동 확인) · 지도: [`docs/README.md`](../../README.md)

작성일: 2026-11-17
관련: `design-mcp-agent-query.md` (MCP·query_plan, ADR-004), `design-typo-synonym-matching.md`, `../graph/design-agentic-filter.md`, `../../architecture/model-config-and-pipeline-contract.md`

---

## 1. 문제

### 1.1 실험과 운영이 섞여 있다

- Playground 의 파이프라인 화면은 설정을 바꿀 때마다 0.5초 뒤 자동으로 `PUT /knowledge-bases/{kb}/pipeline` 에 저장한다.
- 이 저장본(`kb.pipeline_config`)이 곧 운영 설정이다. API 채팅과 MCP `search` 가 요청에 파이프라인이 없으면 이것을 쓴다.
- 그래서 Playground 에서 실험하는 순간 외부 에이전트가 받는 검색 동작이 바뀐다. 예전 설정으로 돌아갈 방법도 없다.

### 1.2 진입점이 흩어져 있고, 같은 KB 인데 경로마다 동작이 다르다

| 호출자 | 진입점 | 파이프라인 | 설정 반영 |
|---|---|---|---|
| Playground 채팅 | `POST /chat/stream` | 화면 설정을 요청에 실음 | ✅ |
| API 채팅 | `POST /chat` | 요청에 있으면 그것, 없으면 KB 저장본 | ✅ |
| 검색만 | `POST /retrieve` | 옛 경로 (파이프라인과 별개) | ❌ |
| MCP `search` | `/chat` 함수를 직접 호출 | KB 저장본 | ✅ (에이전틱 포함, 답변 생성 후 버림) |
| MCP 조회 도구 (`lookup_values`, `query_plan` 등) | 그래프 직접 조회 | 읽지 않음 | ❌ (Typo·Synonym 등 항상 켜짐) |

## 2. 결정 (사용자, 2026-11-17)

1. **정책의 출처는 하나.** 파이프라인 설정이 그 KB 의 검색 정책이다. 채팅·API·MCP 모두 같은 정책을 따른다.
2. **검색 필터가 있어야 검색한다.**
   - Graph 필터가 없으면 그래프 검색을 하지 않는다.
   - 벡터 필터가 없으면 벡터 검색을 하지 않는다.
   - 검색 필터가 하나도 없으면 "검색 필터 없음, 검색 결과 없음" 으로 응답한다.
3. **옵션은 켜져 있으면 실행, 꺼져 있으면 그 단계만 건너뛴다(pass).** 도구는 모두 열어 두되 단계마다 정책을 확인한다. 나중에 Graph 뒤에 붙인 후처리 필터도 MCP 에 같이 적용된다.
4. **에이전틱은 MCP 에서 건너뛴다.** 외부 에이전트가 이미 에이전틱 역할을 한다. 호출 파라미터로 실행을 고를 수 있다.
5. **진입점은 `search` 하나.** UI·API·MCP 가 모두 같은 함수로 들어오고, 파라미터에 따라 운영 동작 또는 테스트 동작이 된다.
6. **운영과 테스트를 분리한다.** 파이프라인 화면을 "운영"·"테스트" 두 탭으로 나눈다. 테스트 탭에서 "반영" 을 누르면 확인을 거쳐 운영 탭에 반영된다.
7. **파이프라인 구성은 JSON 으로 관리하고 이력을 남긴다.** 이력은 고지라가 쓰는 Gitea 의 Git 커밋으로 남긴다. 옛 버전을 언제든 조회하고, 테스트 탭으로 불러와 다시 시험할 수 있다.

## 3. 단일 검색 진입점

### 3.1 함수

```python
# backend/app/services/retrieval/search_entry.py (신규)
async def search(kb_id: str, query: str, opts: SearchOptions) -> SearchResult

class SearchOptions:
    config: Literal["live", "draft"] | int = "live"   # 운영 / 테스트 / 특정 버전 번호
    pipeline: dict | None = None    # 저장하지 않은 임시 구성 (테스트 탭에서 편집 중인 것)
    agentic: Literal["pipeline", "skip"] = "pipeline"
    answer: bool = True             # False 면 답변 생성 없이 근거만
    stream: bool = False
    caller: Literal["ui", "api", "mcp"] = "api"   # 로그·트레이스 구분용 (동작을 바꾸지 않는다)
```

- 동작은 `config`·`pipeline`·`agentic`·`answer` 로만 정한다. `caller` 는 기록용이다.
- **호출자별 기본값**

| 호출자 | config | agentic | answer | stream |
|---|---|---|---|---|
| 테스트 탭 채팅 | `draft` (편집 중이면 `pipeline` 에 실음) | pipeline | true | true |
| 운영 탭 채팅 | `live` | pipeline | true | true |
| API `/chat` | `live` | pipeline | true | false |
| MCP `search` | `live` | **skip** | **false** | false |

- `/chat`, `/chat/stream`, MCP `search` 는 이 함수를 감싸기만 한다. `/retrieve` 는 `answer=false` 호출로 바꾼다 (응답 형식은 유지).
- 트레이스에 `config`(버전 번호 포함)와 `caller` 를 남겨, 어떤 설정으로 나온 결과인지 나중에 확인할 수 있게 한다.

### 3.2 처리 순서

1. **구성 해석**: `pipeline` 이 있으면 그것, 아니면 `config` 가 가리키는 버전.
2. **검색 필터 확인**: 구성에서 검색 필터(Graph·ANN·BM25 등 결과를 만드는 스테이지)를 찾는다. 하나도 없으면 `status="disabled"`, `reason="검색 필터 없음"` 으로 끝낸다.
3. **에이전틱**: `agentic="skip"` 이면 에이전틱 스테이지를 뺀 사본으로 실행한다.
4. **스테이지 실행**: 지금의 파이프라인 실행기 그대로. 옵션이 꺼진 단계는 건너뛰고, 건너뛴 사실을 `applied_policy` 에 남긴다.
5. **답변**: `answer=false` 면 생성하지 않는다. 지금 MCP 가 답변을 만들고 버리는 낭비(호출당 4~8초)가 없어진다.

### 3.3 응답에 정책 표시

```json
"applied_policy": {
  "config": {"kind": "live", "version": 12},
  "search_filters": ["graph", "ann"],
  "skipped": ["agentic (MCP)", "typo_synonym (꺼짐)"],
  "graph": {"max_hops": 6, "typo_synonym": false, "list_supplement": true, "graph_fallback": "vector"}
}
```

외부 에이전트가 "결과 0건" 과 "검색 자체를 안 함" 을 구분하고, 결과가 왜 다른지 알 수 있게 한다.

## 4. MCP 조회 도구의 정책 연동

조회 도구는 검색이 아니라 그래프의 부품 조회라서 진입점은 따로 둔다. 다만 **같은 정책 해석 함수**(`resolve_policy(kb, config="live")`)로 운영 설정을 읽는다.

| 도구 | 따르는 설정 | 켜짐 | 꺼짐 / 없음 |
|---|---|---|---|
| `describe_kb` | 전체 | 응답에 `policy` (검색 필터 목록, Graph 옵션, 후처리 목록) | Graph 필터 없음 → `disabled` |
| `lookup_values`, `resolve_entities` | Graph 필터 유무, Typo·Synonym | 사전 + 오타·유사어 후보 | 후보 단계 건너뜀 (사전만) / Graph 없음 → `disabled` |
| `query_plan`, `describe_entity` | Graph 필터 유무, 후처리 | 실행, 근거 청크에 후처리 적용 | Graph 없음 → `disabled` |
| `get_chunks` | 검색 필터 유무, 후처리 | 청크 순서·걸러내기 적용 | 검색 필터 없음 → `disabled` |
| (클라이언트 연쇄 조회) | Max Hop | `policy.max_hops` 를 스킬이 지킨다 (서버가 강제하지는 않음) | — |

- 스킬(`ragaas-query`)에 `search` 판단 기준을 추가한다.
  - 쓰는 경우: 설명·정의·비교형 질문이거나, 근거 확인 ①② 로도 없을 때.
  - 쓰지 않는 경우: 조건 질문(`query_plan`), 특정 엔티티(`describe_entity`), `policy.graph_fallback="none"` KB 에서 문서 근거를 찾으려 할 때.
  - 부를 때는 `answer=false` 로 근거만 받는다.

## 5. 파이프라인 구성: JSON + 버전 이력

### 5.1 구성 형식

지금 `pipeline_config` 형식에 머리 정보만 더한다.

```json
{
  "schema": "ragaas.pipeline/v1",
  "stages": [
    {"type": "gate", "params": {}},
    {"type": "graph", "params": {"max_hops": 6, "top_k": 10, "resolve_terms": true,
                                  "list_supplement": true, "graph_fallback": "vector",
                                  "llm_model_config": {}}}
  ]
}
```

- 스테이지 이름과 파라미터는 지금 실행기 계약(`model-config-and-pipeline-contract.md`)을 그대로 쓴다.
- 저장할 때 검증한다: `stages` 배열, 알려진 스테이지 종류, 파라미터 타입. 모르는 키는 경고만 하고 보존한다 (옛 버전을 불러올 때 깨지지 않게).

### 5.2 저장 구조 — 이력은 Git (고지라가 쓰는 Gitea)

이력은 직접 만든 버전 테이블이 아니라 **Git 커밋**으로 남긴다. 고지라가 쓰는 Gitea 를 함께 쓴다 (사용자 결정, 2026-11-17).

- **서버**: shared-infra 의 공용 Gitea (`shared-gitea`, `gitea/gitea:1.25.5` 고정, `http://192.168.219.115:44372/`, HTTP 만). 고지라의 Mac Gitea 를 데이터째 옮겨 켠다 (사용자 결정 2026-11-17 — 사내망 배포를 위해). 주소는 환경 변수 `GITEA_SERVER` 로만 둔다.
- **저장소**: `ragaas-pipelines` 하나, 기본 브랜치 `main`. KB 마다 파일 하나.

```
ragaas-pipelines/
  kb/<kb_id>/pipeline.json     # 5.1 형식 (운영 구성)
  kb/<kb_id>/README.md         # KB 이름 (사람이 Gitea 에서 볼 때)
```

- **커밋 = 버전.** 운영 반영 한 번이 커밋 하나다. 커밋 메시지는 반영 메모, 본문에는 바뀐 항목(`graph.max_hops 6 → 8`)을 적는다.
- 화면의 버전 번호(v12)는 그 파일의 커밋 순번이다. 실제 식별자는 커밋 SHA 다.
- **RAGaaS 쪽 저장 (Mongo, KB 문서)**

| 필드 | 내용 |
|---|---|
| `pipeline_config` | 운영 구성 (지금 필드 그대로). **검색은 이것만 읽는다** — Gitea 가 멈춰도 검색은 된다 |
| `pipeline_live_ref` | 운영 구성의 커밋 SHA |
| `pipeline_draft` | 테스트 탭에서 편집 중인 구성. 자주 바뀌므로 Git 에 넣지 않고 Mongo 에 자동 저장 |
| `pipeline_draft_base` | 테스트 구성이 어느 커밋에서 출발했는지 |

- **이관**: KB 마다 지금 `pipeline_config` 를 첫 커밋("초기 구성")으로 올리고 `pipeline_live_ref` 를 채운다. draft 는 같은 내용으로 시작.
- **자격 정보**: RAGaaS 전용 계정 `ragaas-bot` (`ragaas` 조직 Owners 팀)의 토큰을 `deploy/.env` 의 `GITEA_TOKEN` 에 둔다. 고지라의 토큰을 같이 쓰지 않는다.
  - 토큰 권한: **repository 읽기·쓰기 + organization 읽기·쓰기**. 조직 안에 저장소를 만들 때 Gitea 가 `write:organization` 을 요구한다 (organization 읽기만 주면 403 — 2026-11-17 확인).
  - 컨테이너는 `deploy/.env` 를 읽는다 (루트 `.env` 가 아님).

### 5.3 동작

| 동작 | 결과 |
|---|---|
| 테스트 탭에서 편집 | `pipeline_draft` 에만 자동 저장. 운영과 Git 은 그대로 |
| 테스트 탭 "반영" | 운영과의 차이·메모 확인 → Gitea 에 커밋 → 성공하면 `pipeline_config`·`pipeline_live_ref` 갱신 |
| 이력에서 "보기" | 그 커밋의 `pipeline.json` 과 이전 커밋과의 차이 |
| 이력에서 "테스트로 불러오기" | 그 커밋의 구성을 `pipeline_draft` 로 복사. 운영은 그대로 |
| 이력에서 "운영으로 되돌리기" | 그 커밋의 내용을 **새 커밋**("되돌림: v7")으로 올리고 운영 지정. 이력은 한 줄로만 쌓인다 (되돌림도 기록) |
| JSON 내보내기 / 가져오기 | 내보내기는 파일로 받기. 가져오기는 테스트 탭(draft)으로만 들어간다 |

- 반영 순서는 **Gitea 커밋 먼저, 성공해야 Mongo 갱신**이다. Gitea 가 안 되면 반영이 실패하고 운영은 그대로다 (이력 없는 운영 변경을 만들지 않는다).
- 같은 내용이면 커밋하지 않는다 (차이 0건이면 "반영할 변경 없음").
- Gitea 에서 사람이 직접 `pipeline.json` 을 고친 경우: 화면은 "Git 에 운영과 다른 최신 커밋이 있음" 으로 알리고, 테스트로 불러올 수만 있게 한다 (Git 을 고쳐도 바로 운영이 바뀌지는 않는다).
- 채팅 트레이스에 그때의 `pipeline_live_ref` 를 남겨, 결과를 그 커밋의 설정과 맞춰 볼 수 있게 한다.

### 5.4 API

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/knowledge-bases/{kb}/pipeline` | `{live: {ref, version, config}, draft, draft_base, dirty}`. 하위 호환으로 `stages`(운영)도 함께 |
| PUT | `/knowledge-bases/{kb}/pipeline/draft` | 테스트 구성 저장 |
| POST | `/knowledge-bases/{kb}/pipeline/publish` | `{note}` → Gitea 커밋 후 운영 지정 |
| GET | `/knowledge-bases/{kb}/pipeline/versions` | 커밋 목록 (순번, SHA, 시각, 메모, 운영 여부) — Gitea commits API |
| GET | `/knowledge-bases/{kb}/pipeline/versions/{ref}` | 그 커밋의 JSON |
| POST | `/knowledge-bases/{kb}/pipeline/versions/{ref}/load` | 그 커밋의 구성을 draft 로 복사 |
| POST | `/knowledge-bases/{kb}/pipeline/versions/{ref}/activate` | 그 내용을 새 커밋으로 올리고 운영 지정 |

- 기존 `PUT /pipeline` 은 `PUT /pipeline/draft` 로 동작을 바꾼다. 옛 화면이 운영을 덮어쓰지 않게 하기 위해서다.
- Gitea 호출은 REST(`/api/v1/repos/{owner}/{repo}/contents/...`, `/commits?path=`)로 한다. 서버에 작업 사본(clone)을 두지 않는다.

## 6. 화면

파이프라인 영역을 탭 두 개로 나눈다.

```
┌ [운영 v12] ─ [테스트 ●] ──────────────────────── [이력] ┐
│ 테스트: v12 에서 출발 · 운영과 다름 2곳                       │
│  Gate → Graph(Max Hop 8, Typo·Synonym 끔)                  │
│                         [운영으로 되돌리기] [운영에 반영…]    │
└──────────────────────────────────────────────────────────┘
```

- **운영 탭**: 읽기 전용. 지금 운영 버전 번호, 반영 시각과 메모를 보여 준다. 여기서 채팅하면 운영 설정으로 실행된다 (외부 에이전트가 받는 것과 같은 결과).
- **테스트 탭**: 편집할 수 있다. 여기서 채팅하면 draft 로 실행된다. 운영과 다르면 탭에 점(●)과 "다름 N곳" 을 표시한다.
  - "운영에 반영…": 차이 목록(예: `graph.max_hops 6 → 8`)과 메모 입력 → 확인.
  - "운영으로 되돌리기": draft 를 운영 구성으로 덮어쓴다 (확인).
- **이력 패널**: 버전 목록 → 보기 / 이전과 비교 / 테스트로 불러오기 / 운영으로 되돌리기. JSON 보기·내보내기·가져오기.
- 채팅 화면에는 지금 어느 탭(운영 v12 / 테스트)으로 묻고 있는지 표시한다.

## 7. 단계 계획

| 단계 | 내용 | 확인 |
|---|---|---|
| S1 | Gitea 저장소·토큰 준비, Git 연동 모듈, KB 필드, 이관(첫 커밋), `resolve_policy`, 버전 API | 단위 테스트(Gitea 모의), 실제 Gitea 에 KB 별 첫 커밋 |
| S2 | `search_entry.search` — 검색 필터 확인, 에이전틱 건너뛰기, `answer=false`, `applied_policy` / `/chat`·`/chat/stream`·`/retrieve`·MCP `search` 연결 | 채팅 회귀 (물리학사 몇 문항), MCP `search` 응답 시간 |
| S3 | MCP 조회 도구 정책 연동 (4장), `describe_kb.policy` | Graph 없는 KB·Typo 끈 KB 로 각 도구 확인 |
| S4 | 화면: 운영/테스트 탭, 반영·되돌리기, 이력 패널, JSON 보기 | 브라우저로 반영·불러오기 흐름 |
| S5 | 스킬 갱신, 설계서(MCP·계약 문서) 갱신, 결정 이력 | — |

- PR #68 (그래프 옵션 3개를 추가함) 머지 뒤 main 기준으로 진행한다. 화면(`PipelineBuilder.tsx`)과 실행기가 겹친다.

### 7.1 결과 (2026-11-17, 브랜치 `feat/search-entry-pipeline-versions`)

| 항목 | 결과 |
|---|---|
| 진입점 | 별도 `search_entry` 모듈 대신 **`/chat` 함수 자체를 단일 진입점**으로 (`/chat/stream`·MCP `search` 가 감쌈). 파라미터 `config`·`agentic`·`answer`·`caller`, 응답 `status`·`applied_policy` |
| 정책 해석 | `retrieval/search_policy.py` — `resolve_pipeline`, `summarize`, `guard`, `policy_view` |
| 검색 필터 없음 | `status=disabled`. 옛 '레거시 전략' 경로(파이프라인 없을 때 전략 이름으로 검색)는 제거 |
| MCP | `search` 에이전틱 건너뜀·근거만 (에이전틱 KB 4.6초, 답변 생성 없음). 조회 도구 6개 + REST `/agent/*` 에 `guard`, `lookup_values` Typo 연동, `describe_kb.policy` |
| 이력 | `services/pipeline_versions.py` — Gitea REST. KB 5개 첫 커밋, `test vec` 로 반영 → 이력 → 보기 → 불러오기 → 되돌리기 확인 (v1 → v2 → v3 '되돌림: v1') |
| 화면 | 운영/테스트 탭, 운영에 반영(차이·메모), 운영 구성으로 되돌리기, 이력 패널, JSON 내보내기·가져오기 |

**설계와 다르게 남긴 것**
- `/retrieve` (옛 검색 전용 API)는 손대지 않았다 — 화면·MCP 가 쓰지 않는다. 정리는 별도.
- MCP 조회 도구의 근거 청크에 **후처리 필터(Re-Rank 등)는 적용하지 않았다**. `get_chunks`·`query_plan` 에는 질문이 없어 리랭크 기준이 없다. `policy.post_filters` 로 알리기만 한다. `search` 는 파이프라인 전체를 타므로 적용된다.
- Max Hop 은 서버가 강제하지 않고 `policy.max_hops` 로 알린다 (설계대로).

## 8. 위험과 대응

| 위험 | 대응 |
|---|---|
| 옛 화면이나 외부 스크립트가 `PUT /pipeline` 으로 운영을 덮어씀 | `PUT /pipeline` 을 draft 저장으로 바꾼다. 운영 변경은 `publish`·`activate` 로만 |
| 옛 버전 JSON 이 지금 실행기와 안 맞음 (지운 옵션 등) | 모르는 키는 무시하고 보존한다. 불러올 때 "이 버전에는 지금 없는 옵션 N개" 를 알린다 |
| Gitea 장애·이관 중 | 검색은 Mongo 의 운영 구성만 읽어 영향 없음. 반영·이력 조회만 실패하고 화면에 알린다 |
| 반영과 동시에 들어온 요청 | 요청 시작 때 운영 버전 번호를 한 번 읽어 끝까지 그 구성으로 실행한다 |
| 정책 확인으로 MCP 조회 도구가 느려짐 | `resolve_policy` 는 KB 문서 하나를 읽는다. 버전 번호를 키로 메모리에 캐시한다 |

## 9. 남은 질문

- 운영 반영 권한: 지금은 사용자 구분이 없다. 권한 체계가 생기면 `publish`·`activate` 를 관리자 전용으로 둔다.
- 버전 보존 기간: Git 이력이라 무기한.
- 저장소 조직: `ragaas` 를 새로 만든다 (고지라 조직과 분리). 공용 Gitea 이관이 끝난 뒤 만든다.
- 선행 작업: 인프라 세션(compose·포트·복원)과 고지라 세션(백업·전환·웹훅) — 끝나야 S1 의 Git 연동을 실제 서버로 확인할 수 있다. 그 전에는 모의 서버로 개발한다.
