from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any
from .common import PaginationParams

class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None
    chunking_strategy: str = "size"
    chunking_config: dict = {}
    metric_type: str = "COSINE"  # COSINE or IP
    enable_graph_rag: bool = False
    graph_backend: Optional[str] = "ontology"
    is_promoted: bool = False
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_provider_id: Optional[str] = None
    llm_model_config: Dict[str, Any] = {}

class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass

class KnowledgeBase(KnowledgeBaseBase):
    id: str
    created_at: datetime
    updated_at: datetime
    document_count: Optional[int] = 0
    total_size: Optional[int] = 0
    is_promoted: bool = False
    promotion_metadata: Optional[dict] = {}
    pipeline_config: Optional[dict] = {"stages": []}

    class Config:
        from_attributes = True

class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
