# 설계문서: 인제스트 시점 엔티티 타입 부여 (B안)

- **상태**: Draft
- **작성일**: 2026-07-17
- **대상**: `ingest_service/` (엔티티 추출 → 트리플 → Fuseki/Neo4j)
- **관련**: [A안](design-ontology-schema-extraction-v2.md) — 승격 스키마 추출 개선. B안은 A안의 상위(근본) 개선.

---

## 1. 배경 및 문제

A안으로 승격 시 실제 트리플 패턴을 LLM에 주입해 스키마 품질을 크게 올렸다. 그러나 상위 제약이 남아 있다: **인제스트가 엔티티 타입을 전혀 저장하지 않는다.**

현행 인제스트 타입 흐름(조사 결과):
- `noun_extractor.py`: recall 극대화를 위해 **"명사만" 추출**하도록 변경됨(타입 추출 프롬프트 제거). 결과는 `List[str]`.
- `noun_extractor.py:79`, `contextual_grouper.py:63`: 엔티티 타입을 **`"Entity"`로 강제**.
- 트리플 dict(`subject/predicate/object/source_node_id/confidence`)에는 **타입 필드 없음**.
- `fuseki_connector.insert_triples`: `inst/X --rel/Y--> inst/Z` + `rdfs:label`만 기록. **`rdf:type` 엣지 없음.**
- Neo4j: 모든 노드가 generic `:Entity` 라벨.

→ Fuseki에는 타입 없는 인스턴스만 존재 → 승격 시 `type_hints`가 비어 LLM이 타입을 추측해야 함. A안이 이를 완화했지만, **ground-truth 타입이 있으면 승격 품질이 근본적으로 개선**되고, 그래프 검색·필터링에도 타입을 활용할 수 있다.

### 핵심 제약: 타입 소스가 없음
타입 추출을 되살리는 가장 단순한 방법(추출 프롬프트에서 name+type 요구)은 **과거에 recall 저하로 제거된 방식**이다. 되돌리면 엔티티 누락이 재발한다. 따라서 **고recall 명사 추출은 그대로 두고, 타입은 별도 패스로 부여**한다.

---

## 2. 목표 / 비목표

### 목표
- 인제스트 시 각 엔티티에 **의미 있는 클래스 타입**을 부여하고 Fuseki에 `rdf:type` 엣지로 저장한다.
- 명사 추출 recall을 **저하시키지 않는다**(추출 프롬프트 불변).
- 기능을 **opt-in 플래그로 게이팅**하여 기존 파이프라인/데이터에 영향 없이 "시도" 가능하게 한다.
- A안 승격이 이 `rdf:type`를 자동으로 `type_hints`로 소비하여 스키마가 풍부해진다.

### 비목표
- Neo4j 동적 라벨은 **후속 단계**(1차는 Fuseki `rdf:type`만). 인터페이스는 확장 가능하게 둔다.
- 기존 인제스트 문서 소급 적용(백필)은 범위 밖 — 신규/재인제스트 시에만 적용.
- 온톨로지 클래스 계층(subClassOf) 자동 생성은 승격(A안) 몫으로 유지.

---

## 3. 설계

### 3.1 전체 흐름

```
noun_extractor (명사만, 고recall)  ──►  contextual_grouper (정규화)  ──►  entity_dictionary {name: {type:"Entity", variants, chunk_ids}}
                                                                                    │
                                                            [NEW] EntityTypeClassifier (opt-in)
                                                                                    │  타입 부여
                                                                                    ▼
                                                            entity_dictionary {name: {type:"Person"|"Show"|..., ...}}
                                                                                    │
                          pipeline.extract_graph: 트리플 생성 시 subject/object 이름 → 사전 타입 조회하여
                          triple dict에 subject_type / object_type 부착 (Seam B)
                                                                                    │
                                                                                    ▼
                          fuseki_connector: inst/X rdf:type class/<Type> 엣지 추가 (+ 기존 label/relation)
```

### 3.2 [NEW] `EntityTypeClassifier` — 추출 후 타입 분류 패스

**파일**: `ingest_service/app/core/entity_type_classifier.py` (신설)

**입력**: 정규화된 엔티티 사전 `{canonical_name: {type, variants, chunk_ids}}` + (선택) 문서 도메인 힌트.
**출력**: `{canonical_name: <class_label>}`.

**동작**:
- 중복 제거된 canonical 엔티티 목록을 배치로 묶어 **1~N회 LLM 호출**로 각 엔티티에 간결한 클래스 라벨을 배정.
- 프롬프트 원칙:
  - "각 엔티티에 대해 가장 적합한 **일반 클래스**(예: Person, Organization, Location, Date, Event, Work, Concept 등)를 배정하라."
  - **일관성 우선**: 유사 엔티티는 동일 라벨. 새 라벨 남발 금지.
  - 판단 불가 시 `Entity`(폴백)로 둔다 — 누락 없이 전량 분류.
  - 출력은 `{"name": "...", "type": "..."}` JSON 배열.
- **어휘 정책**: 폐쇄형(고정 목록)이 아니라 **가이드형 개방 어휘** — 소수의 권장 클래스를 제시하되 도메인 특화 클래스도 허용. (폐쇄형은 도메인 다양성에 취약, 완전 개방형은 파편화 위험 → 중간.)
- **배치/토큰 가드**: 엔티티가 많을 때 배치 분할, 배치당 상한. 무음 절단 금지(로그).
- 재사용성: `noun_extractor`/`contextual_grouper`와 동일한 LLM 클라이언트 주입 패턴을 따른다.

> 대안(기각): 추출 프롬프트에 타입 복원 → recall 저하로 기각. 승격 시점 타입 도출 → 이미 A안이 담당.

### 3.3 사전에 타입 반영

`EntityTypeClassifier` 결과로 `entity_dictionary[name]["type"]`를 갱신한다.
- `contextual_grouper.py:63`의 `"type": "Entity"` 강제는 **초기값으로 유지**(분류 실패/비활성 시 안전 폴백).
- 분류 패스가 활성일 때만 그 값을 덮어쓴다. 즉 grouper는 그대로 두고, 그 **뒤에** classifier를 파이프라인에 삽입.

### 3.4 트리플에 타입 부착 (Seam B — writer 시그니처 최소 변경)

`pipeline.py extract_graph`에서 트리플 dict 생성 시(현행 720-737행) subject/object의 canonical 이름을 `entity_dictionary`로 조회해 타입을 부착:

```python
node_triples.append({
    "subject": s, "predicate": p, "object": o,
    "source_node_id": node.node_id,
    "confidence": conf,
    "subject_type": _lookup_type(entity_dictionary, s),   # NEW (없으면 None)
    "object_type":  _lookup_type(entity_dictionary, o),   # NEW
})
```

- `_lookup_type`: canonical 이름 직접 매칭 + variants 역인덱스로 별칭 매칭. 미발견 시 `None`.
- 이 방식은 임시 저장/프리뷰 캐시를 통해 자동으로 흐르며, `insert_triples` 시그니처를 바꾸지 않는다(트리플 dict의 선택 필드만 추가).

### 3.5 Fuseki writer — `rdf:type` 방출

`fuseki_connector.py _convert_triples_to_rdf`(37-59행)에서 각 트리플의 `subject_type`/`object_type`가 있으면 타입 엣지 추가:

```python
CLASS_NS = "http://rag.local/class/"
...
if t.get("subject_type"):
    cls = self._sanitize_uri(t["subject_type"])
    rdf_lines.append(f'{s_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{CLASS_NS}{cls}> .')
if t.get("object_type"):
    cls = self._sanitize_uri(t["object_type"])
    rdf_lines.append(f'{o_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{CLASS_NS}{cls}> .')
```

- 네임스페이스는 `http://rag.local/class/`. A안 `_build_graph_profile`의 `type_hints`는 object localname만 사용하므로 네임스페이스 불일치 문제 없음.
- `Entity`(폴백) 타입은 잡음이므로 **`rdf:type` 방출에서 제외**(의미 있는 타입만 기록).

### 3.6 Neo4j (후속)
`neo4j_connector`는 1차 범위에서 제외. 인터페이스상 트리플 dict에 타입 필드가 있으므로, 후속에 `apoc.create.addLabels`로 동적 라벨 부여 가능. 본 설계에서는 미구현(문서화만).

### 3.7 설정 게이트
- 신규 플래그 `enable_entity_typing`(기본 **False**). 파이프라인 config/요청 옵션으로 전달.
- False면 현행과 100% 동일(classifier 미실행, 타입 필드 미부착, rdf:type 미방출).
- KB 생성/파이프라인 빌더 UI에 옵션 노출은 후속(우선 백엔드 플래그).

### 3.8 A안과의 상호작용
B 활성 후 Fuseki에 `rdf:type`가 생기면:
- A안 `type_hints`가 채워져 승격 LLM이 **ground-truth 클래스**를 받는다 → 스키마 클래스 다양성/정확도 상승.
- A안 §E 인스턴스 타이핑은 `source_relations` 기반 유지하되, 향후 rdf:type 직접 승격도 가능(후속 최적화).

---

## 4. 변경 파일 요약

| 파일 | 변경 |
|---|---|
| `ingest_service/app/core/entity_type_classifier.py` | **신설** — 추출 후 타입 분류 패스 |
| `ingest_service/app/core/pipeline.py` | classifier 호출 삽입(사전 타입 갱신) + 트리플에 subject/object_type 부착 + 플래그 처리 |
| `ingest_service/app/core/fuseki_connector.py` | 타입 필드 → `rdf:type` 엣지 방출 |
| (config) | `enable_entity_typing` 플래그 배선 |

`contextual_grouper.py`/`noun_extractor.py`는 **변경하지 않음**(recall 보존, Entity는 안전 폴백으로 유지).

---

## 5. 검증 방법

1. **classifier 단위 테스트(오프라인)**: 합성 엔티티 목록 → 타입 배정 형태/일관성/폴백 확인(LLM 목킹 + 실호출 1회).
2. **트리플 부착 확인**: `extract_graph` 결과 트리플에 subject/object_type가 붙는지(사전 매칭·별칭 매칭 포함).
3. **Fuseki 방출 확인**: 소규모 문서 재인제스트 후 `SELECT ?i ?c WHERE { ?i rdf:type ?c }`로 인스턴스 타입 엣지 생성 확인, Entity 제외 확인.
4. **A안 연동 확인**: 타입 부여된 KB를 승격 시 `type_hints`가 채워지고 클래스 다양성이 오르는지 전/후 비교.
5. **게이트 확인**: 플래그 False에서 기존 동작과 diff 없음(트리플/그래프 동일).
6. **recall 회귀**: 명사 추출 결과 수가 타이핑 활성/비활성 간 동일한지(추출 프롬프트 불변 확인).

---

## 6. 리스크 및 완화

| 리스크 | 완화 |
|---|---|
| 타입 분류 LLM 비용/지연(엔티티 많을 때) | 중복 제거된 canonical 목록만 분류, 배치, opt-in 게이트 |
| 클래스 어휘 파편화 | 가이드형 개방 어휘 + 일관성 강조 프롬프트 |
| 오분류로 잘못된 rdf:type | Entity 폴백 제외, 승격 단계에서 재검증(A안), 소급 백필 안 함 |
| 재인제스트 필요 | opt-in, 신규/재인제스트만 적용 — 기존 데이터 무영향 |
| 임시 캐시/프리뷰 경로 호환 | Seam B(선택 필드)로 시그니처 불변, 캐시 통해 자동 전파 |

---

## 7. 구현 순서

1. `EntityTypeClassifier` 신설 + 오프라인 단위 검증
2. `pipeline.py` classifier 삽입 + 트리플 타입 부착 + `enable_entity_typing` 플래그
3. `fuseki_connector.py` rdf:type 방출
4. 게이트 off 회귀 확인 → 소규모 문서로 타이핑 on 재인제스트 → Fuseki 타입 엣지 확인
5. A안 승격 전/후 비교(type_hints 효과)
6. 커밋(feature 브랜치)

---

## 8. 작업 분담
- **설계/검증**: Fable
- **구현**: Sonnet (본 문서 3장 스펙)
- **검증**: Fable (단위/연동/게이트/recall 회귀)
