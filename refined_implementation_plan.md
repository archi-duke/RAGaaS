# Entity-Centric Dynamic Schema Refined Implementation Plan

사용자 피드백을 반영하여 검색 전략을 3가지 패턴으로 정교화한 구현 계획입니다.

## Core Strategy: The Three Patterns

질문의 구조(S/P/O 중 무엇이 미지수인가)에 따라 Predicate 수집 전략을 다르게 가져갑니다.

### 1. 패턴 1: `? -> P -> O` (Subject 미상)
- **예시**: "장풍(O)을 사용하는(P) 참가자는?"
- **상황**: 목적어(Object)인 **O**가 확정적임.
- **전략 (Local-P)**:
    - **O의 Incoming Predicate** (`?s ?p O`)를 집중적으로 수집합니다.
    - 역방향 검색(`^`)보다, 이미 확정된 O로 들어오는 화살표를 찾는 것이 더 정확합니다.
- **Action**: 수집된 Incoming Predicate들을 `context_predicates`로 주입하여 LLM 호출.

### 2. 패턴 2: `S -> ? -> O` (Relation 미상)
- **예시**: "성기훈(S)과 조상우(O)의 관계는?"
- **상황**: **S와 O**가 모두 확정적임.
- **전략 (Direct Edge)**:
    - 두 노드 사이의 **직접 연결**(`S ?p O` UNION `O ?p S`)을 Database에서 직접 조회합니다.
- **Action**:
    - 발견되면 LLM 호출 없이 **즉시 결과 반환** 가능 (Rule-based Optimization).
    - 또는 발견된 관계를 프롬프트에 주입하여 상세 설명 생성에 활용.

### 3. 패턴 3: `S -> P -> ?` (Object 미상)
- **예시**: "성기훈(S)의 후배(P)는 누구야?"
- **상황**: 주어(Subject)인 **S**가 확정적임.
- **전략 (Local-P + Filtering)**:
    - **S의 Outgoing Predicate** (`S ?p ?o`)를 수집합니다.
    - **Filtering**: 모든 Outgoing을 가져오면 노이즈가 될 수 있으므로, 질문의 키워드("후배")와 **텍스트 유사도**가 높은 Predicate를 우선적으로 선별합니다.
- **Action**: 선별된 Predicate들을 `context_predicates`로 주입하여 LLM 호출.

### Fallback Strategy (Global-P)
위의 Local-P 전략에서 유효한 Predicate를 찾지 못한 경우, 기존의 **Global Dynamic Schema** (전체 그래프의 Top-N 빈도 Predicate)를 Fallback으로 사용합니다.

---

## Implementation Details

### Backend: `fuseki.py`

1.  **Helper Methods Refactoring**:
    - `_fetch_entity_predicates(uri)` -> `_fetch_incoming_predicates(uri)`, `_fetch_outgoing_predicates(uri)` 로 분리 및 세분화.
    - `_filter_predicates_by_similarity(predicates, keyword)` 추가.

2.  **Query Logic Refactoring (`query` method)**:
    - **Step 1: Entity Resolution**: 질문에서 Entity 추출 및 URI 매핑 (Instance URI 중심).
    - **Step 2: Pattern Classification**: 매핑된 Entity의 수와 질문 형태를 분석하여 패턴(1, 2, 3) 결정.
    - **Step 3: Strategy Execution**: 패턴별 로직 수행 (Predicate 수집).
    - **Step 4: LLM Generation**: 수집된 Context Predicate 주입.

### Tasks

- [ ] **Entity Resolution 강화**: Instance URI(`inst:`)만 유효한 엔티티로 인정하는 로직 적용 (완료됨).
- [ ] **Predicate Helper 분리**: Incoming/Outgoing 각각 수집하는 메서드 구현.
- [ ] **Pattern 2 (S-O) 최적화**: SPARQLGenerator를 거치지 않고 직접 조회 결과를 반환하는 Fast Path 구현.
- [ ] **Pattern Logic 통합**: `query()` 메서드 내에서 3가지 분기 처리 구현.
- [ ] **Verification**: 각 패턴별 테스트 케이스(장풍, 관계, 후배) 검증.
