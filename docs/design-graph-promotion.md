# 그래프 → 온톨로지 승격 재설계 (텍스트 경로)

- 작성일: 2026-11-15
- 관련: `docs/design-ontology-schema-extraction-v2.md`, `docs/design-schema-mismatch.md`, `docs/design-graph-class-query.md`, `docs/design-graph-relation-targeting.md`

## 1. 의도한 흐름 (소유자)
구조화 문서(YAML/JSON)는 처음부터 스키마가 있다. 일반 텍스트는 스키마가 없으므로 다음 순서를 따른다.
1. 텍스트를 인제스트하면 LLM이 지식 그래프를 추출한다. 이 단계에는 스키마가 없다.
2. 한동안 그래프로 사용한다.
3. **승격**: 그래프에서 스키마를 추론(유도)한다.
4. **그래프 데이터를 그 스키마에 맞게 재구성**한다.
5. 그 결과 TBox와 스키마를 따르는 ABox를 갖춘 온톨로지가 되고, 스키마 인지 검색에 쓰인다.

**검증 스토리**: 아키텍처 스타일 10개(YAML)를 자연어 `.md`로 다시 써서 KB `test-ontology2`에 텍스트로 적재한다. 이를 승격해 YAML 경로(`test-ontology`)와 비교한다.

## 2. 현재 상태 — 갭
| 단계 | 현재 | 갭 |
|---|---|---|
| 텍스트 → 그래프 | 청크별 LLM 추출, 역관계 `inverse_*` 기본 생성 | predicate가 통제되지 않는다 (한↔영 혼용, 문장형 노드) |
| 스키마 유도 | `OntologyPromoter` Step 2 LLM 프롬프트 | 아래 결함 1~6 |
| **ABox 재구성** | **없음** — `instance_types.ttl`(rdf:type)만 적재 | predicate 병합, 엔티티 병합, 값 정규화가 모두 없다 |
| 스키마 인지 검색 | C 경로만 `schema_info` 사용 | 결함 6으로 실효가 없다 |
| 승격 후 새 텍스트 문서 | 정합성 검사·추출 유도 없음 | 단일 세그먼트 key 규칙만 적용된다 |
| 스키마 최신성 | Mongo 스냅샷 | 문서가 추가·삭제돼도 갱신되지 않는다 |

### 발견한 결함
1. **URI 불일치**: TBox(`http://example.org/onto/prop/…`, LLM이 새로 지은 이름)와 데이터(`http://rag.local/rel/장점`)의 URI가 다르다. JSON Schema 변환도 같은 문제가 있다.
2. **이전 TBox 재입력**: 내보내기가 UnionGraph 전체를 대상으로 해서 `urn:ontology` 그래프가 포함된다. 재승격하면 이전 TBox가 다시 입력으로 들어간다.
3. **메타·역관계 오염**: 프로파일에 `meta:sourceNodeId·docId·confidence`와 `inverse_*`가 관계로 집계된다. 그 결과 `MAX_RELATIONS=60` 상한에 걸려 실제 관계가 잘린다.
4. **필터 무효**: Step 1 confidence·근거 필터가 Fuseki 경로에서 아무것도 거르지 않는다 (`evidence_path=None`).
5. **동의어 병합 미실행**: `owl:sameAs` 병합 코드가 `return` 뒤에 있어 실행되지 않는다.
6. **C 경로 키 불일치**: 승격은 `schema_info["properties"]`를 쓰고, `sparql_generator`는 `relations`를 읽는다.
7. **과도한 타입 부여**: domain/range로 타입을 일괄 부여해 한 엔티티가 여러 타입을 받는다. 이때 `infer_kinds`는 그중 하나를 임의로 고른다.
8. **클래스 네임스페이스 이원화**: `example.org/onto/class/`와 `rag.local/class/` 두 가지가 쓰인다.
9. **`is_promoted`의 세 가지 의미**: 유도 승격, JSON Schema 등록, 구조화 업로드 preview 분기에 함께 쓰인다. revert하면 선언 TBox까지 지워진다.
10. **텍스트 문서 재정규화 불가**: 원본이 삭제되므로 재정규화하려 하면 항상 `needs_source`가 된다.

### 실측 (test-ontology2, micro-frontend.md 1건, 기본 설정)
- 트리플 30개가 나왔다. 같은 스타일을 YAML로 넣었을 때는 약 60개다.
- 관계 이름이 혼재한다: `has positive effect on` / `장점` / `요구` / `필요`.
- 적합 조건 4개가 문장 노드 하나로 뭉쳤다.
- 장점은 3개 중 2개, 단점은 3개 중 1개만 추출됐다.
- 결정 규칙의 조건과 결론의 연결이 사라졌다 ("팀 규모 | 점수 | -3점").
- 값이 `중간`/`높다`처럼 한국어로 나왔다. 방향이 뒤집힌 관계도 있다 ("프론트엔드 빌드 인프라 | 필요 | Micro-Frontend").

## 3. 목표 설계
**원칙**: 새 메커니즘을 만들지 않는다. `schema_alignment`(동치 감지·제안·규칙·패널)를 승격의 재구성 수단으로 재사용한다.

### (a) 스키마 유도 — `schema_alignment/induction.py`
1. **프로파일**: `urn:doc:*` 그래프만 대상으로 하고, `meta/`, `inverse_`, reification은 제외한다.
2. **클래스 유도**: LLM이 레코드 클래스를 정한다. 속성명은 새로 짓지 않고 **기존 predicate 중에서 대표를 고른다**.
3. **동치 감지**: 임시 타입으로 kind를 고정한 뒤 동치 감지기를 실행해 속성 묶음과 값 어휘를 얻는다.
   - **순서**: 클래스 확정이 동치 감지보다 먼저 와야 한다. 텍스트 그래프는 문서마다 predicate가 달라 시그니처 군집이 깨지기 때문이다.
4. **산출**: 결과를 `SchemaMappingProposal`(`origin=promotion:<run_id>`)로 만든다. `class`(엔티티→클래스)와 `entity`(병합) 종류를 추가한다.
   - TBox 초안은 **데이터와 같은 `rag.local` URI**를 쓴다. 예: `rel:pros … skos:altLabel "장점","이점"`.

### (b) 소유자 검토
스키마 정렬 패널에 "승격 초안" 탭을 추가한다. 일괄 수락 API는 `POST /schema/promotion/{run_id}/apply`다.

### (c) ABox 재구성
**L1 트리플 리플레이** (기본, LLM 비용 0)
- 저장된 `{doc_id}_triples.json`의 불변 사본(`_triples.raw.json`)에 현재 규칙을 결정적으로 적용한다.
- 적용 순서: 엔티티 병합 → key → value → 타입.
- 적용 결과로 `urn:doc:{doc_id}` 그래프만 교체한다.
- 청크(Milvus)와 `source_node_id`는 보존되므로 근거도 유지된다.
- 멱등이다. revert는 규칙 없이 재생하면 된다.
- raw가 없는 기존 문서는 Fuseki reification에서 복원한다.

**L2 스키마 유도 재추출** (opt-in, LLM 비용 발생)
- 저장된 청크를 TBox를 넣은 프롬프트로 다시 추출한다. n항 구조(`quality_attributes`, `decision_rules`)는 이 단계에서만 복원된다.

**기각한 방안**: SPARQL UPDATE 재작성(stmt 해시·근거 불일치)과 전체 재인제스트(LLM 비결정성·비용·원본 삭제).

### (d) 검색
- **유형 질문**: 타입이 문서 그래프에 있으므로 클래스가 kind가 된다. 다중 타입은 결정적으로 선택한다.
- **관계 타게팅**: `altLabel`을 별칭 풀에 추가한다.
- **C 경로**: `urn:ontology`를 실시간으로 로드한다.

### (e) 이후 텍스트 문서
1. 추출 프롬프트에 TBox 요약(클래스·속성·별칭·enum)을 주입한다.
2. 추출 후 전체 규칙을 적용한다.
3. 미지 predicate는 제안으로 올라간다. 비율이 임계를 넘으면 `schema_status=stale`로 표시한다.

### 선언 경로 통합
- `schema_source`(none | declared | induced), `schema_status`(draft | active | stale), `schema_version`을 둔다.
- `is_promoted`는 호환용 파생값으로 남긴다.
- 네임스페이스는 `rag.local`로 통일한다.

## 4. 실험
- **데이터**: `test-ontology2` (`f220990a-…`, 설정은 `test-ontology`와 동일).
  - 기본 인제스트 설정으로 적재한다. 실사용 기준선이다.
  - 신규 Milvus 컬렉션이 정상 동작함을 확인했다 (2026-11-15).
- **지표**

| 지표 | 내용 |
|---|---|
| M1 | 사실 재현율 (YAML 체크리스트 대비) |
| M2 | 스키마 커버리지 (YAML 경로별 유도 속성 존재, 보유 멤버 수, 값 어휘) |
| M3 | 파편화 (서로 다른 predicate 수, kind 수) |
| M4 | 질문 매트릭스 (두 검색 설계 문서의 질문을 두 KB에 실행해 답 엔티티 F1과 경로 비교) |
| M5 | 근거 무결성 (재구성 전후 청크 수, stmt `sourceNodeId` 실재) |

- **합격선 (조정 가능)**

| 계층 | 대상 | 기준 |
|---|---|---|
| 1계층 | 스칼라 enum, 스타일 간 관계, pros/cons | 커버리지 ≥90%, 재현율 ≥80% |
| 2계층 | fit/avoid 신호 | ≥60% |
| 3계층 | n항 구조 | L2 이후 측정 |

## 5. 구현 순서
| 단계 | 내용 |
|---|---|
| S0 | 결함 수정 (내보내기는 urn:doc만, 프로파일에서 meta·inverse 제외, relations 키, 죽은 코드 제거) — 독립 PR |
| S1 | 트리플 리플레이 (ingest `/replay`, raw 사본, 규칙 적용 확장, 텍스트 재정규화 분기) |
| S2 | 스키마 유도 (`induction.py`, 제안 종류 추가, `/promote`를 유도 실행 → 초안 반환으로 교체) |
| S3 | 상태·TBox 통일 (`schema_source`/`status`, 네임스페이스) |
| S4 | 검색 연동 (다중 타입, TBox 실시간 로드, altLabel) |
| S5 | 정합 인제스트 + L2 재추출 |

S1과 S2가 끝나면 1차 실험을 할 수 있다. 그 전에 **현행 승격을 그대로 실행한 기준선**(Before)을 측정해 둔다.
