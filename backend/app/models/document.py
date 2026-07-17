from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import Field
import uuid
import enum

class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    DELETING = "deleting"

class Document(Document):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kb_id: str
    filename: str
    file_type: str
    status: str = DocumentStatus.PENDING.value
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    file_path: Optional[str] = None
    
    # Extraction Settings
    extractor_type: Optional[str] = None
    max_paths: Optional[int] = None
    enable_text_cleaning: Optional[bool] = False
    enable_subject_restoration: Optional[bool] = True
    generate_inverse: Optional[bool] = False
    extraction_examples: Optional[str] = None
    custom_prompt: Optional[str] = None
    # Entity Normalization Settings
    enable_entity_normalization: Optional[bool] = False
    normalization_algorithm: Optional[str] = "embedding"  # embedding | string | llm
    normalization_threshold: Optional[float] = 0.85
    max_sample_size: Optional[int] = 50000
    enable_normalization_confirmation: Optional[bool] = False
    
    # Pipeline State (for Resuming)
    pipeline_status: Optional[str] = None # e.g. "ENTITY_EXTRACTED", "TRIPLE_EXTRACTED"
    pipeline_metadata: Optional[dict] = None # Stores intermediate data (preview_id, dictionary, summary)
    
    # Statistics
    chunk_count: Optional[int] = 0
    entity_count: Optional[int] = 0
    triple_count: Optional[int] = 0

    # Progress / Error reporting (§4.2, §4.3)
    progress: Optional[int] = 0
    error: Optional[str] = None

    # Stuck-state recovery (§4.4) — computed at read time in list_documents,
    # never persisted (doc.save() must not be called after setting this).
    stale: Optional[bool] = False

    class Settings:
        name = "documents"
        indexes = [
            "kb_id",
            "status"
        ]
