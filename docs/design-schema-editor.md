# 설계: 스키마 편집기 (사람 검수 1단계)

작성일: 2026-11-16 · 상태: 1차 구현 완료
관련: `design-graph-promotion.md`(유도 승격·리플레이·재추출), `design-schema-mismatch.md`(매핑 제안·규칙)

## 1. 왜 필요한가

승격(스키마 유도)은 LLM 이 그래프를 보고 클래스·속성 초안을 만들고, 사람은 그 **제안을 받거나 거절**만 할 수 있었다.
물리학사 평가에서 남은 오답의 절반은 그래프 문제(관계 방향이 뒤집힘, 사실 누락)였고, 이는 속성의 정의·방향이
정확해야 줄어든다. 상용 시스템(Palantir 온톨로지, Neo4j/Stardog 등)도 스키마는 사람이 다듬는 것을 전제로 한다.
그래서 사람이 스키마를 **직접** 고치는 화면이 필요하다.

검수 기능 로드맵 (이 문서는 1단계):
1. **스키마 편집기** — 클래스·속성의 이름·정의·방향·별칭 편집, 버전 이력 ← 이번
2. 트리플 검토 대기열 — 방향 의심·근거 약함·스키마 밖 트리플을 사람이 맞음/틀림/수정. 사람이 고친 내용은 별도 그래프에 두어 재추출에도 살아남게
3. 엔티티 정리 — 같은 대상의 다른 이름 병합, 잘못된 병합 분리
4. 틀린 답변에서 바로 고치기 — Execution Log 에서 빠진 사실을 그 자리에서 트리플로 추가

## 2. 대상과 저장 위치

- 대상: 온톨로지로 승격된 KB 전부.
  - 텍스트 KB (`schema_source` = `induced` / `declared`): 아래 §2~§5
  - 구조화(YAML/JSON) KB (`structured`): 저장 방식이 달라 §7
- 스키마 본체: `kb.promotion_metadata.induction`
  - `classes`: `[{name, description}]`
  - `properties`: `[{name, description, domain, range, members(별칭, 대표 이름 포함), seed?}]`
- 클래스 멤버: `class` 규칙(엔티티 → 클래스)
- 이 스키마를 쓰는 곳: TBox(`urn:ontology:{kb}`), 스키마 기준 재추출 프롬프트(`build_schema_spec`), 검색의 클래스 카탈로그·스키마 정보(`schema_info`)

새로 추가한 메타:
- `schema_version` (1부터), `schema_updated_at`, `schema_last_summary`
- `schema_history`: 바꾸기 전 스키마 사본 `[{version, at, summary, spec}]`, 최근 20개

## 3. 저장할 때 일어나는 일

`PUT /knowledge-bases/{kb}/schema/spec` (`services/schema_alignment/schema_editor.py`)

1. **정규화**: 속성 이름 공백 → `_`, 클래스 이름 PascalCase 문자만, 별칭 목록 정리(대표 이름 맨 앞)
2. **검증** — 오류면 저장 안 함
   - 이름 없음·중복, domain 이 클래스 목록에 없음, 같은 별칭이 두 속성에 있음
   - 경고(저장은 됨): 정의 없음(재추출 정확도 저하), range 가 클래스가 아님(값으로 취급)
3. **버전 확인**: `base_version` 이 현재 버전과 다르면 409 — 두 사람이 동시에 고쳐 덮어쓰는 것을 막는다
4. **변경 요약**: 추가·삭제·이름 변경·수정. 이름 변경은 화면이 보낸 `renamed_from` 으로만 인정한다
   (같은 이름의 삭제+추가와 구별해야 기존 데이터를 옮길 수 있으므로)
5. 이전 스키마를 이력에 넣고 새 스키마 저장, TBox 재생성, 클래스 카탈로그 캐시 무효화
6. **이름 변경을 데이터에 반영** (LLM 비용 0)
   - 속성: key 규칙 `옛 이름 → 새 이름` 추가. 기존 별칭 규칙(`x → 옛 이름`)은 새 이름을 가리키게 바꾼다
     (리플레이의 key 매핑은 한 번만 적용돼 `x → 옛 → 새` 연쇄가 안 되기 때문)
   - 클래스: class 규칙의 대상 이름을 바꾼다. 삭제한 클래스의 멤버 규칙은 끈다
   - 그다음 텍스트 문서를 **리플레이**: 저장된 추출 트리플(raw)에 규칙을 다시 적용해 그래프만 교체
7. 정의·방향·별칭·새 속성은 **재추출을 해야** 데이터에 반영된다 → 응답의 `reextract_recommended` 로 알리고,
   화면의 "스키마 기준 재추출" 버튼으로 기존 재추출 창을 연다 (비용 견적·진행·되돌리기 포함)

되돌리기(`POST …/schema/spec/revert {version}`)는 이력의 사본을 **새 버전으로 저장**한다 (이력이 지워지지 않음).
그 사이 이름을 바꾼 속성은 `renamed_from` 을 자동으로 붙여 규칙과 그래프도 함께 되돌린다.

API:

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/{kb}/schema/spec` | 스키마 + 속성별 트리플 수 + 스키마 밖 관계 + 이력 |
| POST | `/{kb}/schema/spec/validate` | 저장 전 미리보기 (오류·경고·변경 요약) |
| PUT | `/{kb}/schema/spec` | 저장 (`base_version`, `replay` 기본 true) |
| POST | `/{kb}/schema/spec/revert` | 이력 버전으로 되돌리기 |

## 4. 화면

KB 상세의 **Schema** 탭 (온톨로지로 승격된 KB 에만 보임, `components/SchemaEditor.tsx`)
- 클래스 표: 이름·설명·멤버 수, 추가/삭제
- 속성 표: 이름, 방향(domain 선택 → range 클래스 또는 값), 정의(재추출 프롬프트에 그대로 들어감), 별칭, 트리플 수, 검색
- 이름을 바꾸면 "이전: …" 표시 → 저장 시 `renamed_from` 으로 전송
- 편집할 때마다 서버 검증 결과(변경 요약·오류·경고)를 위에 표시, 오류가 있으면 저장 버튼 비활성
- **스키마 밖 관계**: 그래프에는 있지만 스키마에 없는 술어(트리플 수 순) — 눌러서 속성으로 추가
- **이력**: 버전·시각·요약, 되돌리기

## 5. 검증 (2026-11-16, test-ontology3 물리학사)

| 단계 | 결과 |
|---|---|
| 조회 | 클래스 8, 속성 21, 속성별 트리플 수, 스키마 밖 관계(설명 10, 시간 4 …) |
| 미리보기 | `속성 이름 저술함→저술했음`, 정의 없는 속성 3개 경고 |
| 옛 버전 기준 저장 | 409 거부 |
| 저장 | 버전 2, 규칙 4건 변경, 문서 29건 리플레이, 트리플 55건이 `저술했음` 으로 이동 |
| 되돌리기 | 버전 3, 트리플 55건 `저술함` 으로 복귀, 이력 [2, 1] |
| 이후 검색 | Q01·Q33·Q35 정답 유지 |
| 구조화 KB(test-ontology) | 편집 불가 안내 |

단위 테스트: `backend/tests/test_schema_editor.py` (정규화·검증·변경 요약 5건)

## 7. 구조화(YAML/JSON) KB 편집

구조화 KB 의 스키마는 YAML 필드 구조에서 업로드할 때마다 다시 만들어진다 (`mark_structured_ontology`).
스키마 그래프를 직접 고치면 다음 업로드 때 사라지므로, 편집 내용을 **따로 저장해 두고 만들 때마다 덧씌운다**.

| 편집 | 저장 | 반영되는 곳 | 재업로드·새 문서 |
|---|---|---|---|
| 유형 이름·설명 (K1 → ArchitectureStyle) | `promotion_metadata.schema_overlay.classes` | 클래스 카탈로그(검색 계획·에이전틱 KB 요약), TBox 클래스 | 유지 |
| 속성 정의·별칭 | `schema_overlay.properties[경로]` | 계획 프롬프트의 경로 설명, TBox `rdfs:comment`·`skos:altLabel` | 유지 |
| 속성 이름(경로) 변경 | key 매핑 규칙 `옛 경로 → 새 경로` (origin=schema_editor) + 해당 문서 재정규화 | 데이터(그래프·청크) | 유지 (업로드 때 규칙 적용) |
| 속성 추가·삭제, 방향 변경, 유형 추가 | 불가 — 오류로 안내 | YAML 원본에서 | - |

- 유형 이름 K1, K2 … 는 멤버 수 순서로 매번 다시 매겨진다. 그래서 덧씌우기는 저장 당시 **멤버 목록**을 함께 두고,
  멤버가 절반 이상 겹치는(Jaccard ≥ 0.5) 유형에 붙인다 (`class_query.match_overlay_class`). 클래스가 있는 유형은 원래 이름으로.
- 되돌리기: 덧씌우기를 이력 버전으로 바꾸고, 그 버전 이후 편집기가 만든 경로 이름 변경 규칙은 끈 뒤 전체 문서 재정규화.

검증 (2026-11-16, test-ontology):

| 단계 | 결과 |
|---|---|
| 조회 | 유형 1(K1, 멤버 10), 속성 경로 95 (유형·값·레코드 수) |
| 저장 v2 | K1 → ArchitectureStyle + 설명, `fit_signals.modifiability` 정의·별칭(수정용이성·변경용이성) |
| 저장 v3 | `tradeoffs.cons` → `tradeoffs.weaknesses`: 규칙 1건, 문서 10건 재정규화, 그래프 술어 31건 이동 |
| 속성 추가 시도 | 거부 ("YAML 원본에 필드를 추가하세요") |
| serverless.yaml 삭제 후 재업로드 | 유형 이름·정의 유지, 새 문서에도 `weaknesses` 적용 |
| v2 로 되돌리기 (v4) | 경로 이름만 `cons` 로 복귀, 유형 이름·정의는 유지 |
| 검색 | 에이전틱 계획이 별칭을 사용 ("modifiability(수정용이성/서비스 빠른 추가)") |

알려진 문제: 재정규화 중 문서 1건의 벡터 청크가 옛 내용으로 남았다 (그래프는 정상). 같은 청크 id 로 지웠다 바로
다시 넣을 때 Milvus(v2.3)에서 생기는 것으로 보이며, 그 문서만 다시 재정규화하니 정상이 됐다. 재정규화 후 청크 검증이 필요하다.

## 8. 스키마 그래프 보기

**편집기 안 그래프 (표 / 그래프 전환)** — `components/SchemaGraph.tsx`
- 지금 편집 중인 상태로 그린다 (저장 전 변경도 바로 보임) — 스키마 구조를 이해하면서 고치기 위함
- 텍스트 KB: 클래스 = 노드, range 가 클래스인 속성 = 이름이 붙은 화살표, 그 밖의 속성 = domain 클래스의 값 속성(개수 표시),
  domain 이 없는 속성은 'domain 미지정' 노드에 모음
- 구조화 KB: 유형 → 중첩 필드(경로 세그먼트) 트리, 마지막 세그먼트는 값 속성
- '값 속성도 노드로' 를 켜면 값 속성까지 작은 노드로
- 노드를 누르면 옆 패널에 설명·나가는/들어오는 관계·값 속성(정의·별칭·값 예시), 링크를 누르면 속성 정의

**뷰어에서 열기** → 기존 그래프 뷰어의 스키마 모드(`/graph-viewer?mode=schema`)를 새 탭으로. 저장된 TBox 기준이며,
클래스를 누르면 실제 인스턴스가 펼쳐진다.

고친 것:
- `GET /graph/schema`: 질의 하나에 OPTIONAL 이 겹쳐 행이 불어나 `LIMIT 100` 에 잘렸다
  (test-ontology3 클래스 8 중 6, test-ontology 12 중 2). 클래스·속성·subClassOf 질의로 나눴다.
  range 가 클래스인 속성은 클래스 간 링크, 아니면 domain 클래스의 `attributes`(정의·별칭 포함)로 → 노드 툴팁에 표시.
- 구조화 KB TBox: 중첩 구조의 domain·range 가 없어 링크가 그려지지 않았다. 데이터의 rdf:type 으로 채운다
  (`fit_signals`: ArchitectureStyle → Fit_signals, `modifiability`: Fit_signals 의 값 속성).
- `GET /graph/schema/instances`: 인스턴스를 온톨로지 그래프에서만 찾아 비어 있었다 (데이터는 문서 그래프에 있음).
  문서 그래프의 rdf:type 으로 찾고, 타입이 없는 레코드(구조화 KB 최상위)는 클래스 카탈로그의 유형 멤버로.

결과: test-ontology3 클래스 8·관계 10, test-ontology 유형 12·관계 11. Person 클릭 시 인스턴스가 펼쳐지는데,
'암', '빛' 같은 잘못 분류된 엔티티가 보인다 — 2단계(트리플·엔티티 검토)에서 다룰 대상.

## 9. 스키마가 데이터 구조와 어긋나던 문제 (2026-11-16)

**텍스트 KB — range 누락** (test-ontology2): 시드 없이 유도한 스키마는 속성 36개 모두 range 가 비어 있어 클래스 간 관계가
하나도 그려지지 않았다. 데이터에는 관계가 있다 — 속성 목적어가 어느 클래스 멤버인지(class 규칙) 세면:

| 속성 | 목적어 클래스 | 비율 |
|---|---|---|
| 관련_패턴 | ArchitectureStyle | 26/27 |
| is_derived_from | ArchitectureStyle | 5/5 |
| is_centered_around | SoftwareComponent | 6/10 |
| has_positive_effect_on | QualityAttribute | 22/35 |

- `schema_editor.infer_ranges`: 목적어의 60% 이상(최소 3건)이 한 클래스면 range 로 추천. 나머지(장점 문장·값)는 값 속성이 맞다.
- 승격 적용(`apply_induction`) 때 빈 range 를 자동으로 채운다 (`range_inferred` 로 근거 기록).
- 편집기: 빈 range 옆에 "추천: → 클래스 (비율)" 버튼, "range 추천 모두 적용". test-ontology2 에 4건 적용(v2) → 관계 4개 표시.
- test-ontology2 속성 36개는 정의도 모두 비어 있다 — 재추출 정확도를 위해 채울 대상.

**구조화 KB — 중첩 블록을 클래스로 올림** (test-ontology): 진짜 유형은 ArchitectureStyle 하나인데 YAML 중첩 블록
(fit_signals, tradeoffs, decision_rules …)에 붙은 rdf:type 을 TBox 가 클래스 11개로 올렸다. 이 노드들은 레코드마다
하나씩 붙은 속성 묶음이지 독립 대상이 아니다. 반대로 다른 스타일을 가리키는 경로(related_patterns,
combines_well_with.style, conflicts_with.style)는 레코드 노드에 rdf:type 이 없어 관계로 잡히지 않았다.

- `class_query.attach_ref_kinds`: 경로 값의 60% 이상이 한 유형의 멤버면 `ref_kind` (다른 레코드 참조)
- TBox: 중첩 블록 클래스에 `rag:structural true`, 참조 경로의 range = 유형
- 스키마 그래프(API·편집기): 유형 노드 하나 + 중첩 블록은 값 속성 묶음(fit_signals 26, decision_rules 24 …),
  참조 경로 3개는 ArchitectureStyle → ArchitectureStyle 관계. 편집기의 "중첩 블록 펼치기" 로 예전 트리도 볼 수 있다.

데이터(트리플·청크)는 바꾸지 않았다 — 데이터는 이미 올바른 엔티티를 가리키고 있었고, 스키마 설명만 빠져 있었다.

## 10. 스키마 추출 지침 반영 (2026-11-16, 검토: Fable · 구현: Opus)

지침은 `.claude/skills/ontology-schema-extraction/SKILL.md` (사람 절차 + 규칙 요약). 검토에서 지침보다 먼저 고칠 코드 결함이 나왔다.

**결함 (코드 확인 → 수정)**
| 결함 | 영향 | 수정 |
|---|---|---|
| `validate_induction` 이 range·정의를 시드에서만 채움, 프롬프트도 요구 안 함 | 시드 없는 KB 의 range·정의 전부 빈칸 | 프롬프트가 range(클래스명 또는 빈칸)·정의('A \| 관계 \| B')를 요구, 비시드는 LLM 값 채택(채택된 클래스명만) |
| 프롬프트가 "members 는 주어 엔티티만" | 목적어로만 나오는 품질 속성 등이 클래스에 못 들어감 | 관계별 목적어 집계(서로 다른 수·상위 8·서술 비율)와 '목적어로만 나오는 엔티티' 블록 추가, 멤버는 주어·목적어 모두 |
| range 추정이 리플레이 전에 실행 | 별칭→대표 반영 전 그래프를 세어 0건 | `apply_induction` 에서 리플레이 뒤 `range_check` |
| `_compact` 가 1글자 이름을 '' 로 | class 규칙 '줄 → Person' 이 '암'·'빛' 등 1글자 엔티티 전부에 적용 | 토큰이 없으면 구분자만 지운 원문 (backend·ingest 둘 다) |
| 재유도 적용 시 같은 대상의 옛 규칙이 남음 | 규칙 중복 → 적용 순서에 따라 결과가 달라짐 | 적용 전에 같은 source 의 이전 제안 규칙을 끔 (편집기 규칙은 유지) |
| 재유도가 편집한 스키마를 덮음 | 사람 편집 유실 | 재유도 전 스키마를 편집기 이력에 보관 |

**range 데이터 검증** (`schema_editor.range_check`)
- 목적어: 대표 + 별칭 술어 합산, 서술·수치·30자 초과 제외, **서로 다른 목적어** 기준, 5개 미만은 판정 안 함
- 판정: 데이터 최다 클래스 ≥ 60% → 데이터 채택(선언과 다르면 LLM 선언은 교체, 시드·사람 선언은 충돌 표시) /
  선언 일치율 < 30% → LLM 선언은 비움, 시드·사람 선언은 경고 / 그 사이 → 유지 + 멤버 누락 제안
- **부호·강도 계열**(`family_key`: has_moderate_negative_effect_on → has_effect_on)은 목적어를 합쳐 같은 range

**부호·강도 계열을 묶지 않는다** — 프롬프트에 "묶지 마라"를 넣어도 GLM 이 moderate/strong 을 positive/negative 에 묶었다
(key 규칙은 이름만 바꾸므로 강도가 사라짐). `validate_induction` 에서 결정적으로 분리하고, 분리된 관계는 대표와 같은 domain·range 로 둔다.

**편집기 데이터 검증 카드** — 관계별 일치율 표시, 클래스별 멤버 누락 후보(체크 → class 규칙 + 리플레이),
range 위반 목록, 클래스 범위 표기 중복 찾기(LLM 제안 → 체크 → entity 규칙 + 리플레이). 자동 수락 없음.
API: `POST schema/spec/members`, `GET schema/spec/merge-candidates`, `POST schema/spec/merge`, `POST schema/induce/dry-run`.

**적용 결과**
| KB | 전 | 후 |
|---|---|---|
| test-ontology2 (재유도 + 검증) | 클래스 9, range 4/36, 정의 0/36, 그래프 관계 4 | 클래스 6, range 25/38, 정의 38/38, 그래프 관계 25. 검증 가능한 관계 10개 모두 일치율 ≥ 60%. 효과 관계 5개 모두 → QualityAttribute (계열 합산 77%) |
| test-ontology (YAML) | 유형 1, 참조 관계 3 | 변화 없음 (유도 경로 아님) |
| test-ontology3 (평가용) | 재유도 안 함 — 미리보기만: 시드 속성 이름·range 변화 0, domain 3개(시드에 domain 없는 반박함·기반함·시대)만 차이, 정의 18 → 27 | 1글자 키 수정 + 리플레이만 적용: 1글자 Person 이 '줄'·'빛'·'암' → '줄' 만. 물리학사 29 / 32 (2회, 이전 28~29), 사실 재현율 146/197 → 146/197 |

test-ontology2 사람 확인 내역: 멤버 지정 12건(팀 자율성·consistency·참고문헌 5·요구 3·개념 2, 문장 조각·'중간' 등급 값 제외),
표기 병합 3건 수락(운영 복잡도←operational complexity, 일관성←consistency, 확장성←scalability), 2건 거절
(디버깅 용이성←debugging complexity, 운영 단순성←운영 복잡도 — **반대 개념**을 LLM 이 같은 것으로 묶음).
LLM 병합 제안을 사람이 확인해야 하는 이유다.

## 11. 속성별 트리플 목록 + 병합 충돌 수정 (2026-11-16)

- `GET schema/spec/triples?property=` — 속성(텍스트: 대표+별칭 술어, 구조화: 필드 경로)의 트리플, 상태(ok/gap/violation/value/-),
  주어 클래스의 domain 불일치, 근거 청크(rdf:Statement 의 sourceNodeId)·문서. 편집기 속성 표의 트리플 수를 누르면 열린다
  (`PropertyTriplesModal`), 멤버 누락은 그 자리에서 지정.
- 이 목록으로 찾은 버그: 표기 병합 `operational complexity → 운영 복잡도` 가 적용되지 않았다. 예전 유도의 **값 규칙**
  `운영 복잡도 → operational complexity` 가 남아 있어, 적용 순서(entity → value)상 병합 결과를 다시 영어로 바꿨다.
  `merge_entities` 가 대표 이름을 다른 이름으로 바꾸는 기존 entity·value 규칙을 끄도록 수정 (`conflicts_disabled`).

## 6. 남은 것

- 재추출 후 결과 비교(전/후 트리플 차이)를 편집기 안에서 보여 주기
- 속성 병합(두 속성을 하나로) 전용 동작 — 지금은 한쪽 삭제 + 별칭 추가 + 재추출로 가능
- 2단계(트리플 검토 대기열)와 사람 수정분 보존 그래프
