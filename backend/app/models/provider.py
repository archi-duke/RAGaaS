from typing import Optional, List, Dict
from datetime import datetime
from beanie import Document
from pydantic import BaseModel, Field
import uuid


# ── Built-in 프로바이더 API Key + 캐시된 모델 목록 ─────────────────────────────────

class BuiltinProviderConfig(Document):
    """
    OpenAI, Anthropic, Google 등 Built-in 프로바이더의 API Key 및 캐시된 모델 목록.
    - encrypted_key: Fernet 암호화된 API Key
    - cached_models_llm, cached_models_embedding: API 조회 결과 캐시
    - cached_at: 마지막 조회 시각
    """
    provider_id: str  # "openai" | "anthropic" | "google"
    encrypted_key: str = ""
    cached_models_llm: List[str] = []
    cached_models_embedding: List[str] = []
    cached_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "builtin_provider_configs"


class BuiltinProviderKeyUpdate(BaseModel):
    api_key: str


# ── Custom 프로바이더 ─────────────────────────────────────────────────────────────

class CustomProvider(Document):
    """사용자 정의 LLM/Embedding 프로바이더."""
    provider_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str                          # 표시 이름 (예: "My Company LLM")
    base_url: str                      # API Base URL (예: "https://my-api.example.com/v1")
    encrypted_key: str                 # Fernet 암호화된 API Key
    model_list: List[str] = []         # 사용 가능한 모델 목록 (사용자 입력)
    provider_type: str = "both"        # "llm" | "embedding" | "both"
    extra_headers: Dict[str, str] = {}  # 추가 HTTP 헤더 (예: {"x-dep-ticket": "credential:TICKET"})
    embedding_request_format: str = "minimal"  # "openai" | "minimal" - minimal: input만, extra_headers로 인증
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "custom_providers"


# ── API 요청/응답 스키마 ──────────────────────────────────────────────────────

class CustomProviderCreate(BaseModel):
    name: str
    base_url: str
    api_key: str                       # plaintext — 백엔드에서 즉시 암호화
    model_list: List[str] = []
    provider_type: str = "both"
    extra_headers: Optional[Dict[str, str]] = None  # 추가 HTTP 헤더
    embedding_request_format: str = "minimal"  # "openai" | "minimal"


class CustomProviderResponse(BaseModel):
    """프론트엔드에 반환되는 응답 — api_key/encrypted_key 포함하지 않음."""
    provider_id: str
    name: str
    base_url: str
    model_list: List[str]
    provider_type: str
    has_key: bool = True               # 키가 등록됐는지 여부만 노출
    extra_headers: Optional[Dict[str, str]] = None  # 추가 HTTP 헤더
    embedding_request_format: str = "minimal"
    created_at: datetime
