from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(title="RAG Management System API")

from app.core.milvus import MilvusUnavailableError


@app.exception_handler(MilvusUnavailableError)
async def milvus_unavailable_handler(request: Request, exc: MilvusUnavailableError):
    # Milvus 가 멈추거나 컬렉션이 로드되지 않을 때 — 500 대신 503 으로 원인을 알려준다
    return JSONResponse(status_code=503, content={"detail": str(exc)})


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

# KB 스키마 매핑 제안·규칙 (docs/design/schema/design-schema-mismatch.md)
from app.api import schema_alignment
app.include_router(schema_alignment.router, prefix="/api/v2/knowledge-bases", tags=["Schema Alignment"])

from app.api import graph_viewer
app.include_router(graph_viewer.router, prefix="/api/v2/graph", tags=["Graph Viewer"])

# 외부 에이전트용 조회 (docs/design/agent/design-mcp-agent-query.md) — 읽기 전용, LLM 없음
from app.api import agent_query
app.include_router(agent_query.router, prefix="/api/v2/knowledge-bases", tags=["Agent Query"])

# MCP 서버 (Streamable HTTP, /api/mcp → 게이트웨이 /ragaas/api/mcp) — docs/design/agent/design-mcp-agent-query.md §5
try:
    from app.mcp_server import mount as _mount_mcp
    _mount_mcp(app)
except ImportError as _e:      # mcp SDK 미설치 이미지에서도 나머지 API 는 뜨게
    print(f"[Startup] MCP 서버 비활성: {_e}")

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

    # 그래프 KB 캐시 미리 채우기 (카탈로그 + 라벨 임베딩 + 용어 사전) — 재시작 직후 첫 질문·MCP 호출이
    # 수 초를 떠안지 않게. 참조를 app.state 에 보관 (GC 로 작업이 사라지지 않게) — 2026-11-17
    import asyncio as _asyncio
    from app.services.agent_query import catalog as _cat
    app.state.warm_task = _asyncio.get_running_loop().create_task(_cat.warm_all())

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



