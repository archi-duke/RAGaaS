"""KB 용어 사전 항목 (docs/design/agent/design-kb-lexicon.md §3)."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class KbLexiconEntry(Document):
    kb_id: str
    label: str                      # 그래프 라벨 (concept_only 면 상위 개념 말)
    norm: str                       # entity_linking._compact(label)
    variants: List[str] = Field(default_factory=list)   # 정규화가 같은 다른 라벨 (Clean Architecture / clean-architecture)
    ko: List[str] = Field(default_factory=list)
    en: List[str] = Field(default_factory=list)
    syn: List[str] = Field(default_factory=list)
    broader: List[Dict[str, Any]] = Field(default_factory=list)   # [{"label", "status": proposed|approved|rejected}]
    concept_only: bool = False
    skip: bool = False
    source: str = "llm"             # llm | user — user 항목은 재생성 때 덮어쓰지 않음
    model: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "kb_lexicon"
        indexes = [IndexModel([("kb_id", ASCENDING), ("norm", ASCENDING)], unique=True)]
