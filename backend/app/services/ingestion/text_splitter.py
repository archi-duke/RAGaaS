from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import OpenAIEmbeddings
from typing import List, Dict
from app.core.config import settings

class ChunkingService:
    def __init__(self):
        self.default_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )

    def chunk_by_size(self, text: str, chunk_size: int = 1000, overlap: int = 200, separators: List[str] = None) -> List[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            separators=separators or ["\n\n", "\n", " ", ""]
        )
        return splitter.split_text(text)

    def chunk_parent_child(self, text: str, parent_size: int = 2000, child_size: int = 500, parent_overlap: int = 0, child_overlap: int = 100, separators: List[str] = None) -> List[Dict]:
        parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=parent_size, 
            chunk_overlap=parent_overlap,
            separators=separators or ["\n\n", "\n", " ", ""]
        )
        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_size, 
            chunk_overlap=child_overlap,
            separators=separators or ["\n\n", "\n", " ", ""]
        )
        
        parents = parent_splitter.split_text(text)
        chunks = []
        
        for i, parent_text in enumerate(parents):
            children = child_splitter.split_text(parent_text)
            for child_text in children:
                chunks.append({
                    "content": child_text,
                    "metadata": {
                        "parent_id": i,
                        "parent_content": parent_text
                    }
                })
        return chunks

    def chunk_context_aware(self, text: str, headers_to_split_on: List[tuple] = None) -> List[str]:
        # Default headers if none provided
        if not headers_to_split_on:
            headers_to_split_on = [
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
            ]
        
        markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        docs = markdown_splitter.split_text(text)
        return [doc.page_content for doc in docs]

    def chunk_semantic(self, text: str, buffer_size: int = 1, breakpoint_threshold_type: str = "percentile", breakpoint_threshold_amount: float = 95.0) -> List[str]:
        embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)
        semantic_splitter = SemanticChunker(
            embeddings,
            buffer_size=buffer_size,
            breakpoint_threshold_type=breakpoint_threshold_type,
            breakpoint_threshold_amount=breakpoint_threshold_amount
        )
        docs = semantic_splitter.create_documents([text])
        return [doc.page_content for doc in docs]

    def split_into_sections(self, text: str, section_size: int = 6000, overlap: int = 500) -> List[str]:
        """
        Split text into larger sections for graph extraction.
        These sections provide broader context for entity/relation extraction.
        
        Args:
            section_size: Size of each section in characters (default: 6000, ~1500 tokens)
            overlap: Overlap between sections to preserve cross-boundary context
        
        Returns:
            List of section texts
        """
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=section_size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        return splitter.split_text(text)

    def chunk_by_size_with_offset(self, text: str, chunk_size: int = 1000, overlap: int = 200, separators: List[str] = None) -> List[Dict]:
        """
        청크 생성 시 원문 오프셋을 포함하여 반환.
        
        Args:
            text: 원본 텍스트
            chunk_size: 청크 크기
            overlap: 오버랩 크기
            separators: 분할 구분자
        
        Returns:
            List of {"content": str, "start_offset": int, "end_offset": int}
        """
        # Use langchain splitter to get chunks
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            separators=separators or ["\n\n", "\n", " ", ""]
        )
        chunk_texts = splitter.split_text(text)
        
        # Calculate offsets by finding each chunk in the original text
        chunks_with_offset = []
        search_start = 0
        
        for chunk_text in chunk_texts:
            # Find the chunk in the original text starting from last position
            start_idx = text.find(chunk_text, search_start)
            if start_idx == -1:
                # Fallback: search from beginning (shouldn't happen normally)
                start_idx = text.find(chunk_text)
            
            if start_idx != -1:
                end_idx = start_idx + len(chunk_text)
                chunks_with_offset.append({
                    "content": chunk_text,
                    "start_offset": start_idx,
                    "end_offset": end_idx
                })
                # Move search start, accounting for overlap
                search_start = max(search_start, start_idx + 1)
            else:
                # If not found, use approximate position
                chunks_with_offset.append({
                    "content": chunk_text,
                    "start_offset": search_start,
                    "end_offset": search_start + len(chunk_text)
                })
                search_start += len(chunk_text) - overlap
        
        return chunks_with_offset

    def split_into_sections_with_offset(self, text: str, section_size: int = 6000, overlap: int = 500) -> List[Dict]:
        """
        섹션 분할 시 원문 오프셋을 포함하여 반환.
        
        Args:
            text: 원본 텍스트
            section_size: 섹션 크기
            overlap: 오버랩 크기
        
        Returns:
            List of {"text": str, "start_offset": int, "end_offset": int}
        """
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=section_size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        section_texts = splitter.split_text(text)
        
        sections_with_offset = []
        search_start = 0
        
        for section_text in section_texts:
            start_idx = text.find(section_text, search_start)
            if start_idx == -1:
                start_idx = text.find(section_text)
            
            if start_idx != -1:
                end_idx = start_idx + len(section_text)
                sections_with_offset.append({
                    "text": section_text,
                    "start_offset": start_idx,
                    "end_offset": end_idx
                })
                search_start = max(search_start, start_idx + 1)
            else:
                sections_with_offset.append({
                    "text": section_text,
                    "start_offset": search_start,
                    "end_offset": search_start + len(section_text)
                })
                search_start += len(section_text) - overlap
        
        return sections_with_offset

chunking_service = ChunkingService()
