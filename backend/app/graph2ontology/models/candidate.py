"""온톨로지 후보 모델"""

from enum import Enum
from typing import Union, Optional,  Optional, Union
from pydantic import BaseModel, Field


class CandidateType(str, Enum):
    """후보 유형"""
    CLASS = "class"
    PROPERTY = "property"
    RELATION = "relation"
    INSTANCE = "instance"


class OntologyCandidate(BaseModel):
    """온톨로지 후보 기본 모델"""
    candidate_type: CandidateType
    label: str = Field(..., description="라벨 (한국어)")
    label_en: Optional[str] = Field(default=None, description="영어 라벨 (IRI 생성용)")
    uri: Optional[str] = Field(default=None, description="생성된 IRI")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="신뢰도")
    source_text: str = Field(..., description="추출 근거 텍스트")
    source_chunk_id: str = Field(..., description="출처 청크 ID")


class ClassCandidate(OntologyCandidate):
    """클래스 후보"""
    candidate_type: CandidateType = CandidateType.CLASS
    parent_class: Optional[str] = Field(default=None, description="상위 클래스 라벨")
    description: Optional[str] = Field(default=None, description="클래스 설명")


class PropertyCandidate(OntologyCandidate):
    """데이터 속성 후보"""
    candidate_type: CandidateType = CandidateType.PROPERTY
    domain_class: Optional[str] = Field(default=None, description="도메인 클래스 라벨")
    range_type: str = Field(default="xsd:string", description="값 타입")
    description: Optional[str] = Field(default=None, description="속성 설명")


class RelationCandidate(OntologyCandidate):
    """객체 속성(관계) 후보"""
    candidate_type: CandidateType = CandidateType.RELATION
    domain_class: Optional[str] = Field(default=None, description="도메인 클래스 라벨")
    range_class: Optional[str] = Field(default=None, description="레인지 클래스 라벨")
    inverse_label: Optional[str] = Field(default=None, description="역관계 라벨")
    description: Optional[str] = Field(default=None, description="관계 설명")


class InstanceCandidate(OntologyCandidate):
    """개체(인스턴스) 후보"""
    candidate_type: CandidateType = CandidateType.INSTANCE
    class_label: str = Field(..., description="소속 클래스 라벨")
    properties: dict[str, str] = Field(default_factory=dict, description="속성값 {속성라벨: 값}")
    relations: list[dict[str, str]] = Field(
        default_factory=list, 
        description="관계 [{relation: 라벨, target: 대상라벨}]"
    )


class Triple(BaseModel):
    """트리플 (S, P, O)"""
    subject: str = Field(..., description="주어 IRI 또는 라벨")
    predicate: str = Field(..., description="술어 IRI 또는 라벨")
    object: str = Field(..., description="목적어 IRI, 라벨 또는 리터럴")
    object_is_literal: bool = Field(default=False, description="목적어가 리터럴인지 여부")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_text: str = Field(default="", description="추출 근거 텍스트")
    source_chunk_id: str = Field(default="", description="출처 청크 ID")


class CandidateExtractionResult(BaseModel):
    """후보 추출 결과"""
    doc_id: str = Field(..., description="문서 ID")
    doc_ver: str = Field(default="v1", description="문서 버전")
    run_id: str = Field(..., description="실행 ID")
    
    classes: list[ClassCandidate] = Field(default_factory=list)
    properties: list[PropertyCandidate] = Field(default_factory=list)
    relations: list[RelationCandidate] = Field(default_factory=list)
    instances: list[InstanceCandidate] = Field(default_factory=list)
    triples: list[Triple] = Field(default_factory=list, description="직접 추출된 트리플")
    
    @property
    def total_candidates(self) -> int:
        return len(self.classes) + len(self.properties) + len(self.relations) + len(self.instances)
    
    @property
    def total_triples(self) -> int:
        return len(self.triples)
