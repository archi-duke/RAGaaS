# 설계문서: 온톨로지 스키마 추출 개선 (A안 — 구조 컨텍스트 주입)

- **상태**: Draft
- **작성일**: 2026-07-17
- **대상 코드**: `backend/app/graph2ontology/promoters/ontology_promoter.py`
- **관련 진단**: 승격 스키마가 과도하게 단순하게 생성되는 문제

---

## 1. 배경 및 문제 정의

온톨로지 승격(`POST /knowledge-bases/{kb_id}/promote`)은 `OntologyPromoter`의 7단계 파이프라인으로 KB의 인스턴스 그래프(ABox)에서 스키마(TBox)를 역설계한다. 핵심은 2단계 `_step2_schema_stabilization`에서 GPT-4o에게 스키마 생성을 요청하는 것이다.

### 현행 동작 (문제의 핵심)

`_step2`가 LLM에 전달하는 입력은 **평평한 두 개의 로컬네임 리스트**뿐이다:

```
candidate_concepts = {모든 subject/object URI의 로컬네임}   # 알파벳 정렬 후 상위 500개
candidate_relations = {모든 predicate URI의 로컬네임}        # 알파벳 정렬 후 상위 100개
```

즉 LLM은 **인물·장소 이름들의 나열 + 관계명 나열**만 받는다. 실제 트리플(S-P-O 패턴), 타입, 빈도수는 전혀 전달되지 않는다.

### 결과

1. 프롬프트는 "관찰된 그래프 패턴만 사용해 domain/range를 정하라(CRITICAL)"고 지시하지만, **정작 패턴을 하나도 보여주지 않는다.** LLM은 이름만 보고 추측한다.
2. 수백 개의 타입 없는 인스턴스가 소수의 일반 클래스로 뭉뜽그려진다 → 스키마가 실제보다 단순해진다.
3. domain/range는 근거 없이 이름 기반으로 환각(hallucination)된다.

> **상위 원인(별도)**: 실 서비스 인제스트(`ingest_service`)가 엔티티 타입을 의도적으로 제거하여(`noun_extractor.py`, `contextual_grouper.py`), Fuseki에는 `rdf:type` 엣지가 전혀 없다. 타입 복원은 재인제스트가 필요한 B안(별도 설계)으로 다룬다. 본 문서(A안)는 **인제스트를 건드리지 않고 기존 그래프만으로** 승격 품질을 끌어올린다.

---

## 2. 목표 / 비목표

### 목표
- LLM에 **실제 그래프 구조(관계별 트리플 샘플 + 빈도수)**를 주입하여, 근거에 기반한 풍부하고 정확한 스키마를 생성한다.
- domain/range를 **관찰된 실제 패턴**에서 도출한다.
- 승격된 TBox가 실제 인스턴스와 연결되도록 **인스턴스-타입 링크 버그(④)를 함께 수정**한다.
- 인제스트 파이프라인 변경 없음, 재인제스트 불필요.

### 비목표
- 인제스트 시점 타입 부여(B안)는 범위 밖.
- 프롬프트의 세부 few-shot 튜닝(C안)은 부수적으로 일부만 반영.
- Neo4j 백엔드 승격(현재 "Coming Soon")은 범위 밖. Fuseki(ontology) 백엔드만 대상.

---

## 3. 설계

### 3.1 핵심 아이디어

`_step2`에서 LLM에 넘기는 입력을 **평평한 이름 리스트 → 구조화된 그래프 프로파일**로 교체한다. 프로파일은 다음을 포함한다:

1. **관계 프로파일**: 각 predicate별로
   - 빈도수(해당 관계가 등장한 트리플 수)
   - 실제 예시 트리플 N개 `(subject_label) --predicate_label--> (object_label)`
2. **개념(노드) 빈도**: 자주 등장하는 인스턴스 라벨 상위 K개 (희소 노이즈 노드 구분용)
3. **기존 타입 힌트(있으면)**: `rdf:type` 엣지가 존재하는 경우 타입별 인스턴스 분포 (현행 rag.local 그래프에는 없지만, Doc2Onto/CLI 경로나 향후 B안 대비 방어적으로 처리)

이렇게 하면 LLM이 "성기훈 --출연--> 오징어게임", "정보라 --출연--> 오징어게임" 같은 **실제 패턴**을 보고 `출연: domain=Person, range=Show`를 근거 있게 도출할 수 있다.

### 3.2 새 헬퍼: `_build_graph_profile(g: Graph) -> dict`

`_step2` 진입부의 concept/relation 수집 로직을 대체하는 헬퍼를 신설한다.

**입력**: 병합된 rdflib `Graph` (라벨 포함)
**출력**:
```python
{
  "relations": [
    {
      "name": "출연",                    # predicate 로컬네임
      "count": 42,                        # 등장 빈도
      "examples": [                       # 최대 SAMPLES_PER_RELATION개
        {"s": "성기훈", "o": "오징어게임"},
        {"s": "정보라", "o": "오징어게임"},
        ...
      ]
    },
    ...
  ],
  "frequent_concepts": ["오징어게임", "성기훈", ...],   # 상위 K개 (빈도순)
  "type_hints": {                         # rdf:type가 있을 때만 채워짐 (없으면 {})
    "Person": ["성기훈", "오일남", ...],
    ...
  }
}
```

**구현 규칙**:
- Built-in 네임스페이스(RDF/RDFS/OWL/XSD/SKOS) predicate는 제외. 단 `rdf:type`은 `type_hints` 수집용으로 별도 처리.
- `rdfs:label`은 표시용 라벨 조회에만 사용하고 관계 목록에서는 제외.
- **라벨 조회**: URI → `rdfs:label` 값 우선, 없으면 URI 로컬네임. 헬퍼 `_label_of(g, uri)` 신설.
- **관계 정렬**: 빈도수 내림차순. 상위 `MAX_RELATIONS`(기본 60)개만 프롬프트에 포함하고, 잘린 개수는 로그로 남긴다(무음 절단 금지).
- **예시 선정**: 각 관계에서 서로 다른 subject를 우선해 다양성 확보(같은 subject 반복 회피), 최대 `SAMPLES_PER_RELATION`(기본 5)개.
- **object가 리터럴인 경우**: data property 후보 신호로 별도 표시(`"o_is_literal": true`). LLM이 object property와 data property를 구분하는 근거가 된다.
- **토큰 가드**: 프로파일 직렬화 결과가 과도하게 커지지 않도록 관계 수/예시 수/개념 수에 상한을 두고, 초과분은 절단 후 로그.

**상수(클래스 `__init__` 또는 모듈 상단)**:
```python
MAX_RELATIONS = 60
SAMPLES_PER_RELATION = 5
MAX_FREQUENT_CONCEPTS = 80
```

### 3.3 프롬프트 개편

현행 프롬프트의 `## INPUT DATA` 섹션(로컬네임 두 리스트)을 **구조화된 프로파일**로 교체한다. 나머지 STRICT RULES / EXTRACTION STEPS / OUTPUT FORMAT 골격은 유지하되 다음을 반영:

- INPUT DATA에 관계별 빈도 + 예시 트리플을 표 형태로 제시:
  ```
  ## OBSERVED GRAPH PATTERNS

  Relations (name, frequency, example triples):
  - 출연 (42×): 성기훈→오징어게임, 정보라→오징어게임, ...
  - 감독 (8×): 황동혁→오징어게임, ...
  ...

  Frequent entities: 오징어게임, 성기훈, 황동혁, ...

  (Known types, if any): <type_hints 또는 "none — infer from patterns">
  ```
- STEP 4(domain/range)를 "관찰된 예시 트리플의 subject/object 유형을 근거로 결정하라. **예시에 실제로 나타난 패턴만 사용**하라"로 강화.
- **단순화 편향 완화(C안 일부 반영)**:
  - 4-클래스짜리 고정 few-shot 예시가 클래스 수를 앵커링하므로, "예시는 형식 참고용이며 클래스 수는 그래프 복잡도에 맞게 결정하라"는 문장을 명시.
  - "prefer general, reusable concepts"는 유지하되 "단, 데이터에 반복적으로 나타나는 의미 있는 구분은 별도 클래스로 유지하라"를 추가해 과도한 병합 방지.
- `temperature`는 0.1 유지(재현성). 필요 시 후속 실험 항목으로 표시.

### 3.4 스키마 적용부

`_step2`의 후반부(LLM JSON → 그래프 반영: `get_class_uri`/`get_prop_uri`, owl:Class/ObjectProperty/DatatypeProperty/subClassOf 추가)는 **현행 로직 유지**. 입력 개편만으로 출력 품질이 개선되므로 이 부분은 변경 최소화한다.

`self.schema_info`(프론트 표시용) 저장 로직도 유지.

### 3.5 ④ 인스턴스-타입 링크 수정

현행 `_export_instance_types`는 "생성 클래스 URI로 이미 `rdf:type` 지정된 인스턴스"만 export하는데, rag.local 그래프에는 그런 인스턴스가 0개라 결과가 비어 승격 TBox가 ABox와 단절된다.

**수정 방향**: `_step2`에서 LLM이 반환한 domain/range 정보를 활용해 **인스턴스에 타입을 부여**한다.

- 각 ObjectProperty의 예시 트리플에서 관찰된 subject → domain 클래스, object → range 클래스로 `<instance> rdf:type <domainClass>` 트리플을 그래프에 추가한다.
- 즉, 프로파일 생성 시 수집한 "관계별 실제 (s,o) URI"를 보관했다가, LLM이 그 관계에 domain/range를 배정하면 해당 s/o URI들에 타입 엣지를 건다.
- 이렇게 하면 `_export_instance_types`가 정상적으로 인스턴스-타입 배정을 export하고, 승격된 온톨로지가 실제 데이터와 연결된다.

> **주의(정확도)**: 한 인스턴스가 여러 관계에서 다른 domain을 가질 수 있다(다중 타입). 이는 owl에서 허용되므로 중복 타입 부여를 허용한다. 다만 과도한 오분류를 막기 위해, 타입 부여는 **LLM이 그 관계에 domain/range를 명시적으로 배정한 경우에만** 수행한다.

### 3.6 변경 파일 요약

| 파일 | 변경 |
|---|---|
| `backend/app/graph2ontology/promoters/ontology_promoter.py` | `_step2_schema_stabilization` 입력부 교체, `_build_graph_profile`/`_label_of` 신설, 프롬프트 개편, 인스턴스 타입 부여 로직 추가 |

프론트/엔드포인트/모델 변경 없음. 응답 스키마(`promotion_metadata`)의 형태 불변.

---

## 4. 검증 방법

1. **단위 검증(오프라인)**: 대표 KB의 `base.trig`를 로드해 `_build_graph_profile` 출력이 관계 빈도·예시·라벨을 올바르게 담는지 확인.
2. **전/후 비교**: 동일 KB("test ot" 포함)를 개선 전/후로 승격하여
   - 생성된 클래스 수 / 속성 수
   - domain/range가 채워진 ObjectProperty 비율
   - `instance_types.ttl`의 타입 배정 건수(현행 ~0 → 개선 후 >0 기대)
   를 비교하고 결과를 표로 정리한다.
3. **리즈너 일관성**: `_step6` owlrl 검증이 `consistent=True`를 유지하는지 확인(순환/모순 미발생).
4. **회귀**: 승격 후 그래프 검색(`ontology_plus` 모드)이 정상 동작하고 `schema_info`가 프론트에 표시되는지 브라우저로 확인.
5. **토큰**: 프로파일 주입으로 프롬프트가 커지므로, 대형 KB에서 입력 토큰이 상한 내에 있는지 로그로 확인.

---

## 5. 리스크 및 완화

| 리스크 | 완화 |
|---|---|
| 프로파일이 커져 토큰/비용 증가 | `MAX_RELATIONS`/`SAMPLES_PER_RELATION`/개념 상한 + 절단 로그 |
| 예시 트리플의 라벨이 없거나 URI가 지저분함 | `_label_of` 폴백(로컬네임), URI 정리 |
| LLM domain/range 배정 오류로 잘못된 타입 부여 | 명시적 배정 시에만 타입 부여, 다중 타입 허용, 검증 단계에서 건수 리포트 |
| 대형 그래프에서 프로파일 계산 비용 | 단일 순회로 빈도/샘플 동시 수집, 상한으로 조기 종료 |

---

## 6. 구현 순서

1. `_label_of`, `_build_graph_profile` 헬퍼 신설 (+상수)
2. `_step2` 입력부를 프로파일 기반으로 교체
3. 프롬프트 개편(구조화 INPUT DATA + 편향 완화 문구)
4. 인스턴스-타입 부여 로직 추가(④ 수정)
5. 오프라인 전/후 비교 검증 → 표 정리
6. 핫패치 → 실제 KB 승격으로 브라우저 확인
7. 커밋 (feature 브랜치)

---

## 7. 작업 분담

- **설계/검증**: Fable
- **구현(코드 생성)**: Sonnet — 위 3장 스펙에 따라 `ontology_promoter.py` 수정
- **검증**: Fable — 전/후 비교, 리즈너 일관성, 회귀 확인
