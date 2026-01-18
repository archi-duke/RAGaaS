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

    class Settings:
        name = "documents"
        indexes = [
            "kb_id",
            "status"
        ]
