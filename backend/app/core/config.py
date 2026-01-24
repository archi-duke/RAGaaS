from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    PROJECT_NAME: str = "RAG Management System"
    API_V1_STR: str = "/api"
    
    # Database
    MONGO_URI: str = "mongodb://root:example@mongo:27017"
    MONGO_DB: str = "ragaas"
    
    # Milvus
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: str = "19530"

    # Fuseki
    FUSEKI_URL: str = "http://localhost:3030"

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"
    
    
    # OpenAI
    OPENAI_API_KEY: str = ""

    # Ingest Service (LlamaIndex based)
    INGEST_SERVICE_URL: str = "http://ingest-service:8001"
    # Shared storage for file exchange
    SHARED_STORAGE_PATH: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "uploads")
    


    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
