"""KB 스키마 매핑 규칙 / 제안 (docs/design/schema/design-schema-mismatch.md §5)."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie import Document
from pydantic import Field


class SchemaMappingRule(Document):
    """KB 단위 매핑 규칙. 인제스트 시 구조화 문서 트리에 적용되고, 검색 시 동치·별칭으로 쓰인다.

    rule_type:
      key    — source_path → target_path (레코드 루트 기준 dot 경로, 이름 변경·중첩 이동)
      value  — source_value → target_value (값 전체 일치만, scope_paths 기본 ["*"] = KB 전체)
      ignore — pair 두 경로(또는 값)는 다른 필드로 구별 유지 (재제안·검색 OR 억제)
    """
    kb_id: str
    rule_type: str
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    source_value: Optional[str] = None
    target_value: Optional[str] = None
    scope_paths: List[str] = Field(default_factory=lambda: ["*"])
    pair: Optional[List[str]] = None
    origin: str = "user"          # user | auto | proposal:<id>
    status: str = "active"        # active | disabled
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "schema_mapping_rules"


class SchemaMappingProposal(Document):
    """감지기가 만든 매핑 제안. 수락 → 규칙, 거절 → ignore 규칙."""
    kb_id: str
    kind: str                     # key | value
    source: str
    target: str
    basis: str                    # normalized | nesting | lexicon | llm
    evidence: Dict[str, Any] = Field(default_factory=dict)
    doc_ids: List[str] = Field(default_factory=list)
    status: str = "pending"       # pending | accepted | rejected | superseded
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "schema_mapping_proposals"
