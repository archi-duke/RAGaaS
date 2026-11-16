"""검색 기록 — 질의마다 질문·답변·실행 로그·추론 과정(에이전틱 스크래치패드 포함)을 남겨 사후 검토에 쓴다."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie import Document
from pydantic import Field


class ChatTrace(Document):
    kb_id: str
    query: str
    answer: str = ""
    strategy: Optional[str] = None
    execution_time: float = 0.0
    has_error: bool = False
    used_fallback: bool = False
    execution_log: List[str] = Field(default_factory=list)
    reasoning: Dict[str, Any] = Field(default_factory=dict)     # graph_metadata.reasoning (agentic 포함)
    result_summary: Optional[str] = None
    triples: List[Dict[str, Any]] = Field(default_factory=list)  # 답변 컨텍스트에 들어간 트리플 (최대 150)
    chunks: List[Dict[str, Any]] = Field(default_factory=list)   # chunk_id·doc·score·앞부분
    pipeline: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "chat_traces"
