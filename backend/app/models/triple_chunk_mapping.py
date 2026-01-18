"""
Triple-Chunk Mapping Model

트리플과 해당 트리플이 추출된 원문 오프셋을 저장하는 모델.
"""
from beanie import Document
from pydantic import Field
import uuid
from datetime import datetime
import hashlib
from typing import Optional

def compute_triple_hash(subject: str, predicate: str, obj: str) -> str:
    """트리플 내용을 기반으로 해시 생성"""
    key = f"{subject}|{predicate}|{obj}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class TripleChunkMapping(Document):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kb_id: str
    doc_id: Optional[str] = None
    chunk_id: Optional[str] = None  # 청크 ID 추가 (정확한 매핑용)
    triple_hash: str
    subject: str
    predicate: str
    object: str
    source_start: int # 원문 시작 오프셋
    source_end: int   # 원문 끝 오프셋
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "triple_chunk_mappings"
        indexes = [
            "kb_id",
            "doc_id",
            "chunk_id",
            "triple_hash"
        ]
