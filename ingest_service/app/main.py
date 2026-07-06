"""
Ingest Service - FastAPI Main Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.ingest import router as ingest_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    print(f"[IngestService] {settings.SERVICE_NAME} starting up...")
    yield
    # Shutdown
    print(f"[IngestService] {settings.SERVICE_NAME} shutting down...")


app = FastAPI(
    title="Ingest Service",
    description="LlamaIndex 기반 문서 인제스션 서비스",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 플랫폼 신원 확정 미들웨어 (계약 05 §1) — introspect / X-Service-Token / dev 폴백
from app.core.platform_auth import platform_auth_middleware
app.middleware("http")(platform_auth_middleware)

# Routers
app.include_router(ingest_router, prefix="/api/v2", tags=["ingest"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": settings.SERVICE_NAME}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.SERVICE_NAME,
        "version": "1.0.0",
        "docs": "/docs",
    }
