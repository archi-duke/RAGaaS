from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Literal

class PipelineStage(BaseModel):
    """개별 파이프라인 스테이지 정의"""
    # smalltalk: 검색 앞단 게이트. 인사/잡담이면 검색 없이 LLM 이 바로 응답하고 파이프라인 중단.
    # agentic: 검색 스테이지를 도구로 삼아 검색 방식·순서를 정하고 단계별로 진행 (docs/design-agentic-filter.md).
    type: Literal["smalltalk", "agentic", "ann", "bm25", "brute_force", "graph", "rerank", "ner_filter"]
    params: Dict[str, Any] = {}

class PipelineConfig(BaseModel):
    """검색 파이프라인 전체 구성"""
    stages: List[PipelineStage] = []

class StageContext(BaseModel):
    """스테이지 간 전달되는 컨텍스트"""
    query: str
    results: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}
