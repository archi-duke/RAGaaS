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
    schema_rules_version: int = 0
    # 스키마 출처/상태 (docs/design/schema/design-graph-promotion.md): none | declared | induced / draft | active | stale
    schema_source: str = "none"
    schema_status: Optional[str] = None  # 스키마 매핑 규칙이 바뀔 때마다 +1 (docs/design/schema/design-schema-mismatch.md)
    promotion_metadata: Dict[str, Any] = {}
    sparql_prompt_template: Optional[str] = None
    pipeline_config: Dict[str, Any] = Field(default_factory=lambda: {"stages": []})   # 운영(live) 구성 — 검색은 이것만 읽는다
    # 운영/테스트 분리 (docs/design/agent/design-search-entry-and-pipeline-versions.md §5)
    pipeline_draft: Optional[Dict[str, Any]] = None       # 테스트 탭에서 편집 중인 구성 (버전 아님, 자동 저장)
    pipeline_draft_base: Optional[str] = None             # 테스트 구성이 출발한 운영 버전(커밋 SHA)
    pipeline_live_ref: Optional[str] = None               # 운영 구성의 Git 커밋 SHA (이력: 공용 Gitea)
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
