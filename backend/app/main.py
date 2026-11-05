from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db
from app.api import knowledge_base, document, retrieval, graph_viewer, websocket_endpoint
from app.api import providers

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS Configuration
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    await init_db()

# Include Routers
app.include_router(knowledge_base.router, prefix="/api/v2/knowledge-bases", tags=["knowledge_bases"])
app.include_router(document.router, prefix="/api/v2/knowledge-bases", tags=["documents"])
app.include_router(retrieval.router, prefix="/api/v2/knowledge-bases", tags=["retrieval"])
app.include_router(graph_viewer.router, prefix="/api/v2/graph", tags=["graph"])
app.include_router(websocket_endpoint.router, prefix="/api", tags=["websocket"])
app.include_router(providers.router, prefix="/api", tags=["providers"])

@app.get("/api/v2/health")
async def health_check():
    return {"status": "ok"}
