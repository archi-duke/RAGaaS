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

@app.get("/")
async def root():
    return {"message": "Welcome to RAG Management System API"}

from app.api import knowledge_base, document, retrieval
from app.core.database import engine, Base
from app.core.milvus import connect_milvus
from app.core.websocket_manager import manager
from fastapi import WebSocket, WebSocketDisconnect

app.include_router(knowledge_base.router, prefix="/api/knowledge-bases", tags=["Knowledge Base"])
app.include_router(document.router, prefix="/api/knowledge-bases", tags=["Documents"])
app.include_router(retrieval.router, prefix="/api/knowledge-bases", tags=["Retrieval"])

from app.api import graph_viewer
app.include_router(graph_viewer.router, prefix="/api/retrieval/graph", tags=["Graph Viewer"])

@app.websocket("/api/ws/{kb_id}")
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

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Connect to Milvus
    try:
        connect_milvus()
        print("[Startup] Milvus Connected.", file=sys.stdout, flush=True)
    except Exception as e:
        print(f"[Startup] Failed to connect to Milvus: {e}", file=sys.stdout, flush=True)
        
    # Recovery Task: Resume incomplete deletions
    try:
        from app.models.document import Document, DocumentStatus
        from app.services.ingestion.cleanup_service import cleanup_service
        from app.core.database import SessionLocal
        from sqlalchemy.future import select
        import asyncio
        
        print("[Startup] Checking for incomplete deletions...", file=sys.stdout, flush=True)
        
        async with SessionLocal() as db:
            result = await db.execute(select(Document).filter(Document.status == DocumentStatus.DELETING.value))
            deleting_docs = result.scalars().all()
            
            if deleting_docs:
                print(f"[Recovery] Found {len(deleting_docs)} documents in DELETING state. Resuming cleanup...", file=sys.stdout, flush=True)
                for doc in deleting_docs:
                    # We use asyncio.create_task to run in background
                    # Wrap in specific error handling
                    async def safe_cleanup(kb_id, doc_id):
                        try:
                            await cleanup_service.perform_cascading_deletion(kb_id, doc_id)
                        except Exception as e:
                            print(f"[Recovery] Cleanup failed for {doc_id}: {e}", file=sys.stdout, flush=True)
                            
                    asyncio.create_task(safe_cleanup(doc.kb_id, doc.id))
                    print(f"[Recovery] Queued cleanup for doc {doc.id}", file=sys.stdout, flush=True)
            else:
                print("[Recovery] No incomplete deletions found.", file=sys.stdout, flush=True)
                
    except Exception as e:
        print(f"[Recovery] Failed to resume deletion tasks: {e}", file=sys.stdout, flush=True)



