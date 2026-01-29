"""
Ingest Service Configuration
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Service settings
    SERVICE_NAME: str = "ingest-service"
    DEBUG: bool = False
    
    # Redis settings
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # OpenAI settings
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    
    # Milvus settings
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    
    # Neo4j settings
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"
    
    # Fuseki settings
    FUSEKI_URL: str = "http://localhost:3030"
    
    # Shared storage
    # Shared storage for file exchange
    SHARED_STORAGE_PATH: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "uploads")
    
    # Main backend URL (for callbacks)
    MAIN_BACKEND_URL: str = "http://localhost:8000"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
