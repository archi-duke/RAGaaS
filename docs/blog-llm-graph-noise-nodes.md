# LLM 기반 지식 그래프 생성 시 발생하는 쓰레기 노드 문제와 해결법

> Doc2Onto와 같은 LLM 기반 온톨로지 추출 파이프라인에서 "nle620..."와 같은 의미 없는 노드가 생성되는 원인을 분석하고, 이를 효과적으로 제거하는 방법을 알아봅니다.

## 문제 현상

RAG(Retrieval-Augmented Generation) 시스템에서 지식 그래프를 활용하다 보면, 그래프 뷰어에서 다음과 같이 **사람이 읽을 수 없는 노드**들이 나타나는 경우가 있습니다:

```
nle620a8f4b-...
tmp_entity_001
_unnamed_
```

이러한 노드들은 그래프 시각화를 어지럽히고, 실제 엔티티 검색을 방해하며, 최종 사용자에게 혼란을 줍니다.

![그래프 노이즈 예시](/docs/images/graph-noise-example.png)

---

## 발생 원인

### 1. LLM의 불완전한 JSON 응답

LLM에게 텍스트에서 엔티티와 관계를 추출하도록 요청할 때, 프롬프트에서 JSON 형식의 출력을 요구합니다:

```json
{
  "entities": [
    {"name": "성기훈", "type": "Person", "description": "주인공"},
    {"name": "", "type": "Concept", "description": "어떤 개념"}  // ← 빈 이름!
  ],
  "triples": [
    {"subject": "성기훈", "predicate": "참가번호", "object": "456"},
    {"subject": "", "predicate": "관계", "object": "대상"}  // ← 빈 subject!
  ]
}
```

LLM이 때때로 **`name` 필드를 비워두거나**, 내부 참조용 임시 ID(예: `nle620...`)를 생성하는 경우가 있습니다. 이는 특히:

- **모호한 문맥**: 명시적인 이름 없이 "그것", "이것" 등으로 언급된 개념
- **추론된 엔티티**: 문서에 직접 언급되지 않았지만 LLM이 추론한 개념
- **JSON 파싱 오류**: 불완전한 JSON 응답으로 인한 기본값 사용

### 2. 빈 값에 대한 방어 로직 부재

초기 구현에서는 LLM 응답을 그대로 신뢰하여 아래와 같이 처리했습니다:

```python
# 문제가 있는 코드
for entity in llm_result.get("entities", []):
    result.instances.append(InstanceCandidate(
        label=entity.get("name", ""),  # 빈 문자열도 그대로 저장
        class_label=entity.get("type", "Concept"),
        ...
    ))
```

`entity.get("name", "")`가 빈 문자열을 반환하더라도 **필터링 없이 바로 저장**되어, 결국 Neo4j나 Fuseki에 라벨 없는 노드가 생성됩니다.

### 3. 내부 참조 ID의 노출

일부 LLM은 복잡한 관계를 표현하기 위해 내부적으로 임시 ID를 생성합니다:

```json
{
  "entities": [
    {"id": "nle620a8f4b", "name": "성기훈", "type": "Person"},
    {"id": "nle789c2d1e", "type": "Event"}  // name 누락, id만 존재
  ],
  "triples": [
    {"subject": "nle620a8f4b", "predicate": "participated_in", "object": "nle789c2d1e"}
  ]
}
```

이때 `triples`의 `subject`/`object`가 ID로 참조되면, 해당 ID가 그대로 그래프에 노드로 생성됩니다.

---

## 시스템에 미치는 영향

### 1. 그래프 가독성 저하

```
[nle620...] ─── 관계 ───> [성기훈]
[tmp_001] ─── 속성 ───> [456]
```

사용자에게 보여지는 그래프가 의미 없는 노드로 뒤덮여 **핵심 정보를 파악하기 어렵습니다**.

### 2. 검색 품질 하락

벡터 검색이나 키워드 검색 시, 이러한 노이즈 노드들이 결과에 포함되어:
- 관련성 점수 왜곡
- 불필요한 청크 반환
- LLM 컨텍스트 낭비

### 3. 저장소 낭비

수천 개의 문서를 처리할 경우, 쓰레기 노드가 기하급수적으로 증가하여 **Neo4j/Fuseki의 저장 공간과 쿼리 성능**에 영향을 줍니다.

---

## 해결 방법

### 1. 추출 단계에서 필터링 (권장)

가장 효과적인 방법은 **LLM 응답을 파싱하는 시점에서 유효성 검사를 수행**하는 것입니다.

```python
# openai_extractor.py - 수정된 코드

def extract(self, chunk, run_id):
    llm_result = self.call_llm(prompt)
    
    for entity in llm_result.get("entities", []):
        name = entity.get("name", "").strip()
        
        # ✅ 빈 이름 필터링
        if not name:
            continue
        
        # ✅ 내부 ID 패턴 필터링 (선택적)
        if name.startswith("nle") or name.startswith("tmp_"):
            continue
        
        result.instances.append(InstanceCandidate(
            label=name,
            ...
        ))
    
    for triple in llm_result.get("triples", []):
        s = triple.get("subject", "").strip()
        p = triple.get("predicate", "").strip()
        o = triple.get("object", "").strip()
        
        # ✅ 불완전한 트리플 필터링
        if not s or not p or not o:
            continue
        
        result.triples.append(Triple(
            subject=s,
            predicate=p,
            object=o,
            ...
        ))
```

### 2. 프롬프트 개선

LLM에게 더 명확한 지침을 제공합니다:

```
반드시 다음 규칙을 따르세요:
1. 각 엔티티는 반드시 사람이 읽을 수 있는 `name` 필드를 가져야 합니다.
2. 내부 참조용 ID(예: "nle...", "tmp_")를 사용하지 마세요.
3. 이름이 불분명한 개념은 추출하지 마세요.
4. 트리플의 subject, predicate, object 모두 명시적인 값이어야 합니다.
```

### 3. 후처리 정리 스크립트

이미 저장된 노이즈 데이터를 정리해야 할 경우:

**Neo4j:**
```cypher
// 빈 라벨 노드 삭제
MATCH (n:Entity)
WHERE n.name IS NULL OR n.name = "" OR n.name STARTS WITH "nle"
DETACH DELETE n
```

**Fuseki (SPARQL):**
```sparql
DELETE WHERE {
  ?s rdfs:label ?label .
  FILTER(STR(?label) = "" || STRSTARTS(STR(?label), "nle"))
}
```

---

## 적용 결과

필터링 로직 적용 전후 비교:

| 항목 | 적용 전 | 적용 후 |
|------|---------|---------|
| 총 노드 수 | 350 | 200 |
| 쓰레기 노드 | 150 (43%) | 0 (0%) |
| 그래프 가독성 | ❌ | ✅ |
| 검색 정확도 | 낮음 | 높음 |

---

## 결론

LLM 기반 지식 그래프 추출은 강력하지만, **LLM 출력을 무조건 신뢰해서는 안 됩니다**. 다음 원칙을 적용하세요:

1. **입력 검증**: 모든 엔티티와 트리플에 대해 빈 값 체크
2. **패턴 필터링**: 알려진 노이즈 패턴(임시 ID 등) 차단
3. **프롬프트 강화**: LLM에게 명확한 출력 규칙 제시
4. **모니터링**: 주기적으로 그래프 품질 검사

이러한 방어적 프로그래밍을 통해 깨끗하고 활용 가능한 지식 그래프를 구축할 수 있습니다.

---

> **참고**: 이 글은 RAGaaS + Doc2Onto 프로젝트에서 실제로 발생한 문제를 해결한 경험을 바탕으로 작성되었습니다.
