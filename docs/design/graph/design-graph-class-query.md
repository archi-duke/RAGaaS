# 그래프 검색: 유형 수준(class-level) 질문 — 질의 계획 기반 SPARQL

> **문서 상태 (2026-11-17)**: ✅ 현행 (2026-11-14 구현) · 지도: [`docs/README.md`](../../README.md)


- 작성일: 2026-11-14
- 선행: `docs/design/graph/design-graph-relation-targeting.md` (엔티티 앵커 질문의 관계 타게팅)
- 대상: `relation_targeting.py`, `class_query.py`(신규), `graph_backends/fuseki.py`, `graph.py`, `api/retrieval.py`, `SearchResults.tsx`

## 1. 문제
관계 타게팅은 **앵커 엔티티가 하나인 질문**만 다룬다. 아래 질문들은 앵커가 없거나, 앵커가 결과가 아니라 조건 값이다.

| 질문 | 유형 |
|---|---|
| 테스트 복잡도가 high인 아키텍처 스타일은? | 필터 |
| 팀 규모가 작을 때 피해야 하는 스타일을 모두 알려줘 | 중첩 경로 필터 (`avoid_signals.team_size = small`) |
| pros가 가장 많은 스타일은? | 집계 |
| microservices와 잘 어울리는 스타일은? | 역방향 (`combines_well_with.style = microservices`) |

일반적인 온톨로지 질의응답은 스키마를 보고 쿼리를 생성한다(Text-to-SPARQL). 다만 LLM이 SPARQL을 자유롭게 쓰면 두 가지 문제가 생긴다.
- 존재하지 않는 경로를 쓰는 오류가 난다.
- 변수명이 제각각이라 근거 청크를 트리플에 정확히 붙이기 어렵다.

## 2. 방식 — 질의 계획(JSON) → 검증 → 결정적 컴파일
1. **스키마 카탈로그**: 데이터에서 유형(kind)별로 경로·값 종류·값 어휘를 추출한다.
2. **LLM 질의 계획**: LLM은 카탈로그 **번호와 값 목록 안에서만** 질의 계획을 JSON으로 낸다.
3. **검증**: 코드가 경로·연산자·값이 실재하고 호환되는지 검증한다.
   - 필터가 무효면 계획 전체를 반려하고 1회 재시도한다. 필터 하나를 버리면 결과가 넓어져 오답이 되기 때문이다.
4. **컴파일·실행**: 코드가 SPARQL로 컴파일해 실행한다. 근거 청크는 트리플의 **s-p-o 정확 일치** statement로 조인한다.
5. **자유 생성으로 넘김**: 계획으로 표현할 수 없는 질문만 기존 자유 Text-to-SPARQL(C 경로)로 보낸다. 리포트에 이 사실을 명시한다.

## 3. 라우팅 (데이터 기준, intent는 힌트)
"마이크로 프론트엔드와 잘 어울리는 스타일은?"(앵커 질문)과 "microservices와 잘 어울리는 스타일은?"(역방향)은 문장 형태가 같다. 그래서 LLM intent만으로 가르지 않고 앵커 노드의 성격으로 판단한다.

| 순서 | 조건 | 경로 |
|---|---|---|
| 1 | intent=multi_hop 또는 hop_count≥2 | 기존 C |
| 2 | 앵커가 **레코드**(시스템 predicate를 뺀 outgoing 있음) | 관계 타게팅 A→B. 결과가 `none`이고 intent=class_query일 때만 유형 경로로 넘어감 |
| 3 | 앵커가 **값 노드**(outgoing 없음) | 유형 경로. 앵커는 값 힌트로 쓴다 |
| 4 | 앵커 없음 | 유형 경로 (기존 "앵커 미해결 → C"를 대체) |

- intent=class_query이면 `의`×2 멀티홉 휴리스틱을 건너뛴다.
- 엔티티가 0개여도 조기 종료하지 않는다. "스타일은 모두 몇 개야?"처럼 엔티티 없는 유형 질문이 있기 때문이다.

## 4. 스키마 카탈로그
- **멤버**: `inst:` 노드이고 구조 노드(`root_N_`)가 아니며, 시스템 predicate를 뺀 outgoing이 있는 노드.
- **유형(kind)**:
  - rdf:type이 있으면 클래스가 유형이다.
  - 없으면 depth-1 predicate 집합의 Jaccard ≥ 0.5로 묶는다 (결정적 탐욕 군집화). 이름은 `K1`, `K2`…이고 대표 멤버를 함께 표시한다.
  - 멤버십은 `VALUES ?e { 멤버 }`로 표현한다 (상한 500).
- **경로**: 멤버 기준 out 방향 깊이 3(구조 노드 경유). 경로별로 멤버 커버리지, 서로 다른 값 수(dv), 예시를 둔다.
- **값 종류**:

| 종류 | 조건 | 카탈로그에 싣는 것 |
|---|---|---|
| enum | dv ≤ 15 | 값 전체 |
| number | 모든 라벨이 숫자 | 범위만. 비교는 라벨의 `xsd:decimal` |
| text | 그 외 | 예시 3개 |

- **저장 형태**: 값은 모두 `inst:` URI + `rdfs:label`이다 (리터럴 객체 0건). 비교는 `COALESCE(라벨, STR(값))`로 한다.
- **캐시**: 프로세스 내 `kb_id → 카탈로그`. 그래프 트리플 수를 지문으로 쓰고 TTL은 300초다. 인제스트가 별도 서비스라 무효화 훅을 걸 수 없어서 이 방식을 쓴다.

## 5. 질의 계획 JSON
```json
{
  "mode": "plan | unsupported | none",
  "kind": "K1",
  "filters": [{"path": 12, "op": "eq", "value": "small"}],
  "return": [3],
  "aggregate": {"fn": "count | max | min | count_members", "path": 20, "order": "desc", "limit": 1},
  "reason": "한 줄 근거"
}
```

- **연산자(op)**: `eq`, `ne`, `in`, `contains`, `gt`, `gte`, `lt`, `lte`(number 전용), `exists`, `not_exists`.
- **결합 규칙**: 필터는 AND로 묶고 최대 4개, return은 최대 6개다.
- **역방향 질문**: 별도 구문 없이 `eq` 필터로 표현한다.
- **값 정규화**: 값 목록의 표기 그대로 쓴다. 코드가 `match_tier`(완전일치·어간일치)와 소형 한/영 동의어표(높음→high 등)로 대조한다.
  - enum 경로에 없는 값이 오면 **0건으로 확정**한다 (Strict 빈 결과와 그 사유를 남긴다).
- **컴파일**:
  1. 필터를 적용한 멤버 조회 (집계는 `GROUP BY`, 동률 포함 상위 선택).
  2. `VALUES ?e {결과}`로 근거를 조회한다. 필터·집계·반환 경로를 UNION으로 묶고, 각 트리플에 `role`과 `entity`를 붙인다.
     - 반환 경로가 필터와 같은 구조 노드 접두를 가지면 같은 항목으로 한정한다. 예: `style=microservices`인 항목의 `reason`만 가져온다.
- **청크 정렬**: 엔티티별 라운드로빈으로 정렬한다. 그래야 top_k 안에 모든 결과 엔티티의 근거가 들어간다.

## 6. C 경로(자유 Text-to-SPARQL) 근거 개선
- **진입 조건**: 계획이 `unsupported`, 검증을 재시도해도 반려, 또는 계획 LLM 호출 불가.
- **정확 조인**: 바인딩에서 s/p/o를 추출할 수 있으면 `VALUES (?s ?p ?o)`로 statement와 정확 조인한다.
- **노드 기반 조인**: s/p/o를 못 얻으면 노드 기반으로 조인한다. 이때 **outgoing이 있는 노드만** 쓴다.
  - 이유: 공유 값 노드(`high` 등)가 문서 전체 청크를 끌어오던 문제를 막는다.
- **적용 범위**: 멀티홉을 포함한 기존 C 전체에 적용한다.

## 7. 리포트 / UI
```
[Graph 1/5 질문 분석] intent=class_query | 대상 유형: '스타일' | 엔티티: 'microservices' | 관계어: …
[Graph 2/5 엔티티 링킹] 'microservices' → inst:microservices (값 노드 — 필터 값으로 사용) | 유형: K1 (멤버 10개)
[Graph 3/5 관계 타게팅] mode=P(질의 계획) | 후보 경로 N개 중 2개 사용
    · 필터: combines_well_with.style = microservices
    · 반환: combines_well_with.reason
[Graph 4/5 선택 트리플] 결과 엔티티 2개 · 트리플 4건
  ▸ micro_frontend
    1. [필터] micro_frontend —combines_well_with.style→ microservices ⟵ …
```

- **답변 컨텍스트**: `result_summary`("조건을 만족하는 엔티티 전체 N개: a, b")를 한 줄 넣는다. 그래야 "모두 알려줘" 질문에 빠짐없이 답한다.
- **UI**: Graph Reasoning 카드의 3단계에 계획(필터·반환·집계)을, 4단계에 엔티티별 묶음과 역할 배지를 표시한다.

## 8. 결정 사항
- **역방향 범위**: 레코드 앵커("microservices"가 레코드인 경우)에서 다른 스타일이 그것을 지목한 역방향까지 합치는 것은 v1에서 하지 않는다. 앵커가 레코드면 관계 타게팅(정방향)으로 답한다. 단 결과가 `none`이고 intent=class_query면 유형 경로로 넘긴다.
- **C 근거 개선 범위**: 기존 C 전체에 적용한다.
- **루트 레코드 rdf:type 부여**: 인제스트 시 부여하는 것은 후속 과제다. 시그니처 추론으로 대신한다.
- **검증 데이터**: GoJIRA `style-define/knowledge/arch-styles/styles/`의 스타일 YAML 10개를 test-ontology에 적재해 쓴다 (micro-frontend 외 9개 추가).

## 9. 검증 매트릭스
- **실데이터 질문**: 실제 데이터를 SPARQL로 조회해 기대값을 정한다. 질문은 다음과 같다.
  - 테스트 복잡도 high
  - 팀 규모 small에서 회피
  - pros 최다
  - microservices와 결합
  - 운영 복잡도 medium
  - 존재하지 않는 값
  - 스타일 개수
  - 계획으로 표현할 수 없는 질문 → C
- **회귀**: 앵커 질문 10개는 mode와 트리플이 그대로여야 한다.

## 10. 구현 중 확정·발견 사항 (2026-11-14)

### 구현 세부 결정
- **조건부 개수 집계**: `aggregate.value`(같은 항목의 특정 값만 셈)와 `aggregate.having`(개수 조건, 예: `>= 3`)을 추가했다.
  - 예: "positive 효과 품질 속성이 3개 이상" — 처음에는 자유 SPARQL로 넘어가 49초가 걸렸고 답변에 구조 노드 ID가 섞였다. 계획으로 처리하면서 13초로 줄었다.
- **개수 단위**: (구조 항목, 값) 쌍, 즉 리프 트리플 단위로 센다. 그래서 pros는 값 수만큼, `effect=positive`는 항목 수만큼 세어진다.
- **같은 항목 한정**: 깊이 3 경로와 숫자·텍스트 조건에도 적용한다.
  - 예: `decision_rules.then.score < 0`인 `then` 항목의 reason만 반환한다.
- **값 노드 힌트**: 엔티티와 값 노드가 완전일치할 때만 힌트로 쓴다.
  - 예: '규칙' → '도메인_규칙_테스트_용이' 같은 부분일치는 쓰지 않는다.
- **목록에 없는 값**: 계획 프롬프트에서 "목록에 없는 값을 비슷한 값으로 바꾸지 말 것"을 지시한다.
  - 예: "very low"는 low로 바꾸지 않고 0건으로 확정한다.
- **유형 질문의 앵커 후보**: LLM 엔티티와 그 번역만 쓴다. spaCy·휴리스틱 토큰은 제외한다.
  - 예: '가장'이 문장형 값 노드에 연결되던 문제를 막는다.
  - 대상 유형 단어('스타일')도 앵커에서 제외한다.

### 인제스트 결함 2건 (ingest-service)
1. **익명 구조 노드 ID 충돌**
   - 증상: `structured_extractor`가 문서와 무관하게 `root_0_tradeoffs_22` 형태로 ID를 만들었다. 그래서 여러 YAML 문서의 구조 노드가 같은 URI로 합쳐져 값이 섞였다. 예: 모든 스타일이 `avoid_signals.team_size=small`을 갖는 것처럼 보였다.
   - 수정: ID를 `root_<idx>_<문서ID 8자>_…` 형식으로 바꿨다. 백엔드의 구조 노드 판별 정규식(`/inst/root_[0-9]+_`)과 호환된다.
   - 영향: 기존에 적재된 다중 YAML KB는 재인제스트해야 한다.
2. **Fuseki 쓰기 실패를 성공으로 처리**
   - 증상: 동시 인제스트 중 httpx 기본 타임아웃(5초)이 넘어 메시지 없는 예외가 났다. 이 예외를 삼켜 작업이 COMPLETED로 끝났고, 그래프가 빈 문서가 생겼다(hexagonal).
   - 수정: 타임아웃을 120초로 늘리고 3회 재시도하며, 최종 실패는 예외로 올려 FAILED로 표시한다.

### 검증 데이터
- GoJIRA `style-define/knowledge/arch-styles/styles/`의 9개 YAML을 test-ontology에 추가했다.
- 원래 있던 `micro-frontend.yaml`은 그대로 두었다. 이 문서는 구 ID 형식이지만, 신규 문서와는 더 이상 충돌하지 않는다.
