# 설계: KB 용어 사전 (한영·음역·동의어·상위 개념)

작성일: 2026-11-16
상태: L1·L2 구현 완료 (2026-11-16), L3~L5 예정
관련: `docs/design-mcp-agent-query.md` §7.1 (드러난 한계), `docs/design-schema-editor.md`

---

## 1. 문제

질문의 말과 그래프의 표기가 다르면 엔티티와 값을 찾지 못한다.

| 질문 | 그래프 | 종류 |
|---|---|---|
| 마이크로서비스, 헥사고날, 클린 아키텍처 | Microservices, Hexagonal 아키텍처, Clean Architecture | 음역 |
| 가용성, 성능 | Availability, performance | 한영 |
| Einstein, Albert Einstein | 아인슈타인 | 영한 |
| 수정 용이성, modifiability | 변경 용이성 | 동의어 |
| 유지보수성, maintainability | (값 없음) 변경·테스트·관리 용이성 | 상위 개념 |

그래프 자체도 한영과 표기가 섞여 있다. test-ontology2 의 라벨 270개 중 영문만으로 된 것이 47개다.
같은 대상이 두 번 들어간 경우도 있다 (`Event Driven Architecture` / `Event-Driven Architecture`).

## 2. 실험 (2026-11-16, test-ontology2 라벨 258개)

| 방식 | 정답 |
|---|---|
| 지금 문자열 일치 | 거의 0 |
| 임베딩 유사도 (text-embedding-3-small) | 1 / 14. 헥사고날 → Hexagonal 이 161위, 클린 아키텍처 → Clean Architecture 가 247위 |
| LLM 별칭(적재 시 1회) + 문자열 일치 | 11 / 15 |
| + 일반어 제거 표기 + 상위 개념 다국어 표기 | 18 / 18 (작은 자체 세트라 낙관적 — §6 평가 세트로 재확인) |

**결론**: 검색할 때 유사도로 맞추는 방식은 음역과 짧은 말에 약하다. 폐쇄망에서는 임베딩 모델 품질도 장담할 수 없다.
**적재할 때 LLM 으로 별칭을 한 번 만들어 두고, 검색할 때는 사전만 찾는다.**

## 3. 사전 항목

KB 마다 라벨 하나에 항목 하나다. Mongo `kb_lexicon` 에 저장한다.

```jsonc
{
  "kb_id": "…", "label": "Hexagonal 아키텍처", "norm": "hexagonal아키텍처",
  "ko": ["헥사고날 아키텍처", "육각형 아키텍처"], "en": ["Hexagonal Architecture"],
  "syn": ["Ports and Adapters", "포트와 어댑터"],
  "broader": [{"label": "아키텍처 스타일", "status": "proposed"}],   // proposed | approved | rejected
  "concept_only": false,     // 그래프 라벨이 아니라 상위 개념으로만 등장한 말 (예: 유지보수성)
  "skip": false,             // 문장형 라벨 — 별칭을 만들지 않음
  "source": "llm",           // llm | user (사람이 고친 항목은 재생성 때 덮어쓰지 않음)
  "model": "glm-5.2", "updated_at": "…"
}
```

## 4. 만들기 (적재 후, 증분)

1. **대상 라벨**: 유형 멤버의 `rdfs:label` + 카탈로그 값 중 짧은 라벨(30자 이하, 문장형 제외). 질의 계획 카탈로그와 같은 출처다.
2. **사전에 없는 라벨만** 40개씩 묶어 LLM 에 보낸다. 동시 호출은 core/llm 제한(4)을 따른다.
3. **상위 개념도 항목으로 만든다.** 상위 개념으로 나온 말 중 사전에 없는 것은 같은 방식으로 별칭을 만든다 (`concept_only=true`). '유지보수성'의 영어 표기 'maintainability'가 이렇게 들어간다.
4. **프롬프트 원칙**
   - 동의어는 *뜻이 같은 것만* 넣는다. 넓거나 좁은 말은 상위 개념 칸에 넣는다.
   - 인명은 성·전체 이름·원어 표기를 모두 넣는다 (아인슈타인 → Einstein, Albert Einstein, 알베르트 아인슈타인).
   - KB 이름과 설명으로 도메인을 알려 준다.
5. **실행 시점**: 수동 `POST /lexicon/build`. 이후 적재·재추출이 끝나면 자동으로 증분 실행한다 (L4).
   비용은 라벨 258개에 LLM 호출 7번, 약 1분이다.

## 5. 찾기 (검색 시, LLM 없음)

질문의 말을 정규화(`entity_linking._compact`)한 뒤 아래 순서로 찾는다.

| 순서 | 일치 | 점수 |
|---|---|---|
| 1 | 라벨 그대로 | 120 |
| 2 | 별칭 (ko / en / syn) | 100 |
| 3 | 일반어를 뺀 표기 (`헥사고날 아키텍처` → `헥사고날`) | 90 |
| 4 | 기존 링킹 점수 (`score_candidate`) | 60~ |

- 일반어: 아키텍처, 스타일, 패턴, 이론, 실험, architecture, style, pattern, theory, experiment.
- **상위 개념**은 일치와 따로 `narrower`(하위 라벨 목록)로 돌려준다. `approved` 가 아닌 것은 `unreviewed` 로 표시한다.
- 같은 별칭이 여러 라벨을 가리키면 **중복 후보**다 (`Micro Frontend` / `Micro-Frontend`). `GET /lexicon/duplicates` 로 보여 주고 스키마 편집기 병합으로 정리한다.

## 6. 평가 세트

- 파일: `docs/datasets/lexicon-eval.json`. 3개 KB, 질문 표기 → 정답 라벨.
- 종류: 음역, 한영, 영한, 동의어, 인명, 상위 개념, 없어야 하는 말(negative).
- 지표:
  - 재현율: 정답이 일치 목록에 있음.
  - 오일치: 일치 목록에 정답 밖의 라벨이 있음.
  - negative 통과: 아무것도 일치하지 않음.
- 실행: `backend/scripts/eval_lexicon.py`. 프롬프트나 일치 규칙을 바꿀 때마다 돌린다.

## 7. 단계

| 단계 | 내용 |
|---|---|
| L1 | 평가 세트 + 사전 생성·저장(증분) + `lookup_values` / `resolve_entities` 연결 |
| L2 | 중복 후보 API, 평가 실행·튜닝 |
| L3 | 스키마 편집기 "용어 사전" 탭 (별칭 수정·삭제, 상위 개념 승인, 중복 → 병합) |
| L4 | 적재·재추출 후 자동 증분, 지금 검색의 엔티티 링킹에도 사전 적용 (`translated_entities` 의존 줄이기) |
| L5 | Fuseki 에 `skos:altLabel` 로도 기록 (SPARQL 사용자·Neo4j 이전 대비) |

## 7.1 L1·L2 결과 (2026-11-16)

구현:
- `backend/app/services/agent_query/lexicon.py` (생성·색인·찾기·중복)
- `backend/app/models/lexicon.py`
- API `POST /{kb}/lexicon/build`, `GET /{kb}/lexicon/status`, `GET /{kb}/lexicon`, `GET /{kb}/lexicon/duplicates`
- 평가 `backend/scripts/eval_lexicon.py`
- `lookup_values` 와 `resolve_entities` 가 사전을 쓴다. 상위 개념은 `narrower` 로 돌려준다.

| | 사전 없음 | 첫 생성 | 최종 |
|---|---|---|---|
| 평가 세트 (63개) | 5 / 63 (8%, negative 만) | 59 / 63 (94%) | **63 / 63** |
| 홀드아웃 (25개, 튜닝에 안 씀) | — | — | **25 / 25** (첫 실행 24/25, 틀린 1건은 정답지 오류) |

**생성 비용**: 3개 KB 동시에 약 4~5분. 라벨 248 / 248 / 574개, 상위 개념 15~80개.
응답에서 빠진 라벨을 다시 요청한 건수는 1~17개다.

**찾기 시간**: values 92~192ms, entities 43~110ms (카탈로그 조회 포함).

**튜닝하며 고친 것** (첫 생성 94% → 100%)

1. 응답 누락: LLM 이 40개 묶음에서 일부 라벨을 건너뛴다 → 빠진 라벨만 다시 요청. 빈 항목은 일반 빌드에서도 다시 만든다.
2. 대시 차이: `Michelson–Morley`(en dash) ≠ `-` → 정규화 키를 NFKC + 대시 통일로.
3. 정규화가 같은 다른 라벨 (`Clean Architecture` / `clean-architecture`): 하나가 덮어쓰던 문제 → `variants` 로 함께 둔다.
4. 동치 경로의 값이 `lookup_values` 에서 빠짐 → 포함하고, 대표 경로로 보고한다.
5. 맥락 없는 값 (`eventual` → '최종적인') → 프롬프트에 "쓰임"(어느 속성의 값인지)을 붙인다 → '결과적 일관성'.
6. 동의어를 한쪽 언어로만 줌 (`Ports and Adapters`) → 양쪽 표기 요구. 흔한 한국어 표기 여럿 요구 (관측성 / 관측 가능성).
7. 상위 개념 항목이 실제 라벨과 같은 말이면 그 별칭을 실제 라벨에 빌려준다 (`배포성` ≡ `deployability` → '배포 용이성').
8. 설명형 라벨(4어절 이상)은 별칭을 색인하지 않는다 ('단순 CRUD에 포트/어댑터 도입은 과설계'가 '헥사고날'로 잡히던 문제).

**남은 오일치 = 실제 중복 데이터**: `에르빈`/`슈뢰딩거`, `J. C. 맥스웰`/`맥스웰`, `clean-architecture`/`Clean Architecture`.
`/lexicon/duplicates` 가 test-ontology2 에서 8묶음, test-ontology3 에서 59묶음을 보여 준다.
진짜 중복(`디랙`/`폴 디랙`, `천동설`/`프톨레마이오스 천동설`)과 LLM 잡음(`빈 대학`/`킬 대학`이 같은 일반 동의어를 공유)이 섞여 있다.
→ L3 편집기에서 사람이 병합하거나 별칭을 지운다.

**주의**: 평가 세트는 작다(88개). 새 KB·도메인을 붙일 때 그 KB 의 항목을 추가하고, 프롬프트를 바꾸면 두 세트를 모두 다시 돌린다.

## 8. 위험

| 위험 | 대응 |
|---|---|
| LLM 이 틀린 동의어를 만듦 → 엉뚱한 일치 | 동의어는 같은 뜻만. 평가의 오일치 지표로 감시. 사람이 고친 항목(`source=user`)은 보존 |
| 상위 개념 잡음 (실험: 마이크로서비스 → '백엔드 독립 배포') | 상위 개념은 `proposed` 로 두고, 승인 전에는 `unreviewed` 표시. 에이전트·스킬은 이를 판단 근거로만 쓴다 |
| 일반어 제거로 짧은 말 충돌 | 제거 후 2자 이상만. 점수를 별칭보다 낮게 |
| 라벨이 많은 KB (수천 개) | 증분 생성. 비용은 라벨 수에 비례 (40개당 호출 1회) |
