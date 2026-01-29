from datetime import datetime
from typing import Optional, List
from beanie import Document
from pydantic import Field

class PromptTemplate(Document):
    name: str = Field(..., description="Unique name of the prompt (e.g., 'rerank_llm_prompt')")
    content: str = Field(..., description="The actual prompt content")
    version: str = Field(default="1.0", description="Version string")
    type: str = Field(default="general", description="Type of prompt (e.g., 'system', 'user', 'extraction')")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "prompts"
        indexes = [
            "name",
            "type"
        ]
