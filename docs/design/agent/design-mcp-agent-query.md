# 설계: 외부 에이전트용 MCP — 스키마를 받아 에이전트가 직접 질의

> **문서 상태 (2026-11-17)**: ✅ 현행 (2026-11-16 구현, ADR-004) · 지도: [`docs/README.md`](../../README.md)


작성일: 2026-11-16
상태: 초안 (구현 전)
관련: `docs/design/graph/design-graph-class-query.md`(질의 계획), `docs/design/graph/design-agentic-filter.md`, `docs/design/schema/design-schema-editor.md`,
`docs/platform-contract/05-backend-contract.md`(인증)

---

## 1. 배경

RAGaaS 를 MCP 로 외부 에이전트(Claude Code, GoJIRA 에이전트 등)에 제공하려 한다.
지금 검색은 RAGaaS 안에서 LLM 이 질문을 분석하고 질의를 계획한다. 그런데 호출하는 쪽도 LLM 에이전트라면,
**질문 해석은 호출하는 쪽이 하고 RAGaaS 는 스키마 제공과 조회만** 하는 편이 빠르고 정확할 수 있다.

### 1.1 검증 (2026-11-16, test-ontology2)

Claude(Opus 5.5)가 호출하는 에이전트 역할을 맡았다. Fuseki 를 직접 조회해 지금 검색(그래프 단독, 각 2회)과 비교했다.

| 질문 | 직접 조회 | 지금 검색 |
|---|---|---|
| 유지 보수성이 좋은 스타일은? | 0.06초 | 14.3초 / 15.8초 |
| 유지 보수성과 수정 용이성이 좋은 스타일은? | 0.06초 | 14.9초 / 15.3초 |
| 사전 조회 (관계 목록 + 값 어휘) | 0.12초 (KB 당 1회) | — |

직접 조회 시간에는 RAGaaS 쪽 LLM 호출이 없다. 호출하는 에이전트의 생각 시간은 빠져 있다.

**결과의 질**

| | 직접 조회 | 지금 검색 |
|---|---|---|
| 조건 해석 | '유지보수성' 값이 그래프에 없음을 값 목록으로 확인했다. 그래서 변경·테스트·관리 용이성과 "장기 유지보수 적합"으로 풀었다. '수정'은 '변경'으로 맞췄다. | 두 질문 모두 조건을 "변경 용이성" 하나로 줄였다. |
| 안정성 | 같은 질의는 같은 결과를 낸다. | 실행마다 5개 또는 6개, 조건도 바뀐다 (`has_positive_effect_on = …` / `contains …` / `has_moderate…`). |
| 순위·반대 근거 | Clean·Hexagonal 이 최상위다. Layered 의 부정 효과와 CQRS 의 긍정·부정 충돌(데이터 오류)도 드러났다. | 순위와 반대 근거가 없다. |
| 복합 조건(AND) | "변경 긍정 AND 다른 유지보수 신호"로 조회했다. | 두 번째 조건이 반영되지 않았다. |

**검증에서 드러난 필요 사항**

1. **값 어휘가 결정적이다.** 관계별로 실제 쓰인 값과 건수를 먼저 봐야 질문의 말을 그래프의 값으로 맞출 수 있다. 이 단계가 없으면 빈 결과가 나온다.
2. **그래프 구조 지식이 필요했다.** 이름은 `rdfs:label` 에 있다. 문서별 named graph 를 쓴다. 근거 청크는 `rdf:subject/predicate/object` + `meta:sourceNodeId` 에 있다. 에이전트에게 이것까지 요구하면 안 된다. 도구가 감춰야 한다.
3. **근거 원문 도구가 필요하다.** 조회 결과는 청크 ID까지만 준다. 원문은 Milvus 에 있다.
4. **YAML(구조화) KB 는 원문 SPARQL 로는 어렵다.** 목록 항목이 구조 노드를 거친다. PR #58 의 조인 버그가 이 지점에서 났다. 질의 계획 JSON 이 필요하다.

---

## 2. 목표 / 비목표

**목표**

- 호출하는 에이전트가 **스키마 받기 → 값·엔티티 확인 → 질의 작성 → 조회 → 근거 원문 회수**를 MCP 도구로 할 수 있다.
- 조회 경로에서 RAGaaS 쪽 **LLM 호출 0회**. 목표 응답 시간은 1초 미만이다.
- 외부 계약은 **질의 계획 JSON** 하나다. 원문 SPARQL 은 관리자·디버깅용으로만 둔다 (§9).
- 사용법을 담은 **스킬**(`ragaas-query`)을 함께 배포한다.

**비목표**

- 답변 문장 생성. 근거만 주고, 답은 호출하는 쪽이 쓴다. 답변까지 원하면 기존 `search` 도구를 쓴다.
- 쓰기 (스키마 편집, 문서 적재). 이번 범위는 읽기만이다.
- Neo4j 백엔드는 1차 구현 범위 밖이다. 단, 계약(`query_plan`)은 Neo4j 를 전제로 설계하고 P7 에서 지원한다 (§9).

---

## 3. 흐름

```
① describe_kb ─→ ② lookup_values / resolve_entities ─→ ③ 질의 작성(에이전트) ─→ ④ query_plan | sparql ─→ ⑤ get_chunks
      ▲                                                                              │
      └──────────────────────── 결과가 비거나 모자라면 다시 ────────────────────────────┘
```

| 단계 | 누가 | 하는 일 | 빈도 |
|---|---|---|---|
| ① | RAGaaS | 유형(클래스), 경로(관계·속성), 정의, 값 어휘 요약, 스키마 버전 | KB 당 1회 (버전이 바뀔 때만 다시) |
| ② | RAGaaS | 질문 속 말 → 그래프 값·엔티티 후보 (별칭·표기 차이 흡수) | 질문마다, 필요할 때 |
| ③ | 에이전트 | 질의 계획 JSON 또는 SPARQL 작성 | 질문마다 |
| ④ | RAGaaS | 검증 → 컴파일 → 실행 → 트리플 + 근거 청크 ID | 질문마다 1~3회 |
| ⑤ | RAGaaS | 청크 ID → 원문, 문서명 | 필요할 때 |

---

## 4. 도구 명세

공통:

- 모든 도구는 `kb_id` 를 받는다.
- 응답에는 `schema_version` 이 들어간다. 값은 스키마 저장 시각 + 카탈로그 해시다.
- 에이전트가 가진 버전과 다르면 응답에 `stale_schema: true` 가 붙는다. 이때 ①을 다시 받는다.

### 4.1 `list_kbs`

이 사용자가 쓸 수 있는 KB 목록이다.

- 각 KB 의 이름, 설명, 그래프 백엔드, 질의 가능 여부(ontology + 승격됨), 문서 수를 준다.

### 4.2 `describe_kb` (①)

```jsonc
// 입력
{"kb_id": "…", "max_values_per_path": 30}
// 출력
{
  "schema_version": "2026-11-16T07:10:00Z#a1b2c3",
  "kb": {"name": "test-ontology2", "kind": "text|structured"},
  "kinds": [                                   // 결과로 돌려받을 수 있는 엔티티 유형
    {"name": "ArchitectureStyle", "description": "…", "members": 11,
     "examples": ["Microservices", "CQRS", "…"]}
  ],
  "paths": {                                   // 유형별 조회 가능한 경로 (질의 계획의 path 로 쓰는 키)
    "ArchitectureStyle": [
      {"key": "has_positive_effect_on", "type": "enum", "description": "강한 긍정 효과를 주는 품질 속성",
       "family": "effect", "polarity": "positive", "strength": "strong",      // 계열 정보 (있을 때)
       "equiv": [], "coverage": 0.82,
       "values": [{"label": "변경 용이성", "members": 5}, {"label": "확장성", "members": 4}, "…"],
       "values_truncated": false},
      {"key": "is_suitable_for", "type": "text", "examples": ["장기 유지보수 요구가 높다", "…"], "distinct": 61},
      {"key": "metadata.ops_complexity", "type": "enum", "values": [{"label": "low", "members": 4}, "…"]}  // 구조화 KB 예
    ]
  },
  "notes": ["text 경로는 contains 로 조회", "같은 계열(effect) 관계는 강도별로 나뉘어 있음 — 긍정 전체는 OR 로"]
}
```

- 출처: 질의 계획에 쓰는 카탈로그(`FusekiBackend._class_catalog`)와 스키마 편집기 spec(`schema_editor.get_spec`)이다.
- 카탈로그에는 이미 enum 값과 멤버 수가 들어 있다(`class_query._path_line_base`). 새로 만들 것은 출력 형식뿐이다.
- `family/polarity/strength` 는 `schema_editor.family_key` 로 붙인다. 강한·중간 긍정을 AND 로 묶는 실수(11/16 관찰)를 에이전트가 피할 수 있게 하려는 것이다.
- 크기: test-ontology2 는 경로 40여 개, 값 상위 30개로 대략 8~15KB 다. 너무 크면 `kinds` 로 거른다.

### 4.3 `lookup_values` / `resolve_entities` (②)

```jsonc
// lookup_values: 말 → 값 후보 (경로별)
{"kb_id": "…", "terms": ["유지보수성", "수정 용이성"], "kind": "ArchitectureStyle"}
→ {"matches": {
     "유지보수성": [],                                         // 정확히 일치하는 값 없음 → 에이전트가 풀어서 판단
     "수정 용이성": [{"path": "has_positive_effect_on", "value": "변경 용이성", "score": 0.86, "via": "embedding"}]
   },
   "related": {"유지보수성": [{"path": "is_suitable_for", "value": "장기 유지보수 요구가 높다", "via": "contains"}]}}

// resolve_entities: 이름 → 엔티티
{"kb_id": "…", "names": ["마이크로서비스", "헥사고날"]}
→ {"entities": {"마이크로서비스": [{"label": "Microservices", "kind": "ArchitectureStyle", "via": "alias"}], "…": []}}
```

- 둘 다 LLM 을 쓰지 않는다.
- 일치 순서: 정확 일치 → 별칭(`skos:altLabel`, 스키마 멤버 별칭) → `entity_linking._compact` 정규화 → 포함(contains) → 임베딩 유사도(값 라벨 임베딩을 캐시해 둔다).
- '유지보수성'처럼 상위 개념은 값으로 없을 수 있다. 이때는 빈 결과 + 관련 후보를 주고, 판단은 에이전트에게 맡긴다. 검증에서 이렇게 하는 쪽이 정확했다.

### 4.4 `query_plan` (④, 기본)

지금 내부 질의 계획 JSON(`class_query.build_plan_messages`)을 외부용으로 다듬은 형식이다.

내부 형식과 다른 점:

- path 는 **번호가 아니라 키**다. 번호는 카탈로그 순서에 따라 바뀌기 때문이다.
- **OR 를 지원**한다.

```jsonc
{
  "kb_id": "…",
  "schema_version": "…",                       // 선택. 다르면 stale_schema 경고
  "kind": "ArchitectureStyle",
  "where": {                                   // 조건 트리: all(AND) / any(OR) / 단일 조건
    "all": [
      {"any": [
        {"path": "has_positive_effect_on",          "op": "eq", "value": "변경 용이성"},
        {"path": "has_moderate_positive_effect_on", "op": "eq", "value": "변경 용이성"}
      ]},
      {"any": [
        {"path": ["has_positive_effect_on", "has_moderate_positive_effect_on"], "op": "in",
         "value": ["테스트 용이성", "관리 용이성"]},
        {"path": "is_suitable_for", "op": "contains", "value": "유지보수"}
      ]}
    ]
  },
  "return": ["has_positive_effect_on", "has_moderate_positive_effect_on", "has_moderate_negative_effect_on"],
  "rank_by": {"count_matched": true},          // 선택: 충족한 조건 수로 정렬
  "aggregate": null,                           // count | max | min | count_members (내부 형식과 같음)
  "limit": 50,
  "include_evidence": true                     // 트리플별 근거 청크 ID
}
```

**연산자**

- 지금과 같다: `eq | ne | in | contains | gt | gte | lt | lte | exists | not_exists`
- `path` 에 배열을 주면 그 경로들 중 하나다(OR). 지금 내부 형식에도 있는 기능이다.

**출력**

```jsonc
{
  "status": "ok|zero|reject",                  // reject 면 message 에 이유와 고칠 방법
  "schema_version": "…",
  "entities": [
    {"label": "Clean Architecture", "matched": 2,
     "values": {"has_positive_effect_on": ["변경 용이성", "테스트 용이성"], "has_moderate_negative_effect_on": ["단순성"]},
     "evidence": [{"s": "Clean Architecture", "p": "has_positive_effect_on", "o": "변경 용이성",
                   "chunk_ids": ["74b7afab-…"], "doc": "clean-architecture.md"}]}
  ],
  "total": 6,
  "adjustments": ["'수정 용이성' 은 값 목록에 없어 zero 처리됨 — lookup_values 로 확인하세요"],
  "sparql": "…",                               // 실제 실행한 SPARQL (디버깅·학습용)
  "elapsed_ms": 61
}
```

**검증 규칙** (내부 `validate_plan` 을 그대로 쓴다)

- 모르는 경로나, 타입과 맞지 않는 연산자 → 계획 전체 `reject`. 필터를 버리고 넓게 찾으면 오답이 되기 때문이다.
- enum 경로에 없는 값 → `zero` (빈 결과 확정). `adjustments` 에 "lookup_values 로 확인" 안내를 넣는다.
- 동치 경로(`equiv`)는 자동으로 함께 조회한다. 구조화 KB 의 구조 노드 조인은 `compile_member_query` 가 처리한다(PR #58).

**구현**

- `validate_plan` 과 `compile_member_query` 는 지금 AND 만 받는다.
- 조건 트리(all/any)를 받도록 넓힌다. `any` 는 SPARQL `UNION` 이나 `FILTER(… || …)` 로 바꾼다.
- 내부 질의 계획 LLM 도 같은 형식을 쓰게 하면, 11/16 의 AND/OR 흔들림도 함께 고칠 수 있다.

### 4.5 `sparql` (④, 관리자·디버깅 전용 — §9-5)

```jsonc
{"kb_id": "…", "query": "SELECT …", "limit": 500, "timeout_ms": 5000}
→ {"vars": [...], "rows": [...], "truncated": false, "elapsed_ms": 58}
```

- **읽기 전용**: Fuseki `/query` 엔드포인트만 쓴다(업데이트 불가). 질의를 파싱해 `SELECT | ASK | CONSTRUCT | DESCRIBE` 만 허용한다.
- **KB 범위**: KB 마다 Fuseki 데이터셋이 따로라서 엔드포인트가 범위를 강제한다. 다른 데이터셋으로 나가는 `SERVICE` 절은 거부한다.
- **제한**: 결과 행 상한(기본 500, 최대 5000), 시간 제한(기본 5초, 최대 20초). 사용자별 동시 2개.
- 응답에 그래프 구조 안내 링크(`describe_kb.notes`)를 넣는다. 스킬에 SPARQL 패턴(라벨, 근거 청크 조인)을 싣는다.

### 4.6 `get_chunks` (⑤)

```jsonc
{"kb_id": "…", "chunk_ids": ["74b7afab-…", "…"], "max_chars": 1500}
→ {"chunks": [{"id": "…", "doc": "clean-architecture.md", "section": "품질 속성", "text": "…"}]}
```

- 기존 `GET /{kb}/chunks/{chunk_id}` 를 여러 건 묶어 조회하는 형태다(Milvus `query` 한 번).
- 구조화 KB 의 `{doc}::struct::{node}` ID 는 레코드 원문(YAML 조각)으로 돌려준다.

### 4.7 `search` (대체 수단)

- 지금 `/chat` 검색이다. 자연어를 넣으면 근거가 나오고, 원하면 답변도 준다.
- 질의 작성이 어렵거나 문서형 질문(정의, 설명)일 때 쓴다.
- 기본값은 `answer: false` (근거만)다. 이때 답변 LLM 을 생략해 6~8초를 아낀다.
- 에이전틱 필터는 기본 끈다. 호출하는 쪽이 이미 에이전트라 루프가 이중이 된다.

---

## 5. 노출 방식

| 계층 | 위치 | 비고 |
|---|---|---|
| REST | `backend/app/api/agent_query.py` → `/api/v2/knowledge-bases/{kb}/agent/{describe,values,entities,plan,sparql,chunks}` | MCP 가 아닌 클라이언트도 사용. 테스트 용이 |
| MCP 서버 | `backend/app/mcp/server.py` — Python `mcp` SDK, Streamable HTTP. FastAPI 에 `/mcp` 로 마운트 | 도구는 REST 핸들러와 같은 서비스 함수를 부른다 |
| 게이트웨이 | `/ragaas/mcp` → `ragaas-backend:8000/mcp` | GoJIRA 공용 게이트웨이 설정에 location 추가 필요 (GoJIRA 쪽 변경) |

**인증**: 플랫폼 계약 05 를 따른다.

- 사람이 쓰는 클라이언트는 `Authorization: Bearer <SSO 토큰>`.
- 서비스(GoJIRA 에이전트)는 서비스 토큰 + `X-User-Id`.
- KB 접근 권한은 기존 KB API 와 같은 검사를 한다.
- 개발 모드에서는 지금처럼 폴백한다.

**운영**

- 도구 호출은 `chat_traces` 와 같은 방식으로 기록한다(`agent_traces`: 도구, 입력, 결과 수, 시간, 사용자).
- 어떤 질의가 zero·reject 를 많이 내는지 보고 스키마와 스킬을 개선한다.

---

## 6. 스킬: `ragaas-query`

위치: `skills/ragaas-query/SKILL.md` (저장소에 두고 배포한다). Claude Code 와 GoJIRA 에이전트가 같은 스킬을 쓴다.

**구성**

1. **언제 쓰나**: RAGaaS KB(아키텍처 스타일, 물리학사 등)에 사실·목록·비교 질문을 할 때.
2. **순서**: `describe_kb`(캐시, 버전 확인) → 질문의 말을 `lookup_values`·`resolve_entities` 로 그래프 값에 맞춤 → `query_plan` 작성 → 비거나 `zero` 면 값 확인 후 다시 → 근거가 필요하면 `get_chunks` → 답변.
3. **질의 작성 규칙** (검증과 지금까지의 오류에서 나온 것):
   - 상위 개념(유지보수성, 안정성)은 값 목록에서 하위 속성으로 풀고, **푼 방식을 답변에 밝힌다**.
   - 같은 계열 관계(강한·중간 긍정)는 `any` 로 묶는다. AND 로 묶지 않는다.
   - 반대 근거(부정 효과)도 `return` 에 넣어 함께 확인한다. 긍정과 부정이 함께 있으면 데이터 충돌로 보고한다.
   - text 경로는 `contains`, enum 경로는 목록에 있는 표기 그대로 쓴다.
   - 질문에 없는 사용자 상황은 가정으로 밝힌다.
4. **답변 규칙**: 트리플만 믿지 말고 핵심 근거는 `get_chunks` 원문으로 확인한다. 출처(문서명)를 표기한다.
5. **예시 3개**: 단순 조건("유지 보수성이 좋은 스타일"), 복합 조건(AND+OR), 집계("단점이 가장 많은 스타일"). 각각 계획 JSON 과 결과를 싣는다.
6. **SPARQL 부록**: 그래프 구조(라벨, named graph, 근거 청크 조인 패턴). `query_plan` 으로 안 되는 질문(유형 간 조인 등)용이다.

---

## 7. 단계 계획

| 단계 | 내용 | 확인 |
|---|---|---|
| P1 | REST: `describe`, `values`, `entities`, `chunks`, `sparql` (기존 함수 재사용, 형식만) | test-ontology / 2 / 3 응답 크기·시간 |
| P2 | `query_plan`: 조건 트리(all/any) + key 기반 path. `validate_plan` 과 `compile_member_query` 확장. 내부 계획 LLM 도 같은 형식으로 | 기존 질의 계획 테스트 + 신규(OR, 순위) |
| P3 | MCP 서버(`/mcp`) + 인증 + `agent_traces` | Claude Code 에서 MCP 연결해 도구 호출 |
| P4 | 스킬 `ragaas-query` 작성 | 아래 평가 |
| P5 | ~~게이트웨이 `/ragaas/mcp`~~ — 불필요 (기존 `/ragaas/api/` 규칙으로 `/ragaas/api/mcp/` 사용, §7.3) | 게이트웨이 경유 호출 확인 |
| P6 | GoJIRA style-define 스킬을 MCP `query_plan` 으로 전환 | GoJIRA 쪽 수정 |
| P7 | Neo4j: 카탈로그 추출 + `query_plan` → Cypher 컴파일러 | 같은 계획 JSON 으로 Fuseki·Neo4j KB 결과 비교 |

**평가**

- Claude Code + 스킬 + MCP 로 아래 질문을 풀고, 지금 검색과 정답률·시간을 비교한다.
  - 물리학사 39문항(test-ontology3)
  - test-ontology / test-ontology2 질문 세트: 11/16 의 두 질문, "4종 서비스…", "배포 용이성과 수정 용이성…"
- 기준: 정답률이 지금 이상이고, RAGaaS 쪽 응답이 질문당 1초 미만(도구 호출 합계).

---

### 7.1 P1 결과 (2026-11-16)

구현: `backend/app/services/agent_query/catalog.py`, `backend/app/api/agent_query.py`, 테스트 `backend/tests/test_agent_query.py`.

| 엔드포인트 | test-ontology2 (text) | test-ontology (YAML) | test-ontology3 (물리학사) |
|---|---|---|---|
| `GET …/agent/describe` | 144ms · 17KB · 경로 40 | 127ms · 29KB · 경로 95 | 288ms · 32KB · 경로 111 |
| `POST …/agent/values` | 63ms | | |
| `POST …/agent/entities` | 43ms | | |
| `POST …/agent/chunks` | 77~210ms (Milvus) | | |
| `POST …/agent/sparql` | 기본 꺼짐 (`AGENT_SPARQL_ENABLED=true` 일 때만, SELECT 만, 동시 2) | | |

**확인된 점**

- 관계 계열이 표시된다 (`has_moderate_negative_effect_on` → polarity=negative, strength=moderate, family=has_effect_on).
- text 경로라도 값이 짧은 라벨이면 어휘로 준다 (`has_positive_effect_on` 값 19종).
- 유형마다 멤버 이름 목록(`member_names`, 최대 150개)을 준다.
- 청크는 문서명을 함께 준다 (Milvus 메타데이터가 비어 있어 `doc_id → Document.filename`).

**드러난 한계 → 다음 단계에서 보강**

1. `lookup_values("수정 용이성")` 은 빈 결과다. 그래프 표기가 '변경 용이성'이라 문자열 일치로는 못 찾는다.
   → 값 라벨 임베딩 유사도를 추가한다 (§4.3). 그 전까지는 에이전트가 `describe` 의 값 어휘를 보고 직접 맞춘다.
   11/16 검증에서도 이렇게 했다.
2. `resolve_entities("마이크로서비스" / "헥사고날")` 는 빈 결과다. 그래프에 한글 음역 별칭이 없다.
   → 에이전트가 `member_names` 로 맞추게 스킬에 적는다. 별칭 보강은 스키마 편집기(멤버 별칭)에서 한다.
3. 멤버 이름은 URI 로컬명에서 만든다. 구조화 KB 는 소문자 키(`hexagonal`)로 보인다.
   → P2 에서 `rdfs:label` 로 바꾼다 (한 번의 SPARQL, 카탈로그와 함께 캐시).

### 7.2 P2 결과 (2026-11-16) — `POST …/agent/plan`

구현: `backend/app/services/agent_query/plan.py`.
기존 `class_query.validate_plan` / `compile_member_query` / `compile_evidence_query` 를 재사용한다.

**실행 방식**

1. 조건 트리(all / any)를 DNF(OR of AND)로 펼친다. 상한: 묶음 16개, 조건 12개, 묶음당 4개.
2. AND 묶음마다 기존 검증·컴파일러로 한 질의를 만든다. 구조화 KB 의 "같은 목록 항목" 조건은 컴파일러가 구조 노드 변수를 공유해 지킨다 (PR #58).
3. 묶음 결과의 합집합이 최종 결과다. 조건마다 따로 조회해 엔티티별 충족 조건 수(`matched`)를 세고, 그 수로 정렬한다.
4. **AND 결과가 0이어도 OR 로 완화하지 않는다.** 내부 검색은 완화하지만, 외부 계약에서는 논리를 에이전트가 정한다. 결과가 없으면 `zero` 와 이유를 돌려준다.

**검증기 변경** (내부 동작은 그대로)

- path 에 key 문자열을 허용한다. 번호는 지금처럼 쓴다.
- text 경로에 `in` 을 허용한다. 내부 LLM 프롬프트는 계속 eq / contains 만 안내한다.
- `strict=True` (외부 계획):
  - text 경로의 느슨한 '라벨 유사' 일치를 하지 않는다. 추측하지 않고 `zero` 를 낸다.
  - 필터 수가 상한을 넘으면 잘라내지 않고 반려한다.

**확인** (11/16 수작업 SPARQL 검증과 같은 결과)

| 질의 | 결과 | 시간 |
|---|---|---|
| test-ontology2 "유지 보수성이 좋은 스타일" (any: 긍정 계열 in [변경·테스트·관리 용이성], 적합 contains '유지보수') | 7개. Clean·Hexagonal 이 matched 2 로 위. CQRS 는 부정 효과에도 '변경 용이성'이 있어 충돌이 드러남 | 229ms |
| test-ontology2 "유지 보수성과 수정 용이성" (all: 변경 용이성, any: 테스트·관리 / 유지보수 적합) | Clean·Hexagonal (3) → Micro-Frontend·Modular Monolith (2) | 94ms |
| test-ontology (YAML) 같은 품질 항목에서 attribute=modifiability AND effect=positive AND strength=high | Clean·Hexagonal·Micro-Frontend·Microservices. 원본 대조 일치 (CQRS·Modular=medium, Layered=negative 제외) | 108ms |

**배포 주의**: 구조화 KB 의 항목 조건 상관은 PR #58 의 `compile_member_query` 수정에 의존한다.
이 브랜치(main 기준)에는 그 수정이 없다. **#58 을 먼저 머지**해야 한다.

### 7.3 P3 결과 (2026-11-16) — MCP 서버

구현: `backend/app/mcp_server.py`. Python MCP SDK 2.3.0 의 `MCPServer` 를 쓴다 (`requirements.txt` 에 `mcp==2.3.0`).

- 전송: Streamable HTTP, stateless, JSON 응답. FastAPI 에 `/api/mcp` 로 마운트했다.
  - 게이트웨이 주소는 **`/ragaas/api/mcp/`** 다. 기존 `/ragaas/api/` 규칙이 그대로 넘기므로 **게이트웨이 변경이 필요 없다** (P5 불필요).
- 도구 7개: `list_kbs`, `describe_kb`, `lookup_values`, `resolve_entities`, `query_plan`, `get_chunks`, `search`.
  - REST 와 같은 서비스 함수를 쓴다. 원문 `sparql` 은 MCP 에 노출하지 않는다.
- 인증은 앱 전역 `platform_auth` 미들웨어가 한다.
  - SSO 모드에서는 MCP 클라이언트가 `Authorization: Bearer` 를 보내야 한다.
  - 서비스(GoJIRA)는 서비스 토큰 + `X-User-Id` 를 보낸다.
- DNS rebinding 보호는 `MCP_ALLOWED_HOSTS` 가 있을 때만 켠다. 폐쇄망 + 게이트웨이 + 인증 뒤가 기본 구성이다.
- 확인: 게이트웨이 경유로 initialize → tools/list → tools/call 을 했다 (헥사고널 → Hexagonal 아키텍처, query_plan 4건, get_chunks 원문).

**Claude Code 연결**

```bash
claude mcp add --transport http ragaas http://<호스트>:44300/ragaas/api/mcp/
```

## 8. 위험과 대응

| 위험 | 대응 |
|---|---|
| 에이전트가 잘못된 계획을 보냄 | 검증에서 reject. 이유와 고칠 방법을 메시지로 준다. zero 는 lookup_values 안내 |
| 스키마 변경으로 에이전트 캐시가 낡음 | `schema_version` 비교 → `stale_schema` |
| 무거운 SPARQL | 시간·행 제한, 사용자별 동시 2개. Fuseki 는 공유 인프라(.115)라 전체 동시 상한도 둔다 |
| 데이터 오류가 그대로 노출 (예: CQRS 변경 용이성 긍정·부정 충돌) | 숨기지 않는다. 응답에 충돌 표시를 넣고, 스키마 편집기의 불일치 목록과 연결한다 |
| `describe_kb` 가 큰 KB 에서 너무 큼 | `kinds` 필터, 값 상위 N 개, 경로 정의는 요약 |
| 외부 에이전트가 다른 사용자 KB 조회 | KB 권한 검사 (기존 KB API 와 같은 규칙) |

---

## 9. 결정 사항 (2026-11-16)

1. **사용 환경**: 운영 시 사내 폐쇄망에서 쓴다. 외부 노출과 외부용 토큰 발급 흐름은 범위 밖이다.
2. **안전장치는 읽기 전용만이 아니다.** 아래를 모두 건다. 폐쇄망이라도 에이전트의 *실수*(카테시안 곱, 전체 정규식)는 막아야 한다. Fuseki 는 공유 인프라라 한 쿼리가 다른 서비스까지 멈출 수 있다.
   - 읽기 전용
   - KB 범위 + `SERVICE` 금지
   - 시간·행 제한, 사용자·전체 동시 상한
   - Fuseki 자격정보 비노출
3. **GoJIRA 연동**: GoJIRA style-define 스킬도 이 MCP 를 쓴다. 완료 후 GoJIRA 쪽을 수정한다 (별도 작업).
4. **Neo4j 지원**: 우선 Jena+Fuseki 로 구현하고, 최종적으로 Neo4j 도 지원한다.
   - 그래서 **외부 계약은 백엔드와 무관한 `query_plan` 하나로 고정**한다.
   - 컴파일러를 백엔드별로 둔다: Fuseki → SPARQL (지금 `compile_member_query`), Neo4j → Cypher (추가).
   - `describe_kb`·`lookup_values`·`get_chunks` 의 출력 형식도 백엔드와 무관하게 유지한다.
5. **원문 질의 도구(`sparql`, 나중에 `cypher`)는 관리자·디버깅 전용**이다. 에이전트와 GoJIRA 는 `query_plan` 만 쓴다.
   - 근거 1: 원문 질의는 틀려도 오류 없이 그럴듯한 결과를 낸다(PR #58 조인 버그, 11/16 AND/OR). `query_plan` 은 검증기가 걸러 준다.
   - 근거 2: 원문 질의는 내부 그래프 표현과 백엔드에 결합된다.
   - 원문 도구는 `query_plan` 으로 표현할 수 없는 질문을 찾아 계획 형식을 넓히는 데 쓴다.
   - 속도 차이는 없다. 11/16 검증의 0.06초는 SPARQL 이라서가 아니라 RAGaaS 쪽 LLM 호출이 없어서 나온 것이다.

## 10. 남은 질문

1. 폐쇄망 운영 시 LLM(GLM-5 계열)과 임베딩 엔드포인트 — `lookup_values` 의 임베딩 일치가 사내 임베딩 모델로 동작하는지 확인 필요.
2. Neo4j KB 의 그래프 표현(레이블·관계 타입·근거 청크 연결)을 Fuseki 와 같은 카탈로그 형식으로 뽑을 수 있는지 — Neo4j 컴파일러 착수 전에 조사.
