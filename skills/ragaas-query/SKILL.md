---
name: ragaas-query
description: RAGaaS 지식 그래프(KB)에 사실·목록·비교·집계 질문을 할 때 사용. 스키마를 받아 질문을 질의 계획(query_plan)으로 직접 만들어 조회하고, 근거 원문으로 확인해 답한다. 아키텍처 스타일 선택, 물리학사 같은 RAGaaS KB 질문, "~한 X는?", "X와 Y를 모두 만족하는", "가장 많은", "X의 스승의 스승" 같은 질문에 쓴다.
---

# RAGaaS 지식 그래프 조회

RAGaaS MCP 도구(또는 같은 REST)로 KB 를 조회한다. **질문 해석과 질의 작성은 네가 하고, RAGaaS 는 검증·실행만 한다.**
RAGaaS 쪽에는 LLM 이 없어 빠르다 (도구 호출당 0.1~0.3초). 대신 질의가 정확해야 한다.

## 도구

| MCP 도구 | REST (`{base}` = `…/ragaas/api/v2/knowledge-bases/{kb_id}`) | 용도 |
|---|---|---|
| `list_kbs` | `GET …/ragaas/api/v2/knowledge-bases/` | KB 목록. 조회 가능 = `graph_backend` 가 `ontology` |
| `describe_kb` | `GET {base}/agent/describe?format=compact` | 스키마: 유형·멤버 이름·경로(key, 정의, 계열·부호·강도, 값 어휘) |
| `lookup_values` | `POST {base}/agent/values` `{"terms": [...], "terms_en": {...}}` | 질문 속 말 → 그래프 값 |
| `resolve_entities` | `POST {base}/agent/entities` `{"names": [...], "names_en": {...}}` | 이름 → 그래프 엔티티 |
| `describe_entity` | `POST {base}/agent/entity` `{"name", "name_en"}` | 엔티티 하나의 관계 전부 (out / in) + chunk_ids |
| `query_plan` | `POST {base}/agent/plan` `{"kind", "where", "return", "aggregate", ...}` | 조회 실행 |
| `get_chunks` | `POST {base}/agent/chunks` `{"chunk_ids": [...]}` | 근거 원문 + 문서명 |
| `search` | `POST {base}/chat` `{"query"}` | 자연어 검색 (느림, 수십 초). 마지막 수단 |

MCP 의 `query_plan` 은 반환 경로를 `return_paths` 로, REST 는 `return` 으로 받는다.
예시 5개(조건 하나, 복합, YAML 같은 항목, 집계, 관계 따라가기)는 `examples.md` 에 있다 — 질의가 처음이면 읽는다.

## 순서

1. **스키마** — `describe_kb` 를 KB 당 한 번 받아 둔다. 응답의 `schema_version` 이 바뀌면 다시 받는다.
   compact 형식의 경로 한 줄: `key [type, 계열:부호/강도] — 정의: 값(엔티티 수), …`.
   엔티티 1개만 가진 경로는 숨겨져 있다 (`rare_paths_hidden`). 특정 엔티티의 사실은 `describe_entity` 로 본다.
   **특정 엔티티를 묻는 질문**("볼츠만의 소속은?", "파인만에 대해")은 바로 `describe_entity` 를 쓴다. 질의 계획보다 빠르고 확실하다.
2. **말 맞추기** — 질문의 엔티티·값을 그래프 표기로 바꾼다.
   - 엔티티(인물, 스타일 이름 등)는 `resolve_entities`, 조건 값(품질 속성, 상, 연도 등)은 `lookup_values` 에 넣는다.
   - **원문과 영어 표기를 함께 보낸다.** 오탈자는 고쳐서 영어로: `{"terms": ["헥사고널"], "terms_en": {"헥사고널": "Hexagonal"}}`.
   - `describe_kb` 의 값·멤버 목록에서 그대로 찾을 수 있으면 이 단계는 건너뛰어도 된다.
   - `matches` 가 비면 그 값은 그래프에 없다. `narrower`(상위 개념을 하위 값으로 푼 것), `related`(포함 일치), `suggestions`(확정 못 한 후보)를 본다.
3. **질의 계획 작성** — 아래 형식과 규칙대로.
4. **실행** — `query_plan`. 결과가 `zero`·`reject` 면 `message` 를 읽고 고쳐서 다시 (최대 2~3회).
5. **근거 확인** — 답의 핵심 근거는 `entities[].evidence[].chunk_ids` 로 `get_chunks` 원문을 확인한다. 트리플만 믿지 않는다.
   - **연도·날짜는 대부분 원문에만 있다** (그래프 값에 섞여 있거나 없음). 연도를 묻는 질문은 청크를 읽는다.
   - **관계 방향이 뒤집힌 트리플이 있다** (추출 오류). 방향이 답을 좌우하면(스승↔제자, 영향을 줌↔받음) 원문으로 확인한다.
6. **답변** — 질문한 언어로. 출처 문서명을 적고, 해석·가정을 밝힌다 (아래 "답변 규칙").

## 질의 계획 형식

```jsonc
{
  "kind": "ArchitectureStyle",                // describe_kb 의 kinds[].name
  "where": {                                   // 조건 트리 — 생략하면 그 유형 전체
    "all": [                                   // all = AND
      {"path": "consistency_model", "op": "eq", "value": "eventual"},
      {"any": [                                // any = OR
        {"path": ["has_positive_effect_on", "has_moderate_positive_effect_on"], "op": "in", "value": ["테스트 용이성", "관리 용이성"]},
        {"path": "is_suitable_for", "op": "contains", "value": "유지보수"}
      ]}
    ]
  },
  "return": ["has_moderate_negative_effect_on"],   // 결과마다 함께 볼 경로 (최대 6)
  "aggregate": null,                           // 집계 (아래)
  "rank_by": "matched",                        // 충족 조건 수로 정렬 (기본)
  "limit": 50
}
```

**조건(leaf)**: `{"path": key 또는 [key, ...], "op": 연산자, "value": 값}`

| type | 연산자 |
|---|---|
| enum | `eq`, `ne`, `in`(값 배열), `contains`(부분 문자열: '노벨' → '노벨 물리학상 (1933년)' 등 모두), `exists`, `not_exists` |
| text | `eq`, `in`, `contains`(부분 문자열), `exists`, `not_exists` |
| number | `eq`, `ne`, `in`, `gt`, `gte`, `lt`, `lte`, `exists`, `not_exists` |

- `path` 배열은 "그 경로들 중 하나"(OR)다. 같은 값을 여러 관계에서 찾을 때 쓴다.
- `value` 는 `describe_kb` 의 `values[].label` 표기 그대로 쓴다. 목록에 없는 값은 `zero` 가 된다 (서버가 추측하지 않음).
- 한 AND 묶음의 조건은 최대 4개. any 를 펼친 조합은 최대 16개. 조건 전체는 최대 12개.
- 구조화(YAML) KB 의 `a.b` 경로(예: `quality_attributes.attribute`, `quality_attributes.effect`)를 같은 `all` 에 넣으면 **같은 목록 항목**에서 함께 만족해야 한다.

**집계**: `{"fn": "count" | "max" | "min" | "count_members", "path": key, "value": 값(선택), "order": "desc" | "asc", "limit": 1, "having": {"op": "gte", "value": 3}}`

- `count` 는 경로 값 개수로 순위를 매긴다. `value` 를 주면 그 값만 센다.
- `count_members` 는 조건을 만족하는 엔티티 수다.
- `max` / `min` 은 number 경로만 된다.

**결과**: `status`(ok/zero/reject), `total`, `entities[]`:
- `label`
- `matched` — 충족한 조건 수
- `matched_conditions` — `conditions` 의 번호
- `evidence[]` — `p`, `o`, `chunk_ids`

그 밖에 `conditions`, `zero_conditions`, `adjustments`, `sparql` 가 온다.
`evidence`: `compact`(기본) | `full`(s·role 포함) | `none`(목록만 — 가장 작음).

## 질의 작성 규칙

1. **상위 개념은 하위 속성으로 푼다.** '유지보수성', '안정성'처럼 값 목록에 없는 말은 `lookup_values` 의 `narrower` 나 값 목록을 보고 풀어 `any` 로 묶는다. **어떻게 풀었는지 답변에 밝힌다.**
2. **같은 계열 관계는 OR 로 묶는다.** 경로의 `family` 가 같고 `polarity`/`strength` 만 다른 관계(강한·중간 긍정 등)는 `path` 배열이나 `any` 로 묶는다. **AND 로 묶지 않는다** (한 대상이 같은 속성에 강한 긍정과 중간 긍정을 동시에 갖는 일은 거의 없다).
3. **반대 근거도 함께 본다.** 긍정 효과를 찾을 때 같은 계열의 부정 경로를 `return` 에 넣는다. 긍정과 부정이 함께 있으면 **데이터 충돌**로 답변에 적는다.
4. **질문의 모든 조건을 넣는다.** "A 와 B 가 좋은" 은 `all: [A, B]` 다. 하나만 넣고 끝내지 않는다. 둘 다 만족하는 결과가 없으면 `any` 로 다시 조회하고, 그렇게 했다고 밝힌다.
5. **text 경로는 `contains`, enum 경로는 목록 표기 그대로 `eq`/`in`.**
6. **관계를 따라가는 질문은 나눠 조회한다.** "X 의 스승의 스승", "X 가 제안한 이론을 반박한 사람" — 한 번에 하나씩 `query_plan` 을 하고 앞 결과의 엔티티를 다음 조건의 값으로 쓴다.
7. **엔티티 하나의 속성을 묻는 질문** ("파인만의 지도교수는?")은 그 엔티티를 값으로 갖는 경로로 찾거나, `kind` + `where: {"path": ..., "op": "eq", "value": 엔티티}` 로 역방향 조회한다. 안 되면 `search`.
8. **같은 결과를 여러 번 쓰면 한 번 받아 둔다.** 예: 한 유형 전체를 `where` 없이 받아 두고 여러 질문에 재사용. 같은 질의를 반복하지 않는다.
9. **`zero` 는 실패가 아니다.** message 를 읽고 값 표기(→ `lookup_values`)나 경로(→ `describe_kb` 정의)를 고친다. 그래도 없으면 "그래프에 없음"으로 답한다. 지어내지 않는다.

## 답변 규칙

- 질문한 언어로 답한다.
- 결과 엔티티마다 근거(경로·값)와 출처 문서명을 적는다.
- 해석을 밝힌다: "유지보수성을 변경·테스트·관리 용이성으로 풀어 조회했습니다".
- 질문에 없는 사용자 상황(팀 규모, 예산 등)을 사실처럼 쓰지 않는다. 필요하면 가정이라고 밝힌다.
- 그래프에 없는 것은 "지식 그래프에서 찾지 못했다"고 답한다. 일반 지식으로 채울 때는 구분해서 밝힌다.
