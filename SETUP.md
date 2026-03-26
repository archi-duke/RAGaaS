# RAG Management System - Setup Guide

## OpenAI API Key 설정 (필수)

문서 처리를 위해서는 OpenAI API 키가 필요합니다.

### 1. .env 파일 생성

```bash
cd backend
cp .env.example .env
```

### 2. API 키 입력

`.env` 파일을 열어서 OpenAI API 키를 입력하세요:

```
OPENAI_API_KEY=sk-proj-your-actual-api-key-here
```

### 3. 백엔드 재시작

API 키를 설정한 후 백엔드를 재시작해야 합니다:

```bash
# 현재 실행 중인 uvicorn 중지 (Ctrl+C)
# 그리고 다시 시작:
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 문제 해결

### 문서가 'processing' 상태에 멈춰있는 경우

OpenAI API 키 없이 업로드한 문서는 'processing' 상태에서 멈춰있습니다.
API 키 설정 후 다음 중 하나를 선택하세요:

1. **문서 삭제 후 재업로드** (권장)
2. **데이터베이스 수동 정리**:
   ```bash
   # processing 상태 문서 삭제
   sqlite3 backend/rag_system.db "DELETE FROM documents WHERE status='processing';"
   ```

### API 키 없이 테스트하려면

로컬 임베딩 모델(예: sentence-transformers)을 사용하도록 코드를 수정해야 합니다.

(SubKey, customfield_15209)
(Client, customfield_15235)
(Actor, customfield_15215)
(requirement_type, customfield_12555)
(Structure Diagram, customfield_18204)
(Pre Condition, customfield_15216)
(Source, customfield_15210)
(Behavior Diagram, customfield_18205)
(BasicFlow, customfield_15217)
(Stimulus, customfield_15211)
(Design Objectives, customfield_18206)
(AlternativeFlow, customfield_15218)
(PROS, customfield_18207)
(ExceptionFlow, customfield_15219)
(Artifact, customfield_15208)
(CONS, customfield_18208)
(Post Condition, customfield_15220)
(Response, customfield_15212)
(Score, customfield_18209)
(Measure, customfield_15213)
(Evaluation, customfield_18210)
(Response Scenario, customfield_15207)
(Decision, customfield_18211)
(QAI, customfield_15204)
(Sensitivity, customfield_18212)
(QAD, customfield_15205)
(TradeOff (S), customfield_18213)
(QAS, customfield_15206)
(Risk (W), customfield_18216)
(quality_attribute, customfield_18217)
(NonRisk (C), customfield_18214)
(Architectural Diagram, customfield_18215)
(VOS, customfield_15247)
(Features, customfield_15248)
(Requirements, customfield_15249)
(A-Design, customfield_18202)
(D-Design, customfield_18203)
(Tests, customfield_18201)
