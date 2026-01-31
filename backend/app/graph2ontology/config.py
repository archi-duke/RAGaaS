"""설정 로드 및 검증 모듈"""

from pathlib import Path
from typing import Union, Optional,  Optional, Union
import yaml
from pydantic import BaseModel, Field


class ChunkingConfig(BaseModel):
    """청킹 설정"""
    # OE-Chunk 설정 (온톨로지 추출용)
    oe_chunk_size: int = Field(default=2000, description="OE-Chunk 크기 (문자)")
    oe_chunk_overlap: int = Field(default=500, description="OE-Chunk 오버랩 (문자)")
    oe_section_aware: bool = Field(default=True, description="섹션 인식 여부")
    
    # RAG-Chunk 설정 (검색용)
    rag_chunk_size: int = Field(default=500, description="RAG-Chunk 크기 (문자)")
    rag_chunk_overlap: int = Field(default=100, description="RAG-Chunk 오버랩 (문자)")


class ExtractionConfig(BaseModel):
    """추출 설정"""
    llm_endpoint: Optional[str] = Field(default=None, description="LLM API 엔드포인트")
    llm_model: str = Field(default="stub", description="LLM 모델 이름")
    confidence_threshold: float = Field(default=0.5, description="후보 필터링 confidence 임계값")
    max_candidates_per_chunk: int = Field(default=20, description="청크당 최대 후보 수")
    examples_path: Optional[str] = Field(default=None, description="Few-shot 예제 파일 경로")


class OntologyConfig(BaseModel):
    """온톨로지 설정"""
    base_uri: str = Field(default="http://example.org/onto/", description="온톨로지 베이스 URI")
    base_graph_uri: str = Field(default="urn:onto:base", description="베이스 그래프 URI")
    evidence_graph_prefix: str = Field(default="urn:ragchunk:", description="Evidence 그래프 URI 접두사")


class StorageConfig(BaseModel):
    """스토리지 설정"""
    # Fuseki
    fuseki_endpoint: Optional[str] = Field(default=None, description="Fuseki SPARQL 엔드포인트")
    fuseki_dataset: str = Field(default="ds", description="Fuseki 데이터셋 이름")
    
    # Milvus
    milvus_host: str = Field(default="localhost", description="Milvus 호스트")
    milvus_port: int = Field(default=19530, description="Milvus 포트")
    milvus_collection: str = Field(default="doc2onto_chunks", description="Milvus 컬렉션 이름")


class Config(BaseModel):
    """전체 설정"""
    version: str = Field(default="1.0", description="설정 버전")
    run_id: Optional[str] = Field(default=None, description="실행 ID (자동 생성)")
    
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    ontology: OntologyConfig = Field(default_factory=OntologyConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def load_config(config_path: Union[str, Path]) -> Config:
    """YAML 설정 파일 로드
    
    Args:
        config_path: 설정 파일 경로
        
    Returns:
        Config 객체
    """
    config_path = Path(config_path)
    
    if not config_path.exists():
        # 기본 설정 반환
        return Config()
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    return Config(**data)


def save_config(config: Config, config_path: Union[str, Path]) -> None:
    """설정을 YAML 파일로 저장
    
    Args:
        config: Config 객체
        config_path: 저장할 파일 경로
    """
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config.model_dump(), f, allow_unicode=True, default_flow_style=False)
