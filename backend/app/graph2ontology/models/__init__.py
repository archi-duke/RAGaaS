"""Doc2Onto Models - Pydantic 데이터 모델"""

from app.graph2ontology.models.candidate import (
    OntologyCandidate,
    ClassCandidate,
    PropertyCandidate,
    RelationCandidate,
    InstanceCandidate,
    CandidateExtractionResult,
)
from app.graph2ontology.models.chunk import (
    ChunkType,
    BaseChunk,
    OEChunk,
    RAGChunk,
    ChunkBatch,
)
from app.graph2ontology.models.entity import (
    EntityEntry,
    EntityRegistry,
)

__all__ = [
    # Candidates
    "OntologyCandidate",
    "ClassCandidate",
    "PropertyCandidate",
    "RelationCandidate",
    "InstanceCandidate",
    "CandidateExtractionResult",
    # Chunks
    "ChunkType",
    "BaseChunk",
    "OEChunk",
    "RAGChunk",
    "ChunkBatch",
    # Entities
    "EntityEntry",
    "EntityRegistry",
]
