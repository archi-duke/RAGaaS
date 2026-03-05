"""
삼성DS API 게이트웨이 프록시 설정
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 프록시 서버 포트
    PORT: int = 8010

    # ── OpenAI 공식 API (최종 타겟) ──────────────────────────────
    EMBEDDING_TARGET_URL: str = "https://api.openai.com/v1/embeddings"
    LLM_TARGET_URL: str = "https://api.openai.com/v1/chat/completions"
    
    # 공식 OpenAI API Key (업스트림 호출용)
    OPENAI_API_KEY: str = ""

    # 업스트림 요청 타임아웃 (초)
    REQUEST_TIMEOUT: float = 120.0

    # SSL 검증 여부
    SSL_VERIFY: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
