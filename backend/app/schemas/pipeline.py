from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Literal

class PipelineStage(BaseModel):
    """개별 파이프라인 스테이지 정의"""
    # smalltalk: 검색 앞단 게이트. 인사/잡담이면 검색 없이 LLM 이 바로 응답하고 파이프라인 중단.
    # agentic: 검색 스테이지를 도구로 삼아 검색 방식·순서를 정하고 단계별로 진행 (docs/design/graph/design-agentic-filter.md).
    # answer_check: 답변 뒤 근거 검사 — 답변 문장이 검색 근거에 있는지 판정 (app/services/retrieval/answer_check.py).
    type: Literal["smalltalk", "agentic", "ann", "bm25", "brute_force", "graph", "rerank", "ner_filter", "answer_check"]
    params: Dict[str, Any] = {}
    # 스테이지 식별자 (화면이 붙인다). 실패 연결이 이 값으로 대상을 가리킨다.
    id: Optional[str] = None
    # 실패/예외 연결 (2026-11-25): 이 스테이지가 실패하면 이 id 의 (뒤쪽) 스테이지로 넘어간다.
    # 없으면 실패를 알리고 파이프라인을 멈춘다. 정상(성공) 연결은 바로 다음 스테이지.
    # 실패 연결의 대상 스테이지는 실패했을 때만 실행된다 (성공하면 건너뜀).
    on_failure: Optional[str] = None

class PipelineConfig(BaseModel):
    """검색 파이프라인 전체 구성"""
    stages: List[PipelineStage] = []

class StageContext(BaseModel):
    """스테이지 간 전달되는 컨텍스트"""
    query: str
    results: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}
