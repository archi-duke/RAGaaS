from openai import AsyncOpenAI
from app.core.config import settings
from typing import List

class EmbeddingService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        # OpenAI embedding model
        response = await self.client.embeddings.create(
            input=texts,
            model="text-embedding-3-small"
        )
        return [data.embedding for data in response.data]

embedding_service = EmbeddingService()
