from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(title="RAG Management System API")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    import json
    print(f"Validation error: {exc}")
    try:
        body = await request.body()
        print(f"Request body: {body.decode()}")
    except Exception:
        pass
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "body": str(exc)})

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

@app.get("/")
async def root():
    return {"message": "Welcome to RAG Management System API"}

from app.api import knowledge_base, document, retrieval
from app.core.database import init_db # engine, Base removed
from app.core.milvus import connect_milvus
from app.core.websocket_manager import manager
from fastapi import WebSocket, WebSocketDisconnect

# 플랫폼 계약 05 §4 — 백엔드 API 베이스 경로는 /api/v2 표준
# (게이트웨이가 /ragaas 프리픽스를 strip 하고 /api/v2/... 로 전달 — 경로 v2)
app.include_router(knowledge_base.router, prefix="/api/v2/knowledge-bases", tags=["Knowledge Base"])
app.include_router(document.router, prefix="/api/v2/knowledge-bases", tags=["Documents"])
app.include_router(retrieval.router, prefix="/api/v2/knowledge-bases", tags=["Retrieval"])

from app.api import graph_viewer
app.include_router(graph_viewer.router, prefix="/api/v2/graph", tags=["Graph Viewer"])

from app.api import providers
app.include_router(providers.router, prefix="/api/v2", tags=["providers"])

@app.websocket("/api/v2/ws/{kb_id}")
async def websocket_endpoint(websocket: WebSocket, kb_id: str):
    await manager.connect(websocket, kb_id)
    try:
        while True:
            # Keep connection alive and wait for messages (if any from client)
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, kb_id)

@app.on_event("startup")
async def startup():
    import sys
    print("[Startup] RAGaaS Backend Starting...", file=sys.stdout, flush=True)

    # Initialize MongoDB (Beanie)
    await init_db()
    print("[Startup] MongoDB Connected & Beanie Initialized.", file=sys.stdout, flush=True)

    # Connect to Milvus
    try:
        connect_milvus()
        print("[Startup] Milvus Connected.", file=sys.stdout, flush=True)
    except Exception as e:
        print(f"[Startup] Failed to connect to Milvus: {e}", file=sys.stdout, flush=True)
    
    # Seed improved extraction prompt if not exists
    try:
        from app.models.prompt import PromptTemplate
        import os
        
        prompt_path = os.path.join(os.path.dirname(__file__), "data", "prompts", "graph_extraction_prompt.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                file_content = f.read()
            
            existing = await PromptTemplate.find_one(PromptTemplate.name == "graph_extraction_prompt")
            if not existing:
                # Insert new
                new_prompt = PromptTemplate(
                    name="graph_extraction_prompt",
                    content=file_content,
                    type="extraction"
                )
                await new_prompt.insert()
                print(f"[Startup] Seeded extraction prompt ({len(file_content)} chars)", file=sys.stdout, flush=True)
            elif existing.content != file_content:
                # Update if file changed (e.g. placeholder fix)
                existing.content = file_content
                await existing.save()
                print(f"[Startup] Updated extraction prompt ({len(file_content)} chars)", file=sys.stdout, flush=True)
            else:
                print("[Startup] Extraction prompt up-to-date.", file=sys.stdout, flush=True)
        else:
            print(f"[Startup] Prompt file not found: {prompt_path}", file=sys.stdout, flush=True)
    except Exception as e:
        print(f"[Startup] Failed to seed extraction prompt: {e}", file=sys.stdout, flush=True)
        
    # Recovery Task: Resume incomplete deletions (Temporarily disabled for Mongo migration)
    # try:
    #     # TODO: Re-implement using Beanie
    #     pass
    # except Exception as e:
    #     print(f"[Recovery] Failed to resume deletion tasks: {e}", file=sys.stdout, flush=True)



