from typing import Optional, List, Dict, Any
from datetime import datetime
from beanie import Document
from pydantic import Field
import uuid

class KnowledgeBase(Document):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    chunking_strategy: str = "size"
    chunking_config: Dict[str, Any] = {}
    metric_type: str = "COSINE"
    enable_graph_rag: bool = False
    graph_backend: Optional[str] = "ontology"
    is_promoted: bool = False
    promotion_metadata: Dict[str, Any] = {}
    sparql_prompt_template: Optional[str] = None
    pipeline_config: Dict[str, Any] = Field(default_factory=lambda: {"stages": []})
    # Embedding model settings
    embedding_provider: str = "openai"       # built-in: openai/anthropic/google, custom: "custom"
    embedding_model: str = "text-embedding-3-small"
    embedding_provider_id: Optional[str] = None  # CustomProvider UUID (custom일 때만 사용)
    # LLM model settings (키워드 추출, 리랭커, 그래프 쿼리 생성용)
    llm_model_config: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


    class Settings:
        name = "knowledge_bases"
