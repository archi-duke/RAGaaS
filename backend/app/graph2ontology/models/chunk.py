"""청크 모델"""

from enum import Enum
from typing import Union, Optional,  Optional, Union
import hashlib
from pydantic import BaseModel, Field, computed_field


class ChunkType(str, Enum):
    """청크 유형"""
    OE = "oe"  # Ontology Extraction용
    RAG = "rag"  # RAG 인덱싱용


class BaseChunk(BaseModel):
    """청크 기본 모델"""
    chunk_type: ChunkType
    doc_id: str = Field(..., description="문서 ID")
    doc_ver: str = Field(default="v1", description="문서 버전")
    chunk_idx: int = Field(..., description="청크 인덱스 (문서 내)")
    text: str = Field(..., description="청크 텍스트")
    
    # 메타데이터
    section_path: Optional[str] = Field(default=None, description="섹션 경로 (e.g., '1.2.3')")
    page: Optional[int] = Field(default=None, description="페이지 번호")
    start_offset: Optional[int] = Field(default=None, description="문서 내 시작 오프셋")
    end_offset: Optional[int] = Field(default=None, description="문서 내 끝 오프셋")
    
    @computed_field
    @property
    def chunk_id(self) -> str:
        """청크 고유 ID: {doc_id}|{doc_ver}|{chunk_idx:04d}"""
        return f"{self.doc_id}|{self.doc_ver}|{self.chunk_idx:04d}"
    
    @computed_field
    @property
    def chunk_hash(self) -> str:
        """청크 텍스트 해시 (MD5)"""
        return hashlib.md5(self.text.encode("utf-8")).hexdigest()
    
    @computed_field
    @property
    def milvus_uri(self) -> str:
        """Milvus URI: milvus://{doc_id}/{doc_ver}/{chunk_idx}"""
        return f"milvus://{self.doc_id}/{self.doc_ver}/{self.chunk_idx:04d}"
    
    @computed_field
    @property
    def graph_uri(self) -> str:
        """Named Graph URI: urn:ragchunk:{doc_id}:{doc_ver}:{chunk_idx}"""
        return f"urn:ragchunk:{self.doc_id}:{self.doc_ver}:{self.chunk_idx:04d}"


class OEChunk(BaseChunk):
    """OE-Chunk: 온톨로지 추출용 (오버랩/섹션 단위)"""
    chunk_type: ChunkType = ChunkType.OE
    overlap_prev: int = Field(default=0, description="이전 청크와 오버랩 문자 수")
    overlap_next: int = Field(default=0, description="다음 청크와 오버랩 문자 수")


class RAGChunk(BaseChunk):
    """RAG-Chunk: 검색용 (짧고 독립적인 의미 단위)"""
    chunk_type: ChunkType = ChunkType.RAG
    source_oe_chunk_idx: Optional[int] = Field(
        default=None, 
        description="원본 OE-Chunk 인덱스 (연결용)"
    )
    
    def to_milvus_record(self) -> dict:
        """Milvus 적재용 레코드로 변환"""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_ver": self.doc_ver,
            "chunk_idx": self.chunk_idx,
            "text": self.text,
            "chunk_hash": self.chunk_hash,
            "section_path": self.section_path or "",
            "page": self.page or -1,
            "start_offset": self.start_offset or -1,
            "end_offset": self.end_offset or -1,
        }


class ChunkBatch(BaseModel):
    """청크 배치"""
    doc_id: str
    doc_ver: str
    oe_chunks: list[OEChunk] = Field(default_factory=list)
    rag_chunks: list[RAGChunk] = Field(default_factory=list)
    
    @property
    def total_oe_chunks(self) -> int:
        return len(self.oe_chunks)
    
    @property
    def total_rag_chunks(self) -> int:
        return len(self.rag_chunks)
