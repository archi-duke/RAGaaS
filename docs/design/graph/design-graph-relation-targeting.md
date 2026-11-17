# 그래프 검색: 관계 타게팅 SPARQL 전환 설계

> **문서 상태 (2026-11-17)**: ✅ 현행 (2026-11-14 구현) · 지도: [`docs/README.md`](../../README.md)


- 작성일: 2026-11-14
- 대상: `backend/app/services/retrieval/graph.py`, `graph_backends/fuseki.py`, `relation_targeting.py`(신규), `api/retrieval.py`, `frontend/src/components/SearchResults.tsx`
- 관련: `docs/design/graph/design-query-analysis-merge.md`, `docs/design/graph/design-query-generation-loop.md`, `docs/design/schema/design-structured-json-yaml-ontology.md`

## 1. 배경 — 무엇이 의도와 달랐나

### 의도한 그래프 검색
1. 질문에서 엔티티와 **묻는 관계**를 추출한다.
2. 그 관계를 겨냥한 SPARQL로 **해당 트리플만** 찾는다.
3. **그 트리플에 연결된 청크**(reification)를 근거로 답한다.

### 실제 동작 (test-ontology, "pros of micro frontend?")
- **질의 분석**: 엔티티 `micro frontend`는 잡혔지만 관계어(`relation_aliases`)는 빈 값이었다.
- **Pattern 3 Fast Path**: 앵커 노드 `inst:micro_frontend` 주변 트리플을 관계 구분 없이 **79개 전부** 가져오고, LLM SPARQL 생성은 건너뛰었다.
- **관련성 검사**: 엔티티 이름 토큰만으로 통과했다.
- **reification 조인**: "found URI가 subject 또는 object인 모든 stmt"를 모았다. 그래서 `inst:high`/`inst:medium` 같은 공유 값 노드가 **문서 전체 청크 23개**를 끌고 왔다.
- **청크 선택**: 임베딩 유사도로 상위 10개를 고르고, 트리플 79개와 함께 답변 프롬프트에 넣었다.
- **결과**: 답은 맞았다. 그러나 `tradeoffs.pros` 3건을 고른 것은 검색이 아니라 **답변 LLM**이었다.

Fast Path는 PR #47 이전부터 있었다. 다만 구조화 문서에서는 엔티티 링킹이 실패해 가려져 있었다. #47에서 링킹을 고치고 2-hop으로 확장하면서 Fast Path가 항상 성공하게 되었다.

## 2. 목표 흐름

```
질문 분석(LLM 1회) → 엔티티 링킹 → 관계 경로 카탈로그(SPARQL 1회)
  → 관계 타게팅(A 결정적 매칭 → B LLM 경로 선택 → C LLM SPARQL 생성)
  → 타게팅 SPARQL 실행(트리플 + 트리플별 청크 정확 조인)
  → 청크를 트리플 연결 순으로 정렬 → 답변(선택 트리플 + 연결 청크만)
  → Execution Log 에 5단계 추론 리포트
```

### 질의 유형별 동작

| 유형 | 판별 | 동작 |
|---|---|---|
| 속성/관계 질문 | 앵커 1개, 관계어 있음 또는 intent=attribute | 관계 타게팅 A → B → C |
| 개요 ("X에 대해 알려줘") | intent=overview, 또는 B가 `overview` 반환 | 앵커의 depth-1 이웃만 조회 (구조 노드 하위 제외, 상한 40). 이웃 전체 조회가 허용되는 유일한 경우 |
| 목적어 역할 | role=object | 같은 파이프라인, incoming 방향 우선 정렬 |
| 두 엔티티 관계 ("A와 B의 관계") | LLM 엔티티 2개가 모두 인스턴스로 링킹 | 양 끝 URI를 고정해 직접 트리플 조회. 0건이면 C |
| 멀티홉 | hop_count≥2 또는 `의`×2 | **이번 범위 밖.** 기존 LLM SPARQL 루프(C)를 유지한다. 후속 과제로 홉별 결정적 체인을 계획한다 |
| 앵커 미해결 | 링킹 실패 | 기존 C → 0건이면 Strict 빈 결과 |

## 3. 관계 타게팅

### 3.1 관계 경로 카탈로그
- 앵커에서 나가는 경로를 `(방향, p0, p1, p2, 건수, 예시값)` 형태로 모은다.
  - 구조화 문서의 익명 구조 노드(`inst:root_N_…`)를 따라 깊이 3까지 내려간다.
  - 예: `tradeoffs.pros`, `decision_rules.if.team_size`
- 들어오는 경로(incoming)는 깊이 1만 모은다.
- SPARQL 1회로 끝나며, test-ontology 기준 약 30ms다.

### 3.2 A. 결정적 매칭 (LLM 없음)
- 비교 방식: 별칭과 경로 세그먼트(predicate 로컬네임)를 `entity_linking.normalize_text/tokens`로 정규화해 비교한다.

| 등급 | 조건 | 예 |
|---|---|---|
| 1 | compact 완전일치 | `pros` = `pros`, `스승` = `스승` |
| 2 | 토큰 수가 같고, 토큰마다 공통 접두 4자 이상 (영문) | `test complexity` ≈ `testing_complexity` |
| 3 | 별칭 토큰 ⊆ 세그먼트 토큰 (영문 3자 이상), 한글은 부분 포함 (2자 이상) | `avoid` ⊂ `avoid_signals` |

- 금지: 토큰 내부 부분 문자열 매칭은 하지 않는다. `of` ⊂ `tradeoffs` 같은 오매칭이 다시 생기기 때문이다.
- 임베딩 미사용: 짧은 한↔영 단어의 임베딩 유사도는 신뢰할 수 없다 (장점~pros 0.20).
- 채택: 최고 등급의 매칭만 채택한다. 동률은 모두 유지하되 상한은 6개 경로다.
- 매칭 위치에 따른 선택:
  - **중간 세그먼트**에 매칭되면 그 접두 아래 경로를 모두 선택한다. 예: `prerequisites` → technical/design/organizational 전체.
  - **리프**에 매칭되면 그 경로만 선택한다. 예: `tradeoffs.pros`.

#### 별칭 풀
다음 순서로 별칭을 모은다.
1. 분석기의 `relation_aliases`
2. `relationship_type`
3. 링킹에 실패한 LLM 엔티티 — 속성어("테스트 복잡도")가 엔티티로 잘못 분류된 경우를 구제한다.

#### 방향 처리 (서사형 KB 회귀 방지)
- 별칭과 같은 predicate는 in/out 양방향을 모두 가져온다. 방향은 필터가 아니라 정렬 기준이며, 역할에 맞는 방향을 앞에 둔다.
  - 이유: LLM으로 추출한 그래프는 방향 일관성이 낮다.
- 역관계 맵(`스승`↔`제자`)으로 확장한 별칭은 **반대 방향에만** 적용한다.
  - 예: "성기훈의 스승" → out:`스승`, in:`제자`. 이렇게 해서 "성기훈의 제자"가 섞이는 것을 막는다.

### 3.3 B. 닫힌 집합 LLM 경로 선택
- **호출 조건**: A가 0건이거나 별칭이 비었고, intent가 overview가 아닐 때만 호출한다.
- **입력/출력**
  - 입력: 질문 + 카탈로그 (경로, 방향, 건수, 예시값, 최대 80개)
  - 출력: `{"mode": "targeted|overview|none", "paths": [...]}`
- **검증**: 반환된 경로는 카탈로그에 실제로 있는지 확인한 뒤에만 쓴다. 그래서 자유 SPARQL 생성보다 견고하다.
- **의역 처리**: 한/영 표현 차이와 의역도 흡수한다. 예: "잘 어울리는 스타일" → `combines_well_with`.
- **`none`일 때**: Strict 빈 결과로 끝낸다. 이웃 전체 조회로 떨어지지 않는다.
- **모델**: 그래프 단계의 `llm_model`을 쓴다. 운영에서는 GLM-5 계열을 쓸 예정이다.
  - GLM 계열은 `thinking` 비활성 옵션을 붙여 호출한다.
  - 응답 JSON은 코드펜스가 섞여도 파싱한다.

### 3.4 C. 기존 LLM SPARQL 생성 루프
- 기존 `_generate_and_execute_sparql`(QueryGenerationLoop)을 그대로 쓴다.
- 진입 조건은 다음 중 하나다: 앵커 미해결, 멀티홉, 두 엔티티 직접 조회 0건, B 호출 예외.
- 카탈로그의 predicate를 `context_predicates`로 넘긴다.

### 3.5 타게팅 SPARQL
- 선택한 경로마다 UNION 분기를 만들고, **리프 트리플의 s-p-o와 정확히 일치하는 statement**로 청크를 조인한다.

```sparql
{ BIND(<anchor> AS ?a) ?a rel:tradeoffs ?s . ?s rel:pros ?o . BIND("out|tradeoffs.pros" AS ?path) }
...
OPTIONAL { ?st rdf:subject ?s ; rdf:predicate ?p ; rdf:object ?o ; meta:sourceNodeId ?chunk }
```

- 구조 경로 트리플은 `(앵커 라벨, "tradeoffs.pros", 값)` 형태로 평탄화한다.
- 각 트리플에 `path`와 `chunk_ids`를 붙인다.
- 메타데이터 `sparql_query`에는 실제로 실행한 SPARQL을 넣는다. 그러면 UI Query 탭에서 그대로 보인다.

### 3.6 링킹 보강
- `_resolve_entity_to_uri` 후보에서 익명 구조 노드(`/inst/root_[0-9]+_`)를 제외한다.
  - 문제였던 예: `'avoid'` → `root_0_avoid_signals_2`
- LLM 엔티티(primary) 중 하나라도 링킹되면, 휴리스틱/spaCy 토큰으로 두 번째 앵커를 잡지 않는다.
  - 기존: primary의 "조각"인 토큰만 건너뛰었다.
- 별칭 풀에 있는 단어는 앵커 후보에서 뺀다.

## 4. 질의 분석 프롬프트 변경 (`_analyze_and_extract`)
- 질문이 묻는 **속성/관계어는 엔티티가 아니다**. `relation_aliases`에 넣는다.
- `relation_aliases`는 특정 속성·관계를 묻는 질문에서 **필수**다.
  - 4~8개를 넣는다: 원문 표기, 한/영 동의어, 단수/복수, snake_case 키 이름.
  - 빈 값은 개요 질문일 때만 허용한다.
- `intent` 필드를 추가한다: `attribute | overview | relation_between | multi_hop`.
- 후처리 규칙:
  - 별칭이 비었고 `relationship_type`이 있으면 그것으로 채운다.
  - 별칭과 같은 엔티티는 제거한다.
- 분석기가 빈 값을 내도 B가 받아 준다. 그래서 프롬프트는 비용 최적화 수단이고, 정확성의 최종 근거는 B다.

## 5. 답변 컨텍스트
- `graph_metadata.triples`에는 **선택된 트리플만** 넣는다.
- 답변 프롬프트의 트리플 줄에는 근거 청크 번호를 붙인다. 예: `- micro_frontend tradeoffs.pros 프론트 팀 독립 배포 [Chunk 1]`.
- 청크 순서는 임베딩이 아니라 **트리플 연결 순**이다. 지지하는 트리플이 많은 청크를 먼저 두고, 그다음 경로 순으로 둔다.
  - `_fetch_chunks`의 ordered 모드로 처리한다.
  - 점수는 `1.0 - 0.01*rank`로 매겨, 파이프라인 병합에서도 순서가 보존되게 한다.
- C 경로(LLM SPARQL)는 트리플↔청크 매핑이 없으므로 기존 cosine 정렬을 유지한다.

## 6. Execution Log 추론 리포트
- 백엔드가 `graph_metadata.reasoning`(dict)을 단일 소스로 만든다.
- 같은 내용을 텍스트로 렌더해 trace 로그 **맨 앞**에 둔다. 프론트는 로그를 `pre-wrap`으로 그대로 표시하므로, 텍스트만으로도 읽힌다.

```
[Graph] ━━ 추론 리포트 ━━
[Graph 1/5 질문 분석] intent=attribute | 엔티티: 'micro frontend'(subject) | 관계어: pros, 장점, advantages
[Graph 2/5 엔티티 링킹] 'micro frontend' → inst:micro_frontend
[Graph 3/5 관계 타게팅] mode=A(결정적 매칭) | 'pros' = tradeoffs.pros (완전일치) | 후보 경로 39개 중 1개 선택
  SPARQL: (실행한 타게팅 SPARQL)
[Graph 4/5 선택 트리플] 3건
  1. micro_frontend —tradeoffs.pros→ 프론트 팀 독립 배포  ⟵ root_0_tradeoffs_22
[Graph 5/5 근거 청크] 1건 (트리플 연결 순)
  #1 …::struct::root_0_tradeoffs_22 ⟵ 트리플 1,2,3
```

- 답변 생성 후 `retrieval.py`가 한 줄을 추가한다: `[Answer] 근거: 그래프 트리플 3건 + 청크 1건 | 답변이 인용한 청크: [Chunk 1]`.
- 리포트 문구에는 "error/failed/fallback"을 쓰지 않는다. `retrieval.py`가 로그 문자열을 스캔해 `has_error`/`used_fallback` 플래그를 켜기 때문이다.
- 프론트 Logs 탭: `graph_metadata.reasoning`이 있으면 "Graph Reasoning" 카드를 추가한다.

## 7. 범위 밖 (후속 과제)
- **멀티홉 체인**: 홉별로 결정적 타게팅을 한다. 현재는 C 경로를 유지한다.
- **Neo4j 백엔드**: 같은 문제의 Fast Path가 있으며, `relation_targeting.py`를 재사용해 고칠 수 있다.
- **벡터 청크 혼합**: "Graph → Hybrid"와 파이프라인 병합에서 벡터 청크가 섞여 들어가는 정책은 소유자가 결정해야 한다.
- **서사형 KB 라이브 검증**: 현재 Fuseki에 서사형 데이터셋이 없다. 단위 테스트 픽스처로 대신하고, 재인제스트 후 검증한다.

## 8. 검증 매트릭스 (test-ontology)

| 질문 | 기대 mode | 기대 트리플 |
|---|---|---|
| pros of micro frontend? | A (분석기가 빈 값이면 B) | `tradeoffs.pros` 3건만 |
| cons of micro frontends | A | `tradeoffs.cons` 3건 |
| 마이크로 프론트엔드 아키텍처의 장점 | A | pros 3건 |
| what are the prerequisites for micro frontend? | A (중간 노드) | prerequisites 하위 전체 |
| when should I avoid micro frontend? | A 또는 B | `avoid_signals.*` |
| micro frontend의 테스트 복잡도는? | A (어간 일치) | `testing_complexity` 1건 |
| 마이크로 프론트엔드와 잘 어울리는 스타일은? | A 또는 B | `combines_well_with.*` |
| micro frontend 에 대해 알려줘 | overview | depth-1 이웃 (40건 이하) |
| micro frontend의 가격은? | none | 0건, Strict 빈 결과, 리포트에 사유 기록 |
