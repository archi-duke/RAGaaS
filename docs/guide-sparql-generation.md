# SPARQL Query Generator – Vibe Coding Guide

자연어 질문을 **Intent + Slots → SPARQL 템플릿 → 엔티티/속성 매핑 → 쿼리 생성**  
파이프라인을 통해 안정적으로 SPARQL 쿼리를 생성하기 위한 **바이브 코딩(Vibe Coding) 개발 지침서**이다.

---

## 1. 목표 (Goal)

- 자연어 질문을 입력받아
- 온톨로지 스키마에 정합적인
- **문법적으로 유효하고 재현 가능한 SPARQL 쿼리**를 생성한다.
- LLM은 “의미 해석과 결정”에 집중하고,
- 쿼리 구조와 안정성은 **템플릿 기반**으로 보장한다.

---

## 2. 전체 파이프라인 개요

```
Natural Language Question
        ↓
Intent + Slots Extraction
        ↓
SPARQL Template Selection
        ↓
Entity / Property Mapping (IRI Resolution)
        ↓
Final SPARQL Generation
        ↓
Syntax / Schema Validation
```

---

## 3. 입력 / 출력 계약 (I/O Contract)

### Input

- `question`: string  
- `schema`: 온톨로지 요약
  - classes
  - properties
  - domain / range
  - labels / synonyms
- `entity_index`: 엔티티 후보 검색 결과
- `property_index`: 속성 후보 검색 결과
- `prefixes`: SPARQL prefix map

### Output (JSON Only)

```json
{
  "intent": "RELATION_CHAIN",
  "slots": {
    "startEntity": "성기훈",
    "relation": "hasTeacher",
    "depth": 2
  },
  "template_id": "T4_RELATION_CHAIN_2HOP",
  "mappings": {
    "entities": {
      "성기훈": "ex:SeongGiHun"
    },
    "properties": {
      "스승": "ex:hasTeacher"
    }
  },
  "sparql": "...",
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
| FACT_LOOKUP | 단일 사실 조회 |
| LIST_BY_TYPE | 타입 기반 목록 |
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
  "startEntity": "IRI or label",
  "targetType": "IRI",
  "relation": "IRI",
  "relations": ["IRI"],
  "depth": 2,
  "filters": [
    {
      "var": "?v",
      "op": ">=",
      "value": "1000000",
      "datatype": "xsd:int"
    }
  ],
  "orderBy": {
    "var": "?v",
    "direction": "DESC"
  },
  "limit": 10
}
```

---

## 6. Intent → Template 선택 규칙

- “A의 B의 C” 구조 → `RELATION_CHAIN`
- “누구 / 무엇 / 어디” → `SELECT`
- “있어?” → `ASK`
- “몇 개” → `COUNT`
- “가장 / 최고” → `ORDER BY + LIMIT`
- “없을 수도” → `OPTIONAL`

---

## 7. 엔티티 / 속성 매핑 규칙

### 엔티티 매핑

1. 정확한 라벨 일치
2. 동의어 일치
3. 부분 문자열
4. 임베딩 유사도

- 동명이인 가능 시 타입/문맥으로 분기
- 불확실하면 `assumptions`에 기록

### 속성 매핑

- 자연어 키워드 → property_index 후보
- domain / range 충돌 시 후보 제거
- 최종 후보 1개 선택
- 불확실하면 가장 일반적인 의미 채택

---

## 8. SPARQL 생성 규칙

- 항상 PREFIX 포함
- 변수명은 의미 기반 네이밍
- 가능하면 타입 제약 추가
- FILTER에는 datatype 명시
- SELECT 변수는 반드시 WHERE에서 바인딩

---

## 9. SPARQL 템플릿 라이브러리

> **핵심 원칙**: 모든 템플릿은 정답 엔티티뿐만 아니라 **경유 트리플 정보(`subject`, `predicate`, `object`)**를 함께 반환해야 한다.
> 이를 통해 Graph RAG 시스템이 2차 조회 없이 관계 정보와 Chunk 매핑 정보를 즉시 활용할 수 있다.

### T1. FACT_LOOKUP (단일 사실 조회)
```sparql
SELECT ?subject ?predicate ?object ?subjectLabel ?objectLabel
WHERE {
  ?subject rdfs:label ?subjectLabel .
  FILTER(STR(?subjectLabel) = "{{START_LABEL}}")
  ?subject {{PROP}} ?object .
  BIND({{PROP}} AS ?predicate)
  OPTIONAL { ?object rdfs:label ?objectLabel }
}
```

### T2. LIST_BY_TYPE (타입 기반 목록)
```sparql
SELECT ?subject ?predicate ?object ?subjectLabel
WHERE {
  ?subject a {{TYPE}} .
  BIND(rdf:type AS ?predicate)
  BIND({{TYPE}} AS ?object)
  ?subject rdfs:label ?subjectLabel .
}
LIMIT 100
```

### T3. FILTER_LIST (조건 필터)
```sparql
SELECT ?subject ?predicate ?object ?subjectLabel
WHERE {
  ?subject a {{TYPE}} ;
           {{PROP}} ?object .
  BIND({{PROP}} AS ?predicate)
  FILTER ( ?object {{OP}} {{VALUE}} )
  ?subject rdfs:label ?subjectLabel .
}
```

### T4. RELATION_CHAIN_1HOP (단일 관계 탐색)
```sparql
SELECT ?subject ?predicate ?object ?subjectLabel ?objectLabel
WHERE {
  ?subject rdfs:label ?subjectLabel .
  FILTER(STR(?subjectLabel) = "{{START_LABEL}}")
  ?subject {{REL}} ?object .
  BIND({{REL}} AS ?predicate)
  ?object rdfs:label ?objectLabel .
}
```

### T5. RELATION_CHAIN_2HOP (2단계 관계 탐색)
```sparql
SELECT ?s1 ?p1 ?o1 ?s2 ?p2 ?o2 
       ?startLabel ?midLabel ?resultLabel
WHERE {
  ?s1 rdfs:label ?startLabel .
  FILTER(STR(?startLabel) = "{{START_LABEL}}")
  ?s1 {{REL1}} ?o1 .
  BIND({{REL1}} AS ?p1)
  ?o1 rdfs:label ?midLabel .
  
  BIND(?o1 AS ?s2)
  ?s2 {{REL2}} ?o2 .
  BIND({{REL2}} AS ?p2)
  ?o2 rdfs:label ?resultLabel .
}
```

### T6. RELATION_CHAIN_NHOP (N단계 Property Path)
```sparql
SELECT ?subject ?predicate ?object ?subjectLabel ?objectLabel
WHERE {
  ?subject rdfs:label ?subjectLabel .
  FILTER(STR(?subjectLabel) = "{{START_LABEL}}")
  ?subject {{REL}}+ ?object .
  BIND({{REL}} AS ?predicate)
  ?object rdfs:label ?objectLabel .
}
```

### T7. AGGREGATION_COUNT (집계)
```sparql
SELECT ?groupVar (COUNT(?countVar) AS ?count)
WHERE {
  {{WHERE_BLOCK}}
}
GROUP BY ?groupVar
```

### T8. RANKING_TOPN (정렬/순위)
```sparql
SELECT ?subject ?predicate ?object ?subjectLabel
WHERE {
  ?subject a {{TYPE}} ;
           {{PROP}} ?object .
  BIND({{PROP}} AS ?predicate)
  ?subject rdfs:label ?subjectLabel .
}
ORDER BY {{DIR}}(?object)
LIMIT {{LIMIT}}
```

### T9. EXISTENCE_ASK (존재 여부)
```sparql
ASK {
  {{SUBJ}} {{PRED}} {{OBJ}} .
}
```

### T10. OPTIONAL_FIELD (선택적 필드)
```sparql
SELECT ?subject ?predicate ?object ?subjectLabel ?optLabel
WHERE {
  ?subject a {{TYPE}} .
  ?subject rdfs:label ?subjectLabel .
  OPTIONAL { 
    ?subject {{OPT_PROP}} ?object .
    BIND({{OPT_PROP}} AS ?predicate)
    ?object rdfs:label ?optLabel 
  }
}
```

---

## 10. LLM Vibe Prompt (Query Compiler)

```text
You are a SPARQL query compiler.

Input:
- question
- schema
- entity_index
- property_index
- prefixes

Steps:
1) Extract intent and slots.
2) Select one SPARQL template.
3) Map entities and properties using indices.
4) Generate final SPARQL with PREFIX.
5) Self-check syntax and schema consistency.

Output ONLY one JSON object.
```

---

## 11. 예시

### Question
> 성기훈의 스승은 누구야?

### Generated SPARQL (트리플 정보 포함)
```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rel: <http://rag.local/rel/>

SELECT ?subject ?predicate ?object ?subjectLabel ?objectLabel
WHERE {
  ?subject rdfs:label ?subjectLabel .
  FILTER(STR(?subjectLabel) = "성기훈")
  ?subject (rel:제자|^rel:스승) ?object .
  BIND(rel:스승 AS ?predicate)
  ?object rdfs:label ?objectLabel .
}
```

### 예상 결과
| subject | predicate | object | subjectLabel | objectLabel |
|---------|-----------|--------|--------------|-------------|
| inst:SeongGiHun | rel:스승 | inst:OhIlNam | 성기훈 | 오일남 |

> 이제 정답("오일남")과 함께 **트리플 정보(성기훈 → 스승 → 오일남)**가 한 번의 쿼리로 반환된다.

---

## 12. 구현 팁

- 템플릿은 코드로 고정
- LLM은 해석/결정만 담당
- 쿼리 문자열 조립은 프로그램이 수행
- 실패 시 OPTIONAL 또는 fallback 전략 적용

---

## 13. 권장 확장

- Intent classifier 분리
- Slot JSON Schema validation
- Property-path 자동 선택
- Graph RAG 연계 (SPARQL → Vector Search)

---
