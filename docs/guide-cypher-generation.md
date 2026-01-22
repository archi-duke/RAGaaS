# Cypher Query Generator (Neo4j) – Vibe Coding Guide

자연어 질문을 **Intent + Slots → Cypher 템플릿 → 엔티티/관계/속성 매핑 → 쿼리 생성**  
파이프라인을 통해 안정적으로 **Neo4j Cypher 쿼리**를 생성하기 위한 **바이브 코딩(Vibe Coding) 개발 지침서**이다.

---

## 1. 목표 (Goal)

- 자연어 질문을 입력받아
- 그래프 스키마(노드 라벨/관계 타입/속성)에 정합적인
- **문법적으로 유효하고 재현 가능한 Cypher 쿼리**를 생성한다.
- LLM은 “의미 해석과 결정”에 집중하고,
- 쿼리 구조와 안정성은 **템플릿 기반**으로 보장한다.

---

## 2. 전체 파이프라인 개요

```
Natural Language Question
        ↓
Intent + Slots Extraction
        ↓
Cypher Template Selection
        ↓
Entity / Relationship / Property Mapping (Schema Resolution)
        ↓
Final Cypher Generation
        ↓
Syntax / Schema Validation
```

---

## 3. 입력 / 출력 계약 (I/O Contract)

### Input

- `question`: string
- `graph_schema`: 그래프 스키마 요약
  - node labels (예: Person, City, University)
  - relationship types (예: HAS_TEACHER, LOCATED_IN)
  - properties (예: name, population, establishedYear)
  - labels/aliases/synonyms
- `entity_index`: 엔티티 후보 검색 결과 (node id or key, label, properties, score)
- `rel_index`: 관계 타입 후보 검색 결과 (type, score)
- `prop_index`: 속성 후보 검색 결과 (property key, score)
- `config`:
  - `id_strategy`: (by_internal_id | by_unique_key)
  - `unique_key`: (예: Person.name, Entity.iri 등)
  - `case_sensitivity` 등

### Output (JSON Only)

```json
{
  "intent": "RELATION_CHAIN",
  "slots": {
    "startEntity": "성기훈",
    "relationType": "HAS_TEACHER",
    "depth": 2
  },
  "template_id": "C4_REL_CHAIN_2HOP",
  "mappings": {
    "entities": {
      "성기훈": { "label": "Person", "key": "name", "value": "성기훈" }
    },
    "relationships": {
      "스승": "HAS_TEACHER"
    },
    "properties": {}
  },
  "cypher": "...",
  "params": { "startName": "성기훈" },
  "assumptions": [],
  "validation": {
    "syntax_ok": true,
    "schema_ok": "likely",
    "notes": []
  }
}
```

---

## 4. Intent 정의

| Intent | 설명 |
|------|------|
| FACT_LOOKUP | 단일 속성 조회 |
| LIST_BY_LABEL | 라벨 기반 목록 |
| FILTER_LIST | 조건 필터 |
| RELATION_CHAIN | 관계 다단계 탐색 |
| AGGREGATION | 집계 질의 |
| RANKING | 정렬 / Top-N |
| EXISTENCE | 존재 여부 |
| TEMPORAL_FILTER | 시간 조건 |

---

## 5. Slot 표준 정의

```json
{
  "startEntity": "label or key value",
  "startLabel": "Person",
  "uniqueKey": "name",
  "relationType": "HAS_TEACHER",
  "depth": 2,
  "filters": [
    { "expr": "n.population >= $minPop", "params": { "minPop": 10000000 } }
  ],
  "orderBy": { "expr": "n.population", "direction": "DESC" },
  "limit": 10,
  "return": ["n", "value"]
}
```

---

## 6. Intent → Template 선택 규칙

- “A의 B의 C” 구조 → `RELATION_CHAIN`
- “누구 / 무엇 / 어디” → `RETURN`
- “있어?” → `EXISTENCE`(RETURN count>0 or EXISTS)
- “몇 개” → `COUNT()`
- “가장 / 최고” → `ORDER BY ... DESC LIMIT`
- “없을 수도” → `OPTIONAL MATCH`

---

## 7. 엔티티 / 관계 / 속성 매핑 규칙

### 엔티티 매핑

1. 정확 라벨/이름 일치
2. 동의어 일치
3. 부분 문자열
4. 임베딩 유사도

- 동명이인 가능 시 `label`/문맥 슬롯으로 분기
- 내부 id 사용은 이식성 낮음 → 가능하면 `unique key`(예: `name`, `iri`) 사용
- 불확실하면 `assumptions`에 기록

### 관계 타입 매핑

- 자연어 관계(“스승/멘토/지도교수”) → `rel_index` 후보
- 도메인/레인지(출발/도착 라벨) 충돌 시 후보 제거(가능하면)
- 불확실하면 가장 일반적 의미 채택 + assumptions 기록

### 속성 매핑

- 자연어 속성(“인구/설립연도”) → `prop_index`
- 노드 라벨에 없는 속성 키면 후보 제외(가능하면)

---

## 8. Cypher 생성 규칙 (안전/안정성)

- **파라미터 바인딩**을 기본으로 사용 (`$param`)
- 문자열 결합으로 값 삽입 금지 (Cypher injection 예방)
- 변수명은 의미 기반 네이밍 (`p`, `teacher`, `grandTeacher`)
- 가능한 경우 라벨 제약을 포함 (`(p:Person)`)

### 검증(LLM self-check) 체크리스트

- MATCH/WHERE/RETURN 순서 정상?
- 변수 스코프/재사용 문제 없음?
- 파라미터 이름 일치?
- OPTIONAL MATCH에서 null 처리 필요?
- 집계 시 RETURN에 비집계 변수 포함 여부 확인

---

## 9. Cypher 템플릿 라이브러리 (Template Pack)

> **핵심 원칙**: 모든 템플릿은 정답 노드뿐만 아니라 **경유 관계 정보(`subject`, `relationship type`, `object`)**를 함께 반환해야 한다.
> 이를 통해 Graph RAG 시스템이 2차 조회 없이 관계 정보와 Chunk 매핑 정보를 즉시 활용할 수 있다.

### C1. FACT_LOOKUP (단일 속성)
```cypher
MATCH (subject:{{LABEL}} { {{KEY}}: $value })
RETURN subject AS subject, 
       '{{PROP}}' AS predicate, 
       subject.{{PROP}} AS object,
       subject.name AS subjectLabel
```

### C2. LIST_BY_LABEL (라벨 목록)
```cypher
MATCH (subject:{{LABEL}})
RETURN subject AS subject,
       'type' AS predicate,
       '{{LABEL}}' AS object,
       subject.name AS subjectLabel
LIMIT $limit
```

### C3. FILTER_LIST (조건 필터)
```cypher
MATCH (subject:{{LABEL}})
WHERE {{FILTER_EXPR}}
RETURN subject AS subject,
       '{{PROP}}' AS predicate,
       subject.{{PROP}} AS object,
       subject.name AS subjectLabel
LIMIT $limit
```

### C4. REL_CHAIN_1HOP (단일 관계 탐색)
```cypher
MATCH (subject:{{START_LABEL}} { {{START_KEY}}: $startValue })
MATCH (subject)-[r:{{REL_TYPE}}]->(object)
RETURN subject AS subject,
       type(r) AS predicate,
       object AS object,
       subject.name AS subjectLabel,
       object.name AS objectLabel
```

### C5. REL_CHAIN_2HOP (2단계 관계 탐색)
```cypher
MATCH (s1:{{START_LABEL}} { {{START_KEY}}: $startValue })
MATCH (s1)-[r1:{{REL_TYPE}}]->(o1)
MATCH (o1)-[r2:{{REL_TYPE}}]->(o2)
RETURN s1 AS s1, type(r1) AS p1, o1 AS o1,
       o1 AS s2, type(r2) AS p2, o2 AS o2,
       s1.name AS startLabel,
       o1.name AS midLabel,
       o2.name AS resultLabel
```

### C6. REL_CHAIN_NHOP (가변 길이 path)
```cypher
MATCH (subject:{{START_LABEL}} { {{START_KEY}}: $startValue })
MATCH path = (subject)-[:{{REL_TYPE}}*{{DEPTH}}]->(object)
UNWIND relationships(path) AS r
RETURN startNode(r) AS subject,
       type(r) AS predicate,
       endNode(r) AS object,
       startNode(r).name AS subjectLabel,
       endNode(r).name AS objectLabel
```

### C7. AGGREGATION_COUNT_GROUP
```cypher
MATCH (subject:{{LABEL}})-[r:{{REL_TYPE}}]->(group:{{GROUP_LABEL}})
RETURN group AS groupNode,
       group.name AS groupLabel,
       COUNT(subject) AS count
ORDER BY count DESC
LIMIT $limit
```

### C8. RANKING_TOPN
```cypher
MATCH (subject:{{LABEL}})
WHERE subject.{{PROP}} IS NOT NULL
RETURN subject AS subject,
       '{{PROP}}' AS predicate,
       subject.{{PROP}} AS object,
       subject.name AS subjectLabel
ORDER BY subject.{{PROP}} {{DIR}}
LIMIT $limit
```

### C9. EXISTENCE (존재 여부)
```cypher
MATCH (a:{{A_LABEL}} { {{A_KEY}}: $aValue })-[r:{{REL_TYPE}}]->(b:{{B_LABEL}})
RETURN a AS subject,
       type(r) AS predicate,
       b AS object,
       COUNT(b) > 0 AS exists
LIMIT 1
```

### C10. OPTIONAL_FIELD (없을 수도 있는 관계/속성)
```cypher
MATCH (subject:{{LABEL}})
OPTIONAL MATCH (subject)-[r:{{OPT_REL}}]->(object)
RETURN subject AS subject,
       CASE WHEN r IS NOT NULL THEN type(r) ELSE null END AS predicate,
       object AS object,
       subject.name AS subjectLabel,
       object.name AS objectLabel
LIMIT $limit
```

---

## 10. LLM Vibe Prompt (Cypher Compiler)

```text
You are a Neo4j Cypher query compiler.

Input:
- question
- graph_schema (labels, rel types, properties, synonyms)
- entity_index (top candidates)
- rel_index (top relationship type candidates)
- prop_index (top property key candidates)
- config (unique key strategy)

Steps:
1) Extract intent and slots.
2) Select one Cypher template_id from the template pack.
3) Map entities / relationship types / properties using indices.
   - Prefer exact label matches.
   - Enforce label constraints when possible.
   - If ambiguous, choose the most likely and record assumptions.
4) Produce final Cypher with PARAMETERS (no string interpolation).
5) Self-check: variable scope, params, MATCH order, aggregation rules.

Output MUST be a single JSON object with keys:
intent, slots, template_id, mappings, cypher, params, assumptions, validation.
Do not output any extra commentary.
```

---

## 11. 예시

### Question
> 성기훈의 스승은 누구야?

### 해석
- Intent: `RELATION_CHAIN`
- Slots: startEntity=성기훈, relationType=HAS_TEACHER, depth=1
- Template: `C4_REL_CHAIN_1HOP`
- Start node 식별: `(subject:Person {name: $startValue})`

### Generated Cypher (트리플 정보 포함)
```cypher
MATCH (subject:Person { name: $startValue })
MATCH (subject)-[r:HAS_TEACHER]->(object)
RETURN subject AS subject,
       type(r) AS predicate,
       object AS object,
       subject.name AS subjectLabel,
       object.name AS objectLabel
```

### Params
```json
{ "startValue": "성기훈" }
```

### 예상 결과
| subject | predicate | object | subjectLabel | objectLabel |
|---------|-----------|--------|--------------|-------------|
| (Person) | HAS_TEACHER | (Person) | 성기훈 | 오일남 |

> 이제 정답("오일남")과 함께 **관계 정보(성기훈 -[HAS_TEACHER]-> 오일남)**가 한 번의 쿼리로 반환된다.

---

## 12. 구현 팁

- 템플릿은 코드로 고정(신뢰성↑)
- LLM은 Intent/Slots + 매핑 결정에 집중
- 쿼리 문자열 조립은 프로그램이 수행(안정성↑)
- 실패/모호성 대응:
  - 관계 타입 후보 다중 제안 → 1순위 채택 + assumptions 기록
  - OPTIONAL MATCH fallback 제공
  - depth 일반화는 `*N` 가변길이 패턴으로 처리

---

## 13. 권장 확장

- Intent classifier 분리 (rule + LLM hybrid)
- Slot JSON Schema validation
- 스키마 기반 제약(라벨/관계/속성 존재 체크)
- 결과 노드 타입/경로 반환 지원
- Graph RAG 연계:
  - Cypher로 후보 노드/관계 식별 → 해당 노드가 언급된 문서/청크를 벡터 검색 → 근거 답변

---
