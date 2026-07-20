# 설계문서: 구조화 문서(JSON/YAML) → 온톨로지 인제스트 (C안)

- **상태**: Draft
- **작성일**: 2026-07-19
- **작성**: Fable (설계) / 구현은 Sonnet, 검증은 Fable
- **관련**: [A안 승격 스키마 추출](design-ontology-schema-extraction-v2.md), [B안 인제스트 타입 부여](design-ingest-entity-typing-b.md)

---

## 1. 배경 및 목표

### 배경
현재 RAGaaS는 **모든 문서를 텍스트로 취급**한다(명사추출 + LLM 트리플 추출). JSON/YAML도 `file_utils.read_text_file`의 `else` 분기에서 **원문 텍스트로 읽혀** 프로즈처럼 청킹·LLM 추출된다. 그러나 구조화 문서는:
- **필드명이 곧 관계(predicate)의 의미**를 담고 있고,
- **중첩/참조가 곧 엔티티 간 관계**이며,
- (JSON Schema가 있으면) **구조 스키마가 곧 온톨로지 TBox**에 가깝다.

따라서 LLM 추측 없이 **결정론적으로, 더 정확하게** 그래프/온톨로지를 구성할 수 있다. 이는 현재 파이프라인의 취약점(트리플 추출 부정확성, 관계 파편화)을 원천 우회한다.

### 목표
1. `.json`/`.yaml`/`.yml` 문서를 **결정론적 필드→트리플 매핑**으로 그래프에 등록한다.
2. 각 엔티티에 **타입(rdf:type)** 을 부여한다(B안 메커니즘 재사용).
3. **기존 온톨로지가 있는 KB**에서는 들어오는 구조를 **기존 TBox에 정렬(align)** 하여 중복 클래스 난립(파편화)을 막는다.
4. 구조화 데이터도 **벡터/키워드 검색 대상**이 되도록 한다(텍스트 문서와 동일 검색 풀).
5. 하류 저장(Milvus/Fuseki/Neo4j)·트리플 형태·승격 경로를 **최대한 재사용**한다.

### 비목표(초기 범위 밖)
- 완전 자동 온톨로지 정렬/병합의 고급 추론(equivalentClass 자동 판정 등) — 초기엔 규칙+LLM 보조 수준.
- 대규모 스트리밍/증분 diff 인제스트 — 초기엔 문서 단위 처리.
- CSV/XML 등 다른 구조 포맷 — JSON/YAML 우선, 확장 가능하게 설계.

---

## 2. 전체 아키텍처

### 분기점
파일 확장자가 `.json`/`.yaml`/`.yml`이면(그리고/또는 신규 `extractor_type="structured"`), **텍스트 파이프라인(read_text_file → restore_subjects → ingest_pipeline.process) 대신 구조화 경로**로 분기한다.

```
ingest.py process_ingest_job
  ├─ (기존) 텍스트: read_text_file → subject_restoration → pipeline.process ──┐
  └─ (신규) 구조화: StructuredGraphExtractor.process(file_path, kb_id) ───────┤
                                                                              ▼
                                        result = {triples, nodes, embeddings, ...}
                                                                              ▼
                              (기존 재사용) Milvus insert_chunks + Fuseki/Neo4j insert_triples
```

구조화 경로는 **기존과 동일한 `result` 형태**(`triples`, `nodes`, `embeddings`, `node_count`, `triple_count`, `stats`)를 반환하여 하류 저장부(ingest.py 246-314)를 그대로 재사용한다.

### 신규 모듈
- `ingest_service/app/core/structured_extractor.py` — 파싱·매핑·타입부여·검색용 verbalization의 핵심.
- `ingest_service/app/core/ontology_aligner.py` — 기존 TBox 조회 + 정렬(align) 로직(3단계 이후).
- (파일 읽기) `file_utils.py`는 그대로 두고, 구조화 경로는 `file_path`에서 직접 `json.load`/`yaml.safe_load` 한다(원문 필요).

---

## 3. 결정론적 매핑 규칙 (JSON/YAML → 트리플)

트리플 dict 형태는 기존과 동일: `{subject, predicate, object, source_node_id, confidence, subject_type, object_type, is_inverse}`. 네임스페이스도 기존 재사용 → 텍스트 그래프와 자연 통합:
- 엔티티 URI: `http://rag.local/inst/{id}`
- 관계 URI: `http://rag.local/rel/{fieldname}`
- 클래스: `http://rag.local/class/{Type}` (B안과 동일)

### 3.1 객체 → 노드(엔티티)
JSON object → 하나의 엔티티 노드. 노드의 **식별자(identity)** 는 §4 정책으로 결정.

### 3.2 필드 → predicate (핵심)
| 필드 값 | 매핑 | 예 |
|---|---|---|
| 스칼라(string/number/bool) | **데이터 속성(literal)**: `subject_type` 부여, object는 리터럴 | `player.name="성기훈"` → `player :name "성기훈"` |
| 중첩 객체 | **객체 속성 + 하위 엔티티 재귀 생성** | `player.address={...}` → `player :address addr1`, `addr1 ...` |
| 참조(id 문자열) | **객체 속성**(§4에서 참조로 판정 시) | `player.gameId="g1"` → `player :game g1` |
| 배열(스칼라) | 같은 predicate로 **다중 리터럴** | `tags:["a","b"]` → 두 트리플 |
| 배열(객체) | 같은 predicate로 **다중 엣지 + 각 하위 엔티티** | `games:[{...},{...}]` |

- **필드명 = predicate 로컬네임.** 축약형/카멜케이스는 그대로 두되, §6에서 기존 어휘로 정규화 가능.
- 리터럴의 xsd 타입은 JSON 타입에서 유추(number→xsd:integer/double, bool→xsd:boolean, ISO 문자열→xsd:dateTime).

### 3.3 배열/중첩 규칙
- 최상위가 배열이면 각 원소를 개별 엔티티로.
- 최상위 컨테이너 키(예: `"participants": [...]`)는 각 원소의 **클래스 힌트**(단수화 → `Participant`)로 사용(§5).
- 익명 중첩 객체(식별자 없음)는 **blank node** 또는 부모+필드 기반 결정론적 URI로 생성.

---

## 4. 엔티티 식별(identity) 정책

노드 URI를 무엇으로 삼을지가 그래프 품질을 좌우한다.

1. **명시적 id 키 우선**: 설정 가능한 id 필드 목록(기본 `id`, `@id`, `uuid`, `_id`, `key`). 있으면 `inst/{id}`.
2. **참조 판정**: 문자열 값이 다른 객체의 id와 일치하면 **리터럴이 아니라 객체 속성(참조)** 으로 처리 → 엔티티 간 연결(FK). (문서 내 id 인덱스를 먼저 1패스로 수집)
3. **라벨 필드**: `name`/`title`/`label` 등은 `rdfs:label`로도 부여(검색·표시용).
4. **id 없음(익명)**: 부모 경로+인덱스 기반 결정론적 URI 또는 blank node. 라벨이 있으면 라벨 기반 URI(텍스트 그래프와 병합되도록).

> id 키/참조 필드는 KB 또는 요청 단위 **매핑 설정**으로 오버라이드 가능하게 설계(초기엔 기본 휴리스틱).

---

## 5. 타입(클래스) 부여

각 엔티티의 클래스를 아래 우선순위로 결정하고 `rdf:type` 방출(B안 fuseki/neo4j 재사용):
1. **명시적 타입 필드**: `type`/`@type`/`kind`/`class`.
2. **컨테이너 키**: 배열 키의 단수형(`participants` → `Participant`).
3. **JSON Schema definition 이름**(스키마가 있으면, §7).
4. 없으면 폴백 `Entity`(방출 제외).

B안의 classifier(LLM 자유 분류)는 **여기선 기본 불필요** — 구조가 타입을 준다. 다만 위 1~3이 모두 없을 때만 선택적으로 classifier 보조 가능.

---

## 6. 온톨로지 인지 정렬 (ontology-aware alignment) ★기존 TBox가 있는 KB

빈 KB면 위 매핑으로 충분하지만, **이미 온톨로지가 구성된 KB**면 파편화를 막기 위해 **기존 TBox에 정렬**한다.

### 6.1 기존 TBox 읽기
- Mongo `kb.promotion_metadata.schema_info` → `{classes:{uri:{count,instances}}, properties:[uri]}` (구조 확인됨)
- 또는 Fuseki `urn:ontology:{kb_id}` 그래프 SPARQL(권위 있는 RDF)

### 6.2 정렬 매칭
들어오는 구조의 후보 클래스/속성을:
- **정확 일치**(로컬네임/라벨) → 기존 URI **재사용**
- **유사 일치**(동의어/표기 차이) → LLM 보조로 매핑 제안 → 재사용 or 매핑테이블 기록
- **미일치** → "신규 후보"로 표시

### 6.3 정렬 방식 — 불일치 시에만 사용자 검토(UI, human-in-the-loop) ★확정
정적 정책(closed/open/hybrid)을 두지 않는다. 대신 **상황을 감지해 제안을 만들고, 불일치가 있을 때만 사용자에게 검토를 요청**한다.

**적용 조건 (결정)**: 정렬·검토는 **KB가 온톨로지 승격된 상태(`kb.is_promoted == True`)일 때만** 작동한다. 승격 전에는 등록된 TBox 자체가 없으므로 정렬 대상이 없다.
- **승격 안 됨(`is_promoted=False`)** → 정렬/검토 없음. 결정론적 매핑으로 **ABox(인스턴스+타입)만 누적**. (이후 사용자가 A안 승격하면 TBox 생성)
- **승격됨 + 후보가 기존 TBox와 100% 일치** → **검토 없이 자동 커밋**
- **승격됨 + 신규/충돌/무관(disjoint) 감지** → **검토 UI 표시** 후 사용자 결정으로 커밋

즉 트리거 = `is_promoted AND 불일치 존재`. 그 외에는 프리뷰 없이 바로 인제스트.

**검토 흐름 (결정)**: 별도의 낯선 단계가 아니라 **기존 preview/confirm 흐름에 통합**한다(RAGaaS의 `enable_normalization_confirmation` → `create_preview` → `confirm` 패턴의 형제). 자연스러운 기존 인제스트 흐름 유지.

**검토 화면 (항목별 결정)**: 각 불일치 후보에 스마트 기본값을 미리 채우고, 사용자가 항목별로 선택:
| 감지 | 사용자 선택지 |
|---|---|
| 🆕 신규 클래스/속성 | [신규 추가] / [기존 X에 매핑] / [무시] |
| 🔶 유사(부분일치) | [기존 X에 병합(기본 제안)] / [신규 유지] / [subclass로] |
| ⚠️ 무관(disjoint) | [경고 후 그래도 추가] / [별도 KB 권고] / [취소] |

**결정의 지속성 (결정)**: 초기엔 **매핑 규칙을 저장하지 않는다** — **문서 등록 때마다 검토**. (반복 최적화·규칙 저장은 후속 과제.)

### 6.4 서로 다른 스키마의 처리(사용자 관심사)
불일치 유형은 6.3의 검토 화면에서 항목별로 처리:
- **보완적(연결됨)**: 대개 신규 클래스로 추가되지만 기존과 무관치 않음 → 참조를 관계로 연결. (신규가 소수면 검토가 가벼움)
- **겹침(부분일치)**: 유사 감지 → 기존 클래스 병합/subclass를 기본 제안.
- **무관(disjoint)**: 경고와 함께 "별도 KB 권고"를 제시하되 최종 선택은 사용자.

---

## 7. JSON Schema 인지 (선택 입력)

문서에 JSON Schema가 동반되거나 KB에 등록돼 있으면 **권위 있는 TBox 소스**로 사용:
- `definitions`/`$defs`/named object → `owl:Class`
- property(scalar) → `owl:DatatypeProperty`+range, property(object/$ref) → `owl:ObjectProperty`+range
- `required` → cardinality(초기엔 SHACL 대신 메타로 기록), `enum` → 통제 어휘
- `allOf`+`$ref` → `rdfs:subClassOf`

스키마가 없으면 **인스턴스에서 유도**(현 A안이 하는 일이지만 구조 신호라 훨씬 정확). → 이 경우 TBox는 A안 승격으로 확정.

> 초기 범위: JSON Schema **감지 시 클래스/속성/도메인·레인지까지 결정론적 반영**, 없으면 인스턴스 기반 클래스만. 고급 제약(SHACL) 매핑은 후속.

---

## 8. 검색 통합 (벡터/키워드)

구조화 데이터도 KB 검색 풀에 들어와야 한다(§검색은 KB 전체 대상). 따라서:
- 각 **최상위 레코드(또는 엔티티)** 를 **텍스트로 verbalize**(예: `"성기훈 (Participant): number=456, appearedIn=오징어게임"`)하여 **1 청크 = 1 노드**로 Milvus에 저장 + 임베딩.
- 트리플의 `source_node_id`를 그 청크 id로 연결(§6.8 기존 chunk_id 링크 재사용) → 그래프 검색이 증거 청크를 붙일 수 있음.
- 결과: 구조화 문서가 벡터/키워드/하이브리드 검색 + 그래프 검색 **모두**에서 검색됨.

---

## 9. TBox 반영 / 승격 관계

- **모두 기존 클래스에 매핑됨(케이스1)** → ABox 인스턴스만 추가, TBox 불변, **재승격 불필요.**
- **신규 클래스 확장(진화형)** → `urn:ontology:{kb_id}` + `schema_info`에 클래스/속성 추가, 리즈너 일관성 재검증, 버전업. 또는 A안 **증분 재승격** 트리거.
- **빈 KB에 첫 구조화 문서** → ABox+타입 생성 후 A안 승격 시 type_hints가 채워져(=B안 효과) 스키마가 결정론적으로 확정.

---

## 10. API / 모델 변경

- **파일 타입 자동 구동 (확정)**: `file_type == json|yaml|yml`이면 자동으로 구조화 경로. Document.file_type 이미 저장되므로 **모델 스키마 변경 불필요**. (텍스트로 처리하고 싶으면 향후 옵션으로 무력화 여지)
- **정렬 검토 = 기존 preview/confirm 재사용 (확정)**: 별도 정책 플래그를 두지 않음. 불일치 감지 시 `create_preview`가 **정렬 제안(alignment proposal)** 을 반환하고, 사용자 확인 후 `confirm`으로 커밋. 일치/빈 KB면 프리뷰 없이 바로 인제스트.
  - preview 응답에 신규 필드: `alignment` = `{matched:[...], new:[...], similar:[{candidate, suggested, score}], disjoint:[...]}`
  - confirm 요청에 신규 필드: `alignment_decisions` = 항목별 사용자 선택(merge/create/map-to/ignore/skip)
- backend `document.py`/`ingest_client`/ingest_service의 preview·confirm 경로에 위 필드 배선(B안과 동일한 배선 패턴).
- **매핑 규칙 저장 없음 (확정)**: 문서 등록마다 검토. `promotion_metadata`/별도 컬렉션에 규칙을 저장하지 않음(후속 과제).
- **id/참조/타입 필드 휴리스틱**: 기본 내장. KB/요청 단위 오버라이드는 후속(초기엔 기본값).

---

## 11. 처리 파이프라인 (end-to-end)

```
1. 파일 타입 감지 (.json/.yaml) → 구조화 경로 분기
2. 파싱 (json.load / yaml.safe_load)
3. id 인덱스 1패스 수집 (참조 판정용)
4. 재귀 매핑: 객체→노드, 필드→predicate, 값→리터럴/참조, 배열→다중
5. 타입 부여 (§5) → rdf:type
6. [kb.is_promoted 일 때만] 기존 TBox와 대조 → 불일치 감지
     - 미승격 / 일치 → 바로 8로 (정렬 없음)
     - 승격됨 + 불일치 → preview로 정렬 제안 반환 → 사용자 검토(UI) → confirm의 결정 적용
7. 엔티티 동일성: 기존 KB 인스턴스와 매칭 → 병합 or 신규
8. verbalize → 청크+임베딩 (검색용, §8)
9. result 조립 → Milvus insert_chunks + Fuseki/Neo4j insert_triples (기존 재사용)
10. [신규 클래스 확장 결정 시] TBox 갱신 + 일관성 재검증
```

---

## 12. 단계별 구현 계획

### Phase 1 — MVP: 결정론적 매핑 + 타입 (빈 KB / 정렬 없음)
- `structured_extractor.py`: 파싱, id 정책, 필드→트리플, 배열/중첩, 타입 부여, verbalize+청크.
- ingest.py 분기(process_ingest_job + create_preview 양쪽), result 조립, 하류 재사용.
- 플래그 배선(file_type 구동). Fuseki/Neo4j/Milvus 저장 확인.
- **산출**: JSON/YAML 등록 → 결정론적 그래프 + rdf:type + 검색 가능.

### Phase 2 — 온톨로지 인지 정렬 + 불일치 검토 UI (기존 TBox 있는 KB)
- `ontology_aligner.py`: schema_info/Fuseki에서 기존 TBox 로드, 정확·유사 매칭(LLM 보조), **불일치 감지**.
- **검토 흐름**: 불일치 시 `create_preview`가 `alignment` 제안 반환 → 프론트 **정렬 검토 화면**(항목별 merge/create/map-to/ignore, disjoint 경고) → `confirm`의 `alignment_decisions` 적용. 일치/빈 KB는 프리뷰 생략하고 바로 커밋.
- 엔티티 동일성(기존 인스턴스 매칭/병합).
- 매핑 규칙 저장 없음(문서마다 검토).
- **산출**: 다른 스키마 문서를 사용자 검토로 기존 온톨로지에 정렬(파편화 방지).

### Phase 3 — JSON Schema 인지 + TBox 진화
- JSON Schema 감지 시 클래스/속성/도메인·레인지 결정론적 반영.
- 진화형 정책: TBox 확장 + 일관성 재검증 + 증분 승격.
- (후속) SHACL 제약, CSV/XML 확장, 매핑 설정 UI.

---

## 13. 검증 방법
1. **매핑 단위 테스트(오프라인)**: 대표 JSON/YAML(중첩·배열·참조·타입 필드) → 기대 트리플/타입 검증.
2. **참조 연결**: FK 문자열이 객체 속성으로 연결되는지, 문서 내 교차참조.
3. **실 저장 e2e**: 소규모 JSON 인제스트 → Fuseki rdf:type + 관계 확인, Milvus 청크 검색 확인.
4. **정렬(Phase 2)**: 기존 TBox 있는 KB에 다른 스키마 등록 → 매칭 재사용/신규 flag 동작.
5. **검색 통합**: 구조화 문서가 벡터+그래프 검색에 모두 잡히는지.
6. **회귀**: 텍스트 문서 인제스트는 완전 불변(구조화 경로 미개입).

---

## 14. 리스크 및 완화
| 리스크 | 완화 |
|---|---|
| id/참조 판정 오류(리터럴↔엔티티 혼동) | 문서 내 id 인덱스 기반 판정, 설정 오버라이드, 애매하면 리터럴 보수적 처리 |
| 필드명 난립(축약형) → 지저분한 predicate | §6 정렬/어휘 정규화, 매핑 설정 |
| 정렬 오매칭(다른 개념을 같은 클래스로) | 정확 일치 우선, 유사는 LLM 보조+flag, 자동 병합 신중 |
| 무관 스키마 혼입 → 파편화 | disjoint 감지 시 경고/별도 KB 권고 |
| 깊은 중첩/순환 참조 | 재귀 깊이 제한, 방문 집합, 순환은 참조 엣지로 |
| 대용량 JSON 토큰/메모리 | 스트리밍 파싱 여지, 레코드 단위 처리, 상한+로그 |

---

## 15. 작업 분담
- **설계/검증**: Fable
- **구현**: Sonnet (본 문서 기준, Phase 1→2→3)
- **검증**: Fable (매핑 단위/실 저장 e2e/정렬/검색/회귀)

---

## 부록: 매핑 예시

입력:
```json
{ "participants": [
    { "id": "p456", "type": "Participant", "name": "성기훈", "number": 456,
      "playedGames": ["g1"] } ],
  "games": [ { "id": "g1", "name": "무궁화꽃", "order": 1 } ] }
```
출력 트리플(요약):
```
inst/p456 rdf:type class/Participant
inst/p456 rdfs:label "성기훈"
inst/p456 rel/number "456"^^xsd:integer
inst/p456 rel/playedGames inst/g1        # 참조 → 객체 속성
inst/g1  rdf:type class/Game
inst/g1  rdfs:label "무궁화꽃"
inst/g1  rel/order "1"^^xsd:integer
```
+ verbalize 청크 2개(p456, g1) → Milvus 저장, source_node_id로 트리플과 연결.
