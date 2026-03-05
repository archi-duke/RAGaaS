import httpx
from openai import AsyncOpenAI
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase


# TODO: REMOVE DEBUG LOGGING AFTER DEBUGGING
async def _log_request(request: httpx.Request):
    """Debug log for outgoing requests"""
    print(f"\n{'='*20} [DEBUG] HTTP REQUEST START {'='*20}")
    print(f"Method: {request.method}")
    print(f"URL: {request.url}")
    print(f"Headers: {dict(request.headers)}")
    try:
        content = request.read().decode("utf-8")
        print(f"Body: {content[:2000]}{'...' if len(content) > 2000 else ''}")
    except Exception:
        print("Body: [binary or un-decodable]")
    print(f"{'='*20} [DEBUG] HTTP REQUEST END {'='*20}\n")

async def _log_response(response: httpx.Response):
    """Debug log for incoming responses"""
    print(f"[DEBUG] HTTP RESPONSE: {response.status_code} {response.url}\n")
# ------------------------------


class EmbeddingService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        base_url: Optional[str] = None,
        extra_headers: Optional[dict] = None,
        embedding_request_format: str = "openai",  # "openai" | "minimal"
    ):
        self.model = model
        self.base_url = (base_url or "").rstrip("/")
        self.extra_headers = extra_headers or {}
        self.embedding_request_format = embedding_request_format or "openai"

        if self.embedding_request_format == "minimal":
            self.client = None
        else:
            if not api_key:
                self.client = None
                return
            client_kwargs: dict = {"api_key": api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            if self.extra_headers:
                client_kwargs["default_headers"] = self.extra_headers
            
            # Using custom http_client to log requests
            client_kwargs["http_client"] = httpx.AsyncClient(
                event_hooks={'request': [_log_request], 'response': [_log_response]}
            )
            self.client = AsyncOpenAI(**client_kwargs)

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        if self.embedding_request_format == "minimal":
            return await self._get_embeddings_minimal(texts)
        if self.client is None:
            raise ValueError("Embedding model API key is not configured.")
        response = await self.client.embeddings.create(
            input=texts,
            model=self.model,
        )
        return [data.embedding for data in response.data]

    async def _get_embeddings_minimal(self, texts: List[str]) -> List[List[float]]:
        """
        Minimal 포맷: curl 예제와 동일
        - POST {base_url}/v1/embeddings
        - Headers: Content-Type + extra_headers (x-dep-ticket 등)
        - Body: {"input": "text"} 또는 {"input": ["a","b"]}
        """
        url = self.base_url
        headers = {"Content-Type": "application/json", **self.extra_headers}
        payload: dict = {"input": texts[0] if len(texts) == 1 else texts}

        async with httpx.AsyncClient(
            timeout=60.0, 
            event_hooks={'request': [_log_request], 'response': [_log_response]}
        ) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # OpenAI 호환 응답: {"data": [{"embedding": [...]}, ...]}
        items = data.get("data", [])
        return [item["embedding"] for item in items]


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
        embedding_request_format=resolved.get("embedding_request_format", "openai"),
    )
