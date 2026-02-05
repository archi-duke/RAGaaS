"""추출기 기본 인터페이스"""

from abc import ABC, abstractmethod
from typing import Union, Optional,  Optional, Union

from app.graph2ontology.models.candidate import CandidateExtractionResult
from app.graph2ontology.models.chunk import OEChunk


class BaseExtractor(ABC):
    """후보 추출기 기본 클래스"""
    
    def __init__(self, confidence_threshold: float = 0.5):
        """
        Args:
            confidence_threshold: 후보 필터링 confidence 임계값
        """
        self.confidence_threshold = confidence_threshold
    
    @abstractmethod
    def extract(
        self, 
        chunk: OEChunk,
        run_id: str,
    ) -> CandidateExtractionResult:
        """청크에서 온톨로지 후보 추출
        
        Args:
            chunk: OE-Chunk
            run_id: 실행 ID
            
        Returns:
            추출 결과
        """
        pass
    
    def extract_batch(
        self,
        chunks: list[OEChunk],
        run_id: str,
    ) -> list[CandidateExtractionResult]:
        """여러 청크에서 배치 추출
        
        Args:
            chunks: OE-Chunk 리스트
            run_id: 실행 ID
            
        Returns:
            추출 결과 리스트
        """
        return [self.extract(chunk, run_id) for chunk in chunks]
    
    def filter_by_confidence(
        self, 
        result: CandidateExtractionResult
    ) -> CandidateExtractionResult:
        """confidence 임계값으로 필터링"""
        return CandidateExtractionResult(
            doc_id=result.doc_id,
            doc_ver=result.doc_ver,
            run_id=result.run_id,
            classes=[c for c in result.classes if c.confidence >= self.confidence_threshold],
            properties=[p for p in result.properties if p.confidence >= self.confidence_threshold],
            relations=[r for r in result.relations if r.confidence >= self.confidence_threshold],
            instances=[i for i in result.instances if i.confidence >= self.confidence_threshold],
            triples=[t for t in result.triples if t.confidence >= self.confidence_threshold],
        )
