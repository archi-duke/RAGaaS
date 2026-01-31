"""OE-Chunk: 온톨로지 추출용 청커"""

import re
from typing import Union, Optional,  Generator

from app.graph2ontology.chunkers.base import BaseChunker
from app.graph2ontology.models.chunk import OEChunk


class OEChunker(BaseChunker):
    """OE-Chunk 청커: 온톨로지 추출용 (섹션 단위, 오버랩 큼)"""
    
    def __init__(
        self, 
        chunk_size: int = 2000, 
        chunk_overlap: int = 500,
        section_aware: bool = True
    ):
        """
        Args:
            chunk_size: 청크 크기 (문자 수)
            chunk_overlap: 청크 간 오버랩 (문자 수)
            section_aware: 섹션 인식 여부
        """
        super().__init__(chunk_size, chunk_overlap)
        self.section_aware = section_aware
        
        # 섹션 헤더 패턴 (한국어 문서 기준)
        self.section_patterns = [
            r"^#{1,6}\s+",  # Markdown 헤더
            r"^\d+(\.\d+)*\.?\s+",  # 번호 (1. 1.1 1.1.1)
            r"^[가-힣]{1,2}\.\s+",  # 한글 번호 (가. 나.)
            r"^[①-⑳]\s+",  # 원숫자
            r"^【.+】",  # 【섹션】 형식
        ]
    
    def _detect_sections(self, text: str) -> list[tuple[int, str, str]]:
        """섹션 경계 탐지
        
        Returns:
            [(시작위치, 섹션경로, 헤더텍스트), ...]
        """
        sections = [(0, "0", "")]  # 기본 섹션
        
        for pattern in self.section_patterns:
            for match in re.finditer(pattern, text, re.MULTILINE):
                start = match.start()
                header = match.group().strip()
                # 간단한 섹션 경로 추출
                numbers = re.findall(r"\d+", header)
                section_path = ".".join(numbers) if numbers else f"s{len(sections)}"
                sections.append((start, section_path, header))
        
        # 위치순 정렬
        sections.sort(key=lambda x: x[0])
        return sections
    
    def chunk_text(
        self, 
        text: str, 
        doc_id: str, 
        doc_ver: str = "v1"
    ) -> Generator[OEChunk, None, None]:
        """텍스트를 OE-Chunk로 분할"""
        
        if not text.strip():
            return
        
        if self.section_aware:
            sections = self._detect_sections(text)
        else:
            sections = [(0, "0", "")]
        
        chunk_idx = 0
        pos = 0
        
        while pos < len(text):
            # 현재 위치의 섹션 찾기
            current_section = "0"
            for start, path, _ in reversed(sections):
                if start <= pos:
                    current_section = path
                    break
            
            # 청크 끝 위치 결정
            end = min(pos + self.chunk_size, len(text))
            
            # 문장/단락 경계에서 자르기 시도
            if end < len(text):
                # 문장 끝 (. ! ? 다음 공백) 찾기
                last_sentence = max(
                    text.rfind(". ", pos, end),
                    text.rfind("! ", pos, end),
                    text.rfind("? ", pos, end),
                    text.rfind("다. ", pos, end),  # 한국어 문장 끝
                    text.rfind("요. ", pos, end),
                    text.rfind("\n\n", pos, end),  # 단락 구분
                )
                if last_sentence > pos + self.chunk_size // 2:
                    end = last_sentence + 2
            
            chunk_text = text[pos:end].strip()
            
            if chunk_text:
                yield OEChunk(
                    doc_id=doc_id,
                    doc_ver=doc_ver,
                    chunk_idx=chunk_idx,
                    text=chunk_text,
                    section_path=current_section,
                    start_offset=pos,
                    end_offset=end,
                    overlap_prev=min(self.chunk_overlap, pos) if chunk_idx > 0 else 0,
                    overlap_next=min(self.chunk_overlap, len(text) - end) if end < len(text) else 0,
                )
                chunk_idx += 1
            
            # 다음 청크 시작 (오버랩 고려)
            pos = end - self.chunk_overlap if end < len(text) else end
            
            # 무한 루프 방지
            if pos <= 0 or (end >= len(text) and pos >= end - self.chunk_overlap):
                break
