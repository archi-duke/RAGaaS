# ragaas-query 예시 (모두 실행 확인, 2026-11-16)

### 1. 조건 하나 (상위 개념 풀기) — "유지 보수성이 좋은 스타일은?"

`lookup_values(["유지보수성"])` → matches 없음, narrower = 변경·테스트·관리 용이성.

```json
{"kind": "ArchitectureStyle",
 "where": {"any": [
   {"path": ["has_positive_effect_on", "has_moderate_positive_effect_on"], "op": "in", "value": ["변경 용이성", "테스트 용이성", "관리 용이성"]},
   {"path": "is_suitable_for", "op": "contains", "value": "유지보수"}]},
 "return": ["has_moderate_negative_effect_on", "has_negative_effect_on"]}
```

→ Clean Architecture·Hexagonal (matched 2) 이 먼저 나오고 나머지 5개가 이어진다. CQRS 는 부정 효과에도 '변경 용이성'이 있다 → 충돌로 표시.

### 2. 복합 조건 — "유지 보수성과 수정 용이성이 좋은 스타일은?"

'수정 용이성'은 `lookup_values` 로 '변경 용이성'이 된다.

```json
{"kind": "ArchitectureStyle",
 "where": {"all": [
   {"path": ["has_positive_effect_on", "has_moderate_positive_effect_on"], "op": "eq", "value": "변경 용이성"},
   {"any": [
     {"path": ["has_positive_effect_on", "has_moderate_positive_effect_on"], "op": "in", "value": ["테스트 용이성", "관리 용이성"]},
     {"path": "is_suitable_for", "op": "contains", "value": "유지보수"}]}]},
 "return": ["has_moderate_negative_effect_on"]}
```

→ Clean·Hexagonal (3) → Micro-Frontend·Modular Monolith (2).

### 3. 구조화 KB, 같은 항목 조건 — "변경 용이성에 강한 긍정 효과가 있는 스타일" (test-ontology)

```json
{"kind": "ArchitectureStyle",
 "where": {"all": [
   {"path": "quality_attributes.attribute", "op": "eq", "value": "modifiability"},
   {"path": "quality_attributes.effect", "op": "eq", "value": "positive"},
   {"path": "quality_attributes.strength", "op": "eq", "value": "high"}]},
 "return": ["operational_complexity"]}
```

→ clean-architecture, hexagonal, micro_frontend, microservices. 세 조건이 같은 품질 항목에서 함께 만족해야 한다.

### 4. 집계 — "단점이 가장 많은 스타일은?"

```json
{"kind": "ArchitectureStyle", "aggregate": {"fn": "count", "path": "has_disadvantage", "order": "desc", "limit": 1}}
```

### 5. 관계 따라가기 — "파인만의 지도교수의 지도교수는?"

1. `resolve_entities(["파인만"])` → `파인만`.
2. 지도교수 관계 경로를 `describe_kb` 에서 찾는다 → `지도교수_of` (값: 제자 이름).
3. `{"kind": "Person", "where": {"path": "지도교수_of", "op": "eq", "value": "파인만"}}` → `존 휠러`.
   `evidence`: (존 휠러, 지도교수_of, 파인만) — 휠러가 파인만의 지도교수다.
4. 같은 방식으로 `"value": "존 휠러"` → `zero` ('존 휠러' 는 지도교수_of 값 목록에 없음).
   `lookup_values(["휠러"])` 로 표기를 확인해도 없으면 → "휠러의 지도교수는 지식 그래프에 없다"고 답한다.

경로 방향이 헷갈리면 두 방향을 `any` 로 묶어 조회하고, `evidence` 의 s·p·o 로 방향을 확인한다.
