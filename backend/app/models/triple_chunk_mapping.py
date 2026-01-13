"""
Triple-Chunk Mapping Model

트리플과 해당 트리플이 추출된 원문 오프셋을 저장하는 모델.
"""
from sqlalchemy import Column, String, Integer, DateTime
from app.core.database import Base
import uuid
from datetime import datetime
import hashlib


def compute_triple_hash(subject: str, predicate: str, obj: str) -> str:
    """트리플 내용을 기반으로 해시 생성"""
    key = f"{subject}|{predicate}|{obj}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class TripleChunkMapping(Base):
    __tablename__ = "triple_chunk_mappings"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(String, nullable=False, index=True)
    doc_id = Column(String, nullable=True, index=True)
    chunk_id = Column(String, nullable=True, index=True)  # 청크 ID 추가 (정확한 매핑용)
    triple_hash = Column(String, nullable=False, index=True)
    subject = Column(String, nullable=False)
    predicate = Column(String, nullable=False)
    object = Column(String, nullable=False)
    source_start = Column(Integer, nullable=False)  # 원문 시작 오프셋
    source_end = Column(Integer, nullable=False)    # 원문 끝 오프셋
    created_at = Column(DateTime, default=datetime.utcnow)
