from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.sqlite import JSON
from app.core.database import Base
import uuid
from datetime import datetime

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    chunking_strategy = Column(String, default="size")
    chunking_config = Column(JSON, default={})
    metric_type = Column(String, default="COSINE")  # COSINE or IP
    enable_graph_rag = Column(Boolean, default=False)
    graph_backend = Column(String, default="ontology", nullable=True) # ontology or neo4j
    is_promoted = Column(Boolean, default=False)
    promotion_metadata = Column(JSON, default={})
    pipeline_config = Column(JSON, default={"stages": []})  # Search pipeline configuration
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
