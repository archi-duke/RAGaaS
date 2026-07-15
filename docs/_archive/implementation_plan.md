# [기능 추가] 부분 텍스트 추출 테스트

## 목표
청크 전체가 아닌, 사용자가 선택한 특정 텍스트 부분에 대해서만 "추출 테스트(Extract Test)"를 수행할 수 있도록 지원합니다.

## 변경 제안

### 프론트엔드
#### [수정] [ChunkDetailModal.tsx](file:///Users/dukekimm/Works/RAGaaS/frontend/src/components/ChunkDetailModal.tsx)
1. **선택 영역 감지 (Selection Tracking)**:
   - `useRef`를 사용하여 청크 콘텐츠 영역(`div`)을 참조합니다.
   - `selectionText` 상태(State)를 추가합니다.
   - `document.addEventListener('selectionchange')`를 통해 사용자가 텍스트를 선택할 때, 해당 선택이 콘텐츠 영역 내부인지 확인하고 텍스트를 저장합니다.

2. **추출 로직 (Extraction Logic)**:
   - `handleExtract` 함수에서 `selectionText`가 존재하면 이를 추출 대상(`chunk_text`)으로 사용합니다.
   - 선택된 텍스트가 없으면 기존처럼 `chunk.content`(전체)를 사용합니다.

3. **UI 피드백 (Button Feedback)**:
   - "Extract" 버튼의 라벨을 상황에 따라 변경하여 명확성을 높입니다:
     - 텍스트 선택 시: "Extract (Selection)"
     - 선택 없음: "Extract Test"

## 검증 계획
### 수동 검증
1. 청크 상세(Chunk Detail) 모달을 엽니다.
2. **시나리오 A (기본)**: 텍스트 선택 없이 "Extract Test" 하위의 "Extract" 버튼 클릭 -> 전체 내용이 추출되는지 확인.
3. **시나리오 B (부분 선택)**: 특정 문장을 드래그하여 선택한 후 "Extract" 클릭 -> 선택한 문장만 추출되는지 확인 (버튼 라벨 변경 확인).
