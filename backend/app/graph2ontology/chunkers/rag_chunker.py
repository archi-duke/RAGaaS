"""RAG-Chunk: 검색용 청커"""

import re
from typing import Union, Optional,  Generator, Optional

from app.graph2ontology.chunkers.base import BaseChunker
from app.graph2ontology.models.chunk import RAGChunk


class RAGChunker(BaseChunker):
    """RAG-Chunk 청커: 검색용 (짧고 독립적인 의미 단위)"""
    
    def __init__(
        self, 
        chunk_size: int = 500, 
        chunk_overlap: int = 100,
    ):
        """
        Args:
            chunk_size: 청크 크기 (문자 수)
            chunk_overlap: 청크 간 오버랩 (문자 수)
        """
        super().__init__(chunk_size, chunk_overlap)
        
        # 문장 분리 패턴
        self.sentence_end_pattern = re.compile(
            r'(?<=[.!?다요])\s+|(?<=\n\n)'
        )
    
    def _split_sentences(self, text: str) -> list[str]:
        """텍스트를 문장 단위로 분할"""
        sentences = self.sentence_end_pattern.split(text)
        return [s.strip() for s in sentences if s.strip()]
    
    def chunk_text(
        self, 
        text: str, 
        doc_id: str, 
        doc_ver: str = "v1",
        source_oe_chunk_idx: Optional[int] = None,
        base_offset: int = 0,
        section_path: Optional[str] = None,
    ) -> Generator[RAGChunk, None, None]:
        """텍스트를 RAG-Chunk로 분할
        
        Args:
            text: 원본 텍스트
            doc_id: 문서 ID
            doc_ver: 문서 버전
            source_oe_chunk_idx: 원본 OE-Chunk 인덱스 (연결용)
            base_offset: 문서 내 기준 오프셋
            section_path: 섹션 경로
        """
        if not text.strip():
            return
        
        sentences = self._split_sentences(text)
        
        chunk_idx = 0
        current_chunk: list[str] = []
        current_length = 0
        current_offset = base_offset
        
        for sentence in sentences:
            sentence_len = len(sentence)
            
            # 현재 청크에 추가 가능한지 확인
            if current_length + sentence_len <= self.chunk_size:
                current_chunk.append(sentence)
                current_length += sentence_len + 1  # +1 for space
            else:
                # 현재 청크 출력
                if current_chunk:
                    chunk_text = " ".join(current_chunk)
                    yield RAGChunk(
                        doc_id=doc_id,
                        doc_ver=doc_ver,
                        chunk_idx=chunk_idx,
                        text=chunk_text,
                        section_path=section_path,
                        start_offset=current_offset,
                        end_offset=current_offset + len(chunk_text),
                        source_oe_chunk_idx=source_oe_chunk_idx,
                    )
                    chunk_idx += 1
                    current_offset += len(chunk_text)
                
                # 오버랩 처리: 이전 청크의 마지막 문장들을 일부 유지
                overlap_sentences = []
                overlap_length = 0
                for s in reversed(current_chunk):
                    if overlap_length + len(s) <= self.chunk_overlap:
                        overlap_sentences.insert(0, s)
                        overlap_length += len(s) + 1
                    else:
                        break
                
                current_chunk = overlap_sentences + [sentence]
                current_length = sum(len(s) for s in current_chunk) + len(current_chunk) - 1
        
        # 마지막 청크 출력
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            yield RAGChunk(
                doc_id=doc_id,
                doc_ver=doc_ver,
                chunk_idx=chunk_idx,
                text=chunk_text,
                section_path=section_path,
                start_offset=current_offset,
                end_offset=current_offset + len(chunk_text),
                source_oe_chunk_idx=source_oe_chunk_idx,
            )
