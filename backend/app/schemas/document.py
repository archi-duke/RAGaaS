from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum

class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    DELETING = "deleting"


class DocumentBase(BaseModel):
    filename: str
    file_type: str

class Document(DocumentBase):
    id: str
    kb_id: str
    status: DocumentStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    file_path: Optional[str] = None  # Added for ingest service communication
    
    # Extraction Settings
    extractor_type: Optional[str] = None
    max_paths: Optional[int] = None
    enable_text_cleaning: Optional[bool] = False
    enable_subject_restoration: Optional[bool] = False
    generate_inverse: Optional[bool] = False
    extraction_examples: Optional[str] = None
    custom_prompt: Optional[str] = None
    # Entity Normalization Settings
    enable_entity_normalization: Optional[bool] = False
    normalization_algorithm: Optional[str] = "embedding"
    normalization_threshold: Optional[float] = 0.85
    max_sample_size: Optional[int] = 50000
    enable_normalization_confirmation: Optional[bool] = False
    
    # Pipeline State (for Resuming)
    pipeline_status: Optional[str] = None
    pipeline_metadata: Optional[dict] = None

    class Config:
        from_attributes = True

class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: Optional[dict] = None
