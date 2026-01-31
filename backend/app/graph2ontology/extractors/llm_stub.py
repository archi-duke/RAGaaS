"""LLM 스텁 추출기"""

import re
from typing import Union, Optional,  Optional, Union

from app.graph2ontology.extractors.base import BaseExtractor
from app.graph2ontology.models.candidate import (
    CandidateExtractionResult,
    ClassCandidate,
    PropertyCandidate,
    RelationCandidate,
    InstanceCandidate,
    Triple,
)
from app.graph2ontology.models.chunk import OEChunk


class LLMStubExtractor(BaseExtractor):
    """LLM 스텁 추출기: 실제 LLM 대신 규칙 기반으로 후보 추출
    
    실제 구현 시 이 클래스를 상속하거나 교체하여 LLM API 연결
    """
    
    def __init__(
        self, 
        confidence_threshold: float = 0.5,
        llm_endpoint: Optional[str] = None,
        llm_model: str = "stub",
    ):
        """
        Args:
            confidence_threshold: 후보 필터링 confidence 임계값
            llm_endpoint: LLM API 엔드포인트 (스텁에서는 미사용)
            llm_model: LLM 모델명
        """
        super().__init__(confidence_threshold)
        self.llm_endpoint = llm_endpoint
        self.llm_model = llm_model
        
        # 한국어 패턴 (스텁용)
        self._class_patterns = [
            r"(.{2,10})은(?:는)?\s+(.{2,15})(?:이다|이라고 한다|를 말한다)",
            r"(.{2,10})란\s+(.{5,30})(?:을|를)?\s*(?:말한다|의미한다)",
        ]
        self._relation_patterns = [
            r"(.{2,15})(?:은|는|이|가)\s+(.{2,15})(?:을|를|에게|와|과)\s+(.{2,10})(?:한다|했다|하였다)",
            r"(.{2,15})의\s+(.{2,10})(?:은|는)\s+(.{2,15})",
        ]
        self._property_patterns = [
            r"(.{2,15})의\s+(.{2,10})(?:은|는|이)\s+(.{2,20})(?:이다|이었다)",
        ]
    
    def extract(
        self, 
        chunk: OEChunk,
        run_id: str,
    ) -> CandidateExtractionResult:
        """청크에서 온톨로지 후보 추출 (스텁: 규칙 기반)"""
        
        result = CandidateExtractionResult(
            doc_id=chunk.doc_id,
            doc_ver=chunk.doc_ver,
            run_id=run_id,
        )
        
        text = chunk.text
        
        # 클래스 추출 (스텁)
        for pattern in self._class_patterns:
            for match in re.finditer(pattern, text):
                label = match.group(1).strip()
                description = match.group(2).strip()
                result.classes.append(ClassCandidate(
                    label=label,
                    description=description,
                    confidence=0.7,  # 스텁 고정값
                    source_text=match.group(0),
                    source_chunk_id=chunk.chunk_id,
                ))
        
        # 관계 추출 (스텁)
        for pattern in self._relation_patterns:
            for match in re.finditer(pattern, text):
                subject = match.group(1).strip()
                obj = match.group(2).strip() if len(match.groups()) >= 3 else ""
                predicate = match.group(3).strip() if len(match.groups()) >= 3 else match.group(2).strip()
                
                result.relations.append(RelationCandidate(
                    label=predicate,
                    domain_class=subject,
                    range_class=obj,
                    confidence=0.6,
                    source_text=match.group(0),
                    source_chunk_id=chunk.chunk_id,
                ))
                
                # 트리플도 생성
                result.triples.append(Triple(
                    subject=subject,
                    predicate=predicate,
                    object=obj,
                    confidence=0.6,
                    source_text=match.group(0),
                    source_chunk_id=chunk.chunk_id,
                ))
        
        # 속성 추출 (스텁)
        for pattern in self._property_patterns:
            for match in re.finditer(pattern, text):
                domain = match.group(1).strip()
                prop_name = match.group(2).strip()
                value = match.group(3).strip()
                
                result.properties.append(PropertyCandidate(
                    label=prop_name,
                    domain_class=domain,
                    confidence=0.6,
                    source_text=match.group(0),
                    source_chunk_id=chunk.chunk_id,
                ))
                
                # 트리플도 생성
                result.triples.append(Triple(
                    subject=domain,
                    predicate=prop_name,
                    object=value,
                    object_is_literal=True,
                    confidence=0.6,
                    source_text=match.group(0),
                    source_chunk_id=chunk.chunk_id,
                ))
        
        return result
    
    def call_llm(self, prompt: str) -> dict:
        """LLM API 호출 (스텁: 빈 결과 반환)
        
        실제 구현 시 이 메서드를 오버라이드하여 LLM API 연결
        
        Expected JSON Schema:
        {
            "classes": [{"label": str, "description": str, "parent_class": str|null}],
            "properties": [{"label": str, "domain": str, "range_type": str}],
            "relations": [{"label": str, "domain": str, "range": str}],
            "instances": [{"label": str, "class": str, "properties": {}}],
            "triples": [{"subject": str, "predicate": str, "object": str, "is_literal": bool}]
        }
        """
        # 스텁: 빈 결과
        return {
            "classes": [],
            "properties": [],
            "relations": [],
            "instances": [],
            "triples": [],
        }
