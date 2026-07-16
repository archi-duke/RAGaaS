# 그래프 질의 분석 병합 설계: 2 LLM 호출 → 1 + 엔티티 역할 판별

> 상태: 구현 예정 (Design)
> 관련: docs/design-query-generation-loop.md (Phase 1/2), entity_linking.py (Phase 2)

## 1. 배경 및 동기

그래프 질의 1회는 현재 LLM 을 4~7회 호출한다(실측):

| # | 호출 | 위치 |
|---|---|---|
| 1 | Gate (needs_search) | retrieval.py:431 |
| 2 | **_extract_entities** | graph.py:225 |
| 3 | **_analyze_query** | graph.py:333 |
| 4 | SPARQL/Cypher 생성 (재시도 최대 3회) | generator |
| 5 | 최종 답변 생성 | retrieval.py:684 |

2번(_extract_entities)과 3번(_analyze_query)은 **둘 다 같은 질문을 LLM 으로 분석**한다 — 전자는 엔티티,
후자는 구조(subject/관계/홉). 겹치는 두 호출을 하나로 병합하면:

- **LLM 왕복 1회 제거 → 응답 지연 단축**
- 엔티티별 **문법 역할(주어/목적어)** 을 부산물로 확보 → 백엔드의 취약한 조사(Josa) 휴리스틱 대체

즉 "역할 판별 추가"를 지연 증가 없이(오히려 감소) 달성한다.

## 2. 목표 / 비목표

### 목표
1. `_analyze_query` + `_extract_entities` → 단일 LLM 호출 `_analyze_and_extract` 로 병합
2. 반환에 `entities[].role` (subject/object/ambiguous) 추가
3. role 을 백엔드로 전달, Pattern 1/3 분류의 **1차 신호**로 사용 (조사 = 폴백)
4. graph.py:104 멀티홉 문자열매칭 → LLM `hop_count` 우선 사용

### 비목표
- Gate 호출은 건드리지 않음 (검색/잡담 판별 유지)
- spaCy 가제티어 추출 유지 (로컬, 비 LLM, recall 보강)
- 쿼리 생성/최종답변 호출 병합 (별도 과제)

## 3. 병합 함수 설계

`_analyze_and_extract(kb_id, query, llm_client, llm_model) -> Tuple[List[str], Dict]`

단일 프롬프트로 아래 JSON 요구:
```json
{
  "entities": [
    {"name": "성기훈", "role": "subject"},
    {"name": "오일남", "role": "object"}
  ],
  "translated_entities": ["Seong Gi-hun", "Oh Il-nam"],
  "relationship_type": "master|student|...|null",
  "is_multi_hop": false,
  "hop_count": 1,
  "alternatives": ["..."]
}
```
규칙(프롬프트):
- entities.name 은 **원문 표기 유지, 번역 금지** (기존 _extract_entities 규칙 계승)
- role: 질문에서 그 엔티티가 관계의 주체면 "subject", 대상이면 "object", 불명확/대칭이면 "ambiguous"
- translated_entities 는 영어 동의어 (recall 보강용, 기존 계승)

처리:
1. LLM 호출 1회 → JSON 파싱 (실패 시 기존처럼 빈 분석 + 빈 엔티티로 graceful)
2. `entities_list` = entities[].name + translated_entities + **spaCy 가제티어** (기존 로직 그대로 이동)
3. `entity_roles` = {name: role} 딕셔너리 구성
4. `query_analysis` 딕셔너리 구성 — 기존 소비처 호환 키 유지:
   - `query_type`: is_multi_hop→"multi_hop", relationship_type 있으면 "relationship", 아니면 "simple"
   - `relationship_keywords`: 기존 키워드 매칭 로직 유지 (relationship_type 보강)
   - `alternatives`, `hop_count`, `entity_roles` (신규)

반환: `(entities_list, query_analysis)` — search() 의 72·76행 두 호출을 이 하나로 대체.

## 4. search() 통합 (graph.py)

기존:
```python
query_analysis = await self._analyze_query(...)      # 72
entities = await self._extract_entities(...)          # 76
```
변경:
```python
entities, query_analysis = await self._analyze_and_extract(kb_id, query, llm_client, llm_model_name)
```
- 84행 `alternatives` 사용부 유지
- 104행 멀티홉 문자열매칭 → `query_analysis.get("hop_count")` 우선, 문자열매칭은 폴백:
  ```python
  llm_hops = query_analysis.get("hop_count")
  if isinstance(llm_hops, int) and llm_hops >= 2:
      graph_hops = max(graph_hops, llm_hops)
  elif any(kw in query.lower() for kw in [...]):   # 기존 폴백
      graph_hops = max(graph_hops, 2)
  ```
- 114행 `backend.query(...)` 에 `entity_roles=query_analysis.get("entity_roles", {})` 추가

**하위호환**: 기존 `_analyze_query`/`_extract_entities` 는 삭제하지 않고 남겨둔다(다른 경로 호출 가능성 대비). 신규 병합 함수만 search() 가 사용.

## 5. 백엔드 role 소비 (neo4j / fuseki)

두 백엔드의 Pattern 1 vs 3 분류(단일 엔티티 시 주어/목적어 판별)를 다음으로 변경:

```python
role = (entity_roles or {}).get(entity_name)   # kwargs 로 전달받음
if role == "object":
    # Pattern 1 (엔티티가 목적어: ? -> P -> O)
elif role == "subject":
    # Pattern 3 (엔티티가 주어: S -> P -> ?)
else:
    # role 없음/ambiguous → 기존 조사 휴리스틱으로 폴백 (동작 불변)
    <기존 josa 기반 is_object_pattern/is_subject_pattern 로직>
```

- neo4j.py: 92~104행 부근 (entity_name = resolved_entities[0] 이후)
- fuseki.py: 660~680행 부근 (entity_name, entity_uri = resolved_uris[0] 이후)
- **role 은 원본 질문 토큰 기준 매핑**이므로, resolved 이후 실제 그래프명과 다를 수 있음 →
  entity_roles 는 {원본토큰: role} 로 만들고, 백엔드는 원본 토큰(resolved_entities 에 담긴 값)으로 조회.
- role 이 없거나 매칭 안 되면 반드시 조사 폴백 (회귀 방지 핵심).

`backend.query()` 시그니처에 `entity_roles` 를 kwargs 로 받으므로 별도 시그니처 변경 불필요(**kwargs).

## 6. 안전장치

- LLM JSON 파싱 실패 → 빈 분석 반환, entities 는 spaCy 만이라도 (기존과 동일 graceful)
- role 신뢰 못 하면 조사 폴백 → 한국어 정형 질문 회귀 없음이 최우선
- 기존 함수 미삭제 (롤백 용이)
- entity_roles 미전달(구 파이프라인/직접호출) 시 백엔드는 전량 조사 폴백 → 하위호환

## 7. 테스트

1. **한국어 정형 (회귀 없어야)**: "성기훈은 누구랑 관계있어?" → 기존과 동일 결과
2. **영어 (개선 확인)**: "Who is Seong Gi-hun related to?" → role 로 Pattern 분류, Fast Path 동작
3. **목적어 패턴**: "오일남을 스승으로 둔 사람은?" → role=object → Pattern 1
4. **멀티홉**: "성기훈의 스승의 제자는?" → hop_count=2 사용 확인
5. **LLM 호출 수 감소 확인**: 로그로 그래프 분석 LLM 호출이 2→1 인지 확인
6. **폴백**: entity_roles 빈 상태로도 정상 (조사 경로) — 하위호환

## 8. 기대 효과

- 그래프 질의당 LLM 왕복 1회 감소 (분석 2→1)
- 조사 취약점(영어·어순변형·소유격 연쇄) 해소, 단 한국어 회귀 없음(폴백)
- 멀티홉 판정 정확도 향상 (문자열매칭 → LLM hop_count)
