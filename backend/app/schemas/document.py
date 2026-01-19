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

    class Config:
        from_attributes = True

class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: Optional[dict] = None
