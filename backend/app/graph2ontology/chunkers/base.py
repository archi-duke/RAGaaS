"""청커 기본 인터페이스"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union, Optional,  Generator

from app.graph2ontology.models.chunk import BaseChunk


class BaseChunker(ABC):
    """청커 기본 클래스"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        Args:
            chunk_size: 청크 크기 (문자 수)
            chunk_overlap: 청크 간 오버랩 (문자 수)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    @abstractmethod
    def chunk_text(
        self, 
        text: str, 
        doc_id: str, 
        doc_ver: str = "v1"
    ) -> Generator[BaseChunk, None, None]:
        """텍스트를 청크로 분할
        
        Args:
            text: 원본 텍스트
            doc_id: 문서 ID
            doc_ver: 문서 버전
            
        Yields:
            청크 객체
        """
        pass
    
    def chunk_file(
        self, 
        file_path: Union[str, Path], 
        doc_id: Optional[str] = None,
        doc_ver: str = "v1"
    ) -> Generator[BaseChunk, None, None]:
        """파일을 청크로 분할
        
        Args:
            file_path: 파일 경로
            doc_id: 문서 ID (None이면 파일명 사용)
            doc_ver: 문서 버전
            
        Yields:
            청크 객체
        """
        file_path = Path(file_path)
        
        if doc_id is None:
            doc_id = file_path.stem
        
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        
        yield from self.chunk_text(text, doc_id, doc_ver)
