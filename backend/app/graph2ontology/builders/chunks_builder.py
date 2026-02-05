"""chunks.jsonl 생성 모듈"""

import json
from pathlib import Path
from typing import Union, Optional,  Generator

from app.graph2ontology.models.chunk import RAGChunk, ChunkBatch


class ChunksBuilder:
    """Milvus 적재용 chunks.jsonl 생성기"""
    
    def __init__(self):
        self.chunks: list[RAGChunk] = []
    
    def add_chunk(self, chunk: RAGChunk) -> None:
        """청크 추가"""
        self.chunks.append(chunk)
    
    def add_batch(self, batch: ChunkBatch) -> None:
        """청크 배치 추가"""
        self.chunks.extend(batch.rag_chunks)
    
    def clear(self) -> None:
        """청크 목록 초기화"""
        self.chunks.clear()
    
    def iter_records(self) -> Generator[dict, None, None]:
        """Milvus 레코드 순회"""
        for chunk in self.chunks:
            yield chunk.to_milvus_record()
    
    def serialize(self, output_path: Union[str, Path]) -> int:
        """chunks.jsonl로 저장
        
        Args:
            output_path: 출력 파일 경로
            
        Returns:
            저장된 청크 수
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        count = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for record in self.iter_records():
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
        
        return count
    
    @classmethod
    def from_jsonl(cls, input_path: Union[str, Path]) -> "ChunksBuilder":
        """JSONL 파일에서 로드
        
        Args:
            input_path: 입력 파일 경로
            
        Returns:
            ChunksBuilder 객체
        """
        builder = cls()
        input_path = Path(input_path)
        
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    # 레코드를 RAGChunk로 변환
                    chunk = RAGChunk(
                        doc_id=data["doc_id"],
                        doc_ver=data["doc_ver"],
                        chunk_idx=data["chunk_idx"],
                        text=data["text"],
                        section_path=data.get("section_path") or None,
                        page=data.get("page") if data.get("page", -1) >= 0 else None,
                        start_offset=data.get("start_offset") if data.get("start_offset", -1) >= 0 else None,
                        end_offset=data.get("end_offset") if data.get("end_offset", -1) >= 0 else None,
                    )
                    builder.add_chunk(chunk)
        
        return builder
    
    @property
    def total_chunks(self) -> int:
        return len(self.chunks)
