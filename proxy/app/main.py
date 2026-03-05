"""
Samsung DS API Gateway 프록시 서비스
- POST /v1/embeddings       → Samsung DS 임베딩 API 중계
- POST /v1/chat/completions → Samsung DS LLM API 중계
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import embedding, chat
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Samsung DS API Proxy",
    description="OpenAI-compatible API proxy for Samsung DS embedding & LLM gateway",
    version="1.0.0",
)

# CORS (사내 환경이면 다 허용해도 무방)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(embedding.router, tags=["Embedding"])
app.include_router(chat.router, tags=["LLM"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "embedding_target": settings.EMBEDDING_TARGET_URL,
        "llm_target": settings.LLM_TARGET_URL,
    }
