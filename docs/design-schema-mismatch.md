# 스키마 불일치 문서 처리 — 검색 시 동치 확장 + 인제스트 시 매핑 규칙

- 작성일: 2026-11-14
- 선행: `docs/design-graph-relation-targeting.md`, `docs/design-graph-class-query.md`, `docs/design-structured-json-yaml-ontology.md` §6

## 1. 문제
일반 업로드는 스키마를 검증하거나 정렬하지 않는다. 키는 그대로 predicate가 된다. 그래서 다음 불일치가 생기면 결과가 **조용히 누락**된다.

| 불일치 | 예 | 영향 |
|---|---|---|
| 같은 의미, 다른 키 | A 문서 `pros`, B 문서 `advantages` | 유형 질문의 필터·집계가 한쪽 경로만 본다 |
| 같은 의미, 다른 값 | `high` vs `높음`, `small` vs `소규모` | eq 필터에서 누락된다 |
| 같은 키, 다른 중첩 | `tradeoffs.pros` vs 평면 `pros` | 다른 경로로 갈린다 |
| 표기만 다름 | `testingComplexity` vs `testing_complexity` | 다른 경로로 갈린다 |

## 2. 구조
두 단계가 **하나의 동치 감지기**를 공유한다.
- **Part 1 (검색 시)**: 감지 결과를 질의 계획의 OR(경로)·IN(값)으로 쓰고, 미확정 유사 항목은 리포트에 경고한다.
- **Part 2 (인제스트 시)**: 감지 결과를 제안으로 만든다. 수락하면 KB 매핑 규칙으로 저장하고, 그 규칙으로 재인제스트해 데이터를 정규화한다.

## 3. 동치 감지기 (`backend/app/services/schema_alignment/equivalence.py`)

### 이름 유사 근거 (임베딩 미사용)
| 근거 | 조건 | 예 |
|---|---|---|
| normalized | 같은 깊이, 세그먼트마다 `_compact` 일치 또는 어간 일치 | `testingComplexity` ≈ `testing_complexity` |
| nesting | 리프가 normalized 일치하고 접두가 다름 | `pros` ≈ `tradeoffs.pros` |
| lexicon | 내장 키 동의어표의 같은 묶음 | pros/advantages/장점 |
| llm | 카탈로그당 1회 LLM 동치 패스 (캐시) | 동의어표 밖의 동의어·한↔영 키 |

### 구조 게이트 (모든 근거에 공통)
- **G1 값 종류 호환**: number는 number와만 묶는다.
- **G2 멤버 상보성**: 공통 멤버 / 작은 쪽 멤버 ≤ 0.2여야 한다. 한 레코드가 두 경로를 모두 가지면 서로 다른 속성이다.
- **G3 접두 공존 금지**: 최상위 세그먼트가 다른 두 접두가 같은 멤버에 공존하면 묶지 않는다.
  - 예: `avoid_signals.team_size`와 `fit_signals.team_size`.

### 값 동치
동치 경로 묶음의 합친 enum 어휘 안에서만 판정한다. 근거는 다음 넷 중 하나다.
- `_compact` 일치
- 값 동의어표 (높음↔high)
- LLM 패스의 `value_groups`
- KB 값 규칙

### 등급
| 등급 | 검색 시 | Part 2 |
|---|---|---|
| 확정 (규칙·normalized·nesting·lexicon) | 자동 OR | 제안 생성. normalized 완전일치는 인제스트 시 자동 적용 |
| LLM 판정 | **자동 OR + 리포트에 "(LLM 판정)" 표기** — 소유자 결정 | 제안 생성 |
| 유사·미사용 (게이트 탈락) | 경고만 | 제안 없음 |
| 구별 유지 (`ignore` 규칙) | 미사용, 경고 없음 | 다시 제안하지 않음 |

설정 `SCHEMA_EQUIV_LLM_AUTO_USE=false`로 두면 LLM 판정은 경고로만 쓴다.

## 4. Part 1 — 질의 계획 확장
- **경로 묶음**: 계획 `path`에 정수 또는 정수 배열(최대 4)을 쓸 수 있다.
  - 주 경로는 **코드의 자동 확장**이다. LLM이 번호 하나만 골라도 검증 단계가 동치 묶음 전체로 펼친다.
  - 배열은 감지기가 놓친 경우를 위한 보조 수단이다.
- **프롬프트**: 묶음의 대표 줄에 동치 경로와 합친 값 어휘를 싣는다. 비대표 줄에는 "N번과 동치"라고 표시한다.
- **컴파일**:
  - 필터·집계 경로 대안을 `UNION`으로 묶는다. `ne`/`not_exists`는 `NOT EXISTS { {alt1} UNION {alt2} }`로 만든다.
  - 경로 대안이 1개면 기존과 같은 SPARQL이 나온다 (회귀 보장).
  - 근거 분기는 대안마다 만들고 `?path`에 **실제 키**를 바인딩한다. 같은 항목 한정은 대안별 접두로 적용한다.
- **앵커 질문(A)**: 선택된 경로에 동치 경로를 덧붙인다. 규칙 별칭(원래 키 → 표준 키)도 별칭 풀에 넣는다.
- **리포트**: `동치 경로`, `동치 값`, `⚠ 유사하지만 사용하지 않은 경로/값` 줄을 추가한다. 경고가 있으면 답변 컨텍스트에 "결과에서 빠졌을 수 있음" 주의 문구를 한 줄 붙인다.
- **캐시**:
  - 카탈로그 지문을 `트리플 수 + 서로 다른 predicate 수`로 바꾼다.
  - 인제스트 완료 콜백에서 카탈로그를 무효화한다.

## 5. Part 2 — KB 매핑 규칙

### 저장 (backend Mongo)
- **`SchemaMappingRule`**: `kb_id`, `rule_type`(key|value|ignore), `source_path`→`target_path`, `source_value`→`target_value`, `scope_paths`(기본 `*` — **KB 전체**, 소유자 결정), `origin`(user|auto|proposal), `status`.
- **`SchemaMappingProposal`**: `kind`, `source`, `target`, `basis`, `evidence`, `doc_ids`, `status`(pending|accepted|rejected).
- **기존 모델 필드 추가**: `KnowledgeBase.schema_rules_version`. `Document`에는 `schema_rules_version`, `schema_warnings`, `source_retained`를 추가한다.

### 인제스트 적용 (`ingest_service/app/core/schema_normalizer.py`)
- **적용 위치**: 구조화 문서는 파싱 직후 **트리**에 규칙을 적용한다. 그래야 identity·구조 노드·청크 텍스트·트리플이 모두 표준 키·값으로 일관되게 나온다.
- **적용 순서**: key 규칙(긴 경로부터) → 자동 표기 정규화 → value 규칙(값 전체 일치만) → 자동 값 표기 정규화.
- **자동 표기 정규화**: KB 어휘와 `_compact` 완전일치이면서 표기만 다른 경우에 적용한다 (예: `testingComplexity`→`testing_complexity`, `High`→`high`).
  - id/label 키는 제외한다.
  - 적용 결과는 `origin=auto` 규칙으로 기록한다.
- **충돌 병합**: 대상 키가 이미 있으면 리스트는 이어 붙이고, 스칼라는 리스트로 만들고, dict는 재귀 병합한다.
- **텍스트(LLM 추출) 문서**: 단일 세그먼트 key 규칙만 트리플 predicate에 적용한다.
- **업로드 처리**: 업로드는 막지 않는다. 처음 보는 유사 키는 그대로 적재하고, 제안과 문서 경고를 남긴다. 그동안 검색은 Part 1의 OR 확장이 보완한다.

### 제안 생성
인제스트 완료 콜백에서 백그라운드로 실행한다.
1. 카탈로그를 무효화하고 다시 만든다.
2. 감지기를 실행한다.
3. 규칙이나 ignore에 없는 확정·LLM 등급 묶음을 제안으로 upsert한다.
4. 해당 문서의 `schema_warnings`를 갱신한다.

비교 기준이 KB의 데이터 기반 카탈로그라서, KB가 승격됐는지와 무관하게 동작한다.

### 검토 API (`/api/v2/knowledge-bases/{kb_id}/schema/...`)
- `GET proposals`
- `POST proposals/{id}/accept` (기본으로 재정규화를 **자동 실행** — 소유자 결정), `POST proposals/{id}/reject` (ignore 규칙 생성)
- `GET/POST rules`, `PATCH/DELETE rules/{id}`
- `POST detect`
- `POST renormalize`
- `POST documents/{doc_id}/reingest` (원본이 없는 기존 문서용)

### 재정규화 = 재인제스트 (SPARQL UPDATE 기각)
**SPARQL UPDATE를 기각한 이유**: Milvus 청크 본문과 임베딩, reification statement URI(`sha256(s|p|o)`), 중첩 이동에 필요한 새 구조 노드·청크를 일관되게 고칠 수 없다. 반면 구조화 추출은 LLM 없이 결정적이라 재인제스트가 싸다.

**방식**
- 같은 `doc_id`로 `replace_existing=True` 재인제스트를 한다.
- 추출이 성공한 **뒤에** 기존 데이터를 삭제하고 삽입한다.
- 동시 실행은 2개로 제한한다.

**원본 보존**: **구조화 원본(YAML/JSON)만 보존**한다 (소유자 결정). 문서를 삭제할 때 함께 지운다.

## 6. 소유자 결정 (2026-11-14 확정)
1. LLM 판정 동치는 검색에 자동으로 쓰고, 리포트에 표기한다.
2. 제안을 수락하면 재정규화를 자동으로 실행한다.
3. 구조화 원본만 보존한다.
4. 값 규칙의 기본 범위는 KB 전체다.

## 7. 검증 시나리오
**변형 문서 `space-based.yaml`** (스키마 v2 기반, 다음만 다르게 만든다)
- `tradeoffs.advantages`(4건) / `disadvantages`(2건)
- `testingComplexity: 높음`
- `operational_complexity: 높음`
- `avoid_signals.team_size: 소규모`

| 질문 | 현재 | Part 1 | Part 2 이후 |
|---|---|---|---|
| 테스트 복잡도 high | space_based 누락 | 포함 (동치 경로 + 동치 값) | 포함, 동치 줄 없음 |
| 팀 규모 small 회피 | 6개 | 7개 | 7개 |
| pros 최다 | 3건 동률 10개 (오답) | space_based=4 단독 | space_based=4 (`tradeoffs.pros`) |

**회귀**: 원래 10개 문서 상태에서 유형 질문 매트릭스와 앵커 질문 매트릭스의 결과가 같아야 한다. 동치·경고 줄은 0건이어야 한다.

## 8. 구현 중 확정·발견 사항 (2026-11-14)

### 감지기 강화
- **어간 일치 기준**: 공통 접두가 4자 이상이면서 짧은 쪽 길이의 60% 이상이어야 한다.
  - 처음에는 `testability`와 `testingComplexity`가 공통 접두 "test" 때문에 묶이는 오탐이 있었다.
- **중첩 차이 판정**: 리프가 표기 일치이거나 동의어표에 있을 때만 인정한다. 어간이 비슷한 것만으로는 묶지 않는다.
- **묶음 병합 조건**: 합치려는 두 묶음의 **모든 교차 쌍**이 게이트를 통과해야 한다. A≈B, B≈C라는 이유로 A와 C까지 연쇄로 묶이는 것을 막는다.
- **숫자 값**: 정규화로 부호가 사라지지 않도록 수치 그대로 비교한다. 처음에는 -3과 3이 같은 값으로 묶였다.

### 재정규화 순서
- 기존 데이터는 **추출이 성공한 직후, 엔티티 해석 전**에 삭제한다.
- 해석 이후에 삭제하면, 해석이 같은 문서의 이전 데이터와 매칭해 identity가 바뀌었다(`space_based` → `Space_Based_Architecture`).

### 기타
- **라우터 등록 위치**: 백엔드가 실제로 실행하는 진입점은 `backend/main.py`다. `app/main.py`는 쓰이지 않으므로, 라우터는 `backend/main.py`에 등록한다.

### 검증 결과 (test-ontology, gpt-5)
| 단계 | 결과 |
|---|---|
| Part 1 | 변형 문서 `space-based`가 동치 경로·값으로 누락 없이 포함됐다. pros 최다 질문도 space_based(4)로 정답이 나왔다. |
| 감지 | 제안 5건(키 3건, 값 2건)이 시나리오와 일치했다. 원래 10개 문서에서는 0건이었다. |
| 수락 | 원본 없음 응답을 받은 뒤 `/reingest`로 재정규화했다. `inst:높음` 노드가 사라지고 표준 키·값으로 적재됐다. |
| 같은 변형의 두 번째 문서 | 규칙이 자동 적용됐고, 새 제안은 0건이었다. 원본은 보존됐다. |
| 정규화 이후 | 동치·경고 줄 없이 같은 정답이 나왔다. "advantages of X"는 규칙 별칭으로 `tradeoffs.pros`에 매칭됐다. |
| 회귀 | 앵커 질문 10개와 유형 질문 매트릭스 결과가 유지됐다. 단위 테스트 50개가 통과했다. |
