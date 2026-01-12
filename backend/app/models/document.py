from sqlalchemy import Column, String, DateTime, ForeignKey, Enum
from app.core.database import Base
import uuid
from datetime import datetime
import enum

class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    DELETING = "deleting"


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(String, ForeignKey("knowledge_bases.id"))
    filename = Column(String)
    file_type = Column(String)
    status = Column(String, default=DocumentStatus.PENDING.value)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

