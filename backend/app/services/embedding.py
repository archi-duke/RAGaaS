from openai import AsyncOpenAI
from app.core.config import settings
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase


class EmbeddingService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        base_url: Optional[str] = None,
        extra_headers: Optional[dict] = None,
    ):
        self.model = model
        client_kwargs: dict = {"api_key": api_key or settings.OPENAI_API_KEY}
        if base_url:
            client_kwargs["base_url"] = base_url
        if extra_headers:
            client_kwargs["default_headers"] = extra_headers
        self.client = AsyncOpenAI(**client_kwargs)

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        response = await self.client.embeddings.create(
            input=texts,
            model=self.model,
        )
        return [data.embedding for data in response.data]


# 기본 싱글톤 (OPENAI_API_KEY env 기반) — 레거시/fallback 용도
embedding_service = EmbeddingService()


async def get_embedding_service(kb: "KnowledgeBase") -> EmbeddingService:
    """KB 설정을 기반으로 EmbeddingService 인스턴스를 반환한다."""
    from app.core.models_resolver import resolve_model_config

    resolved = await resolve_model_config({
        "model": kb.embedding_model,
        "provider": kb.embedding_provider,
        "provider_id": kb.embedding_provider_id,
    })
    return EmbeddingService(
        api_key=resolved["api_key"],
        model=resolved["model"],
        base_url=resolved.get("base_url"),
        extra_headers=resolved.get("extra_headers"),
    )
