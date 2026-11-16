"""RAGaaS MCP 서버 (docs/design-mcp-agent-query.md §5) — Streamable HTTP, /api/mcp 에 마운트.

게이트웨이 경로: /ragaas/api/mcp (기존 /ragaas/api/ 규칙이 /api/ 로 넘김 — 게이트웨이 변경 불필요).
인증은 앱 전역 platform_auth 미들웨어가 처리한다 (계약 05).

도구는 REST(/api/v2/knowledge-bases/{kb}/agent/...)와 같은 서비스 함수를 부른다. 모두 읽기 전용,
search 를 빼면 RAGaaS 쪽 LLM 호출이 없다.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

INSTRUCTIONS = """RAGaaS 지식 그래프 조회 도구.
순서: list_kbs → describe_kb(스키마·값 어휘, KB 당 1회 캐시) → lookup_values / resolve_entities(질문 속 말을 그래프 표기로)
→ query_plan(조건 트리로 조회) → get_chunks(근거 원문) → 답변은 호출한 쪽이 쓴다.
- 말을 맞출 때 원문과 영어 표기(오탈자 교정)를 함께 보낸다 (terms_en / names_en).
- 같은 계열 관계(강도·부호만 다름)를 '긍정 전체'로 찾을 때는 path 배열이나 any 로 묶는다. AND 로 묶지 않는다.
- query_plan 결과가 zero 면 message 를 읽고 값을 다시 맞추거나 조건을 바꾼다 (서버가 자동 완화하지 않음).
- 질의로 표현하기 어려운 설명형 질문만 search 를 쓴다."""


def _security() -> TransportSecuritySettings:
    """DNS rebinding 보호: MCP_ALLOWED_HOSTS 가 있으면 켠다 (예: "192.168.219.115:*,localhost:*").
    없으면 끈다 — 폐쇄망 + 게이트웨이 + 플랫폼 인증 뒤에서 쓰는 기본 구성."""
    hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    origins = [h.strip() for h in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if h.strip()]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


mcp = MCPServer(name="ragaas", title="RAGaaS 지식 그래프", version="0.1.0", instructions=INSTRUCTIONS)


def _err(e: Exception) -> Dict[str, Any]:
    if isinstance(e, HTTPException):
        return {"status": "error", "code": e.status_code, "message": str(e.detail)}
    return {"status": "error", "message": str(e)[:500]}


@mcp.tool(description="쓸 수 있는 KB 목록. 지식 그래프 조회(describe_kb·query_plan)는 queryable=true 인 KB 만 가능.")
async def list_kbs() -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    rows = await KnowledgeBase.find_all().to_list()
    return {"kbs": [{"kb_id": str(k.id), "name": k.name, "description": (k.description or "")[:200],
                     "graph_backend": k.graph_backend or "none",
                     "queryable": (k.graph_backend or "") == "ontology"} for k in rows]}


@mcp.tool(description="KB 스키마: 유형(kinds)과 멤버 이름, 유형별 경로(path key, 정의, 계열·부호·강도, 값 어휘와 건수), "
                      "schema_version. query_plan 의 path 는 여기의 key, value 는 values 의 label 표기 그대로 쓴다. "
                      "KB 당 한 번 받아 두고 schema_version 이 바뀌면 다시 받는다.")
async def describe_kb(kb_id: str, kinds: Optional[List[str]] = None, max_values: int = 30) -> Dict[str, Any]:
    from app.services.agent_query import catalog
    try:
        return await catalog.describe_kb(kb_id, kinds, max_values)
    except Exception as e:
        return _err(e)


@mcp.tool(description="질문 속 말 → 그래프 값 후보(경로별). 한영·음역·동의어는 사전으로, 오탈자·처음 보는 표기는 "
                      "terms_en(말→영어 표기, 오탈자를 고쳐서)으로 찾는다. narrower 는 상위 개념(유지보수성 등)을 하위 값으로 푼 후보, "
                      "suggestions 는 확정 못 한 후보.")
async def lookup_values(kb_id: str, terms: List[str], terms_en: Optional[Dict[str, str]] = None,
                        kind: Optional[str] = None, limit: int = 8) -> Dict[str, Any]:
    from app.services.agent_query import catalog
    try:
        return await catalog.lookup_values(kb_id, terms, kind, max(1, min(limit, 30)), terms_en or {})
    except Exception as e:
        return _err(e)


@mcp.tool(description="이름 → 그래프 엔티티(유형 멤버). 마이크로서비스→Microservices, Einstein→아인슈타인. "
                      "names_en(이름→영어 표기)을 함께 주면 오탈자도 찾는다.")
async def resolve_entities(kb_id: str, names: List[str], names_en: Optional[Dict[str, str]] = None,
                           kind: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
    from app.services.agent_query import catalog
    try:
        return await catalog.resolve_entities(kb_id, names, kind, max(1, min(limit, 20)), names_en or {})
    except Exception as e:
        return _err(e)


@mcp.tool(description="질의 계획 실행 (LLM 없음). where 는 조건 트리: {\"all\": [...]} = AND, {\"any\": [...]} = OR, "
                      "조건 = {\"path\": key | [key, ...], \"op\": eq|ne|in|contains|gt|gte|lt|lte|exists|not_exists, \"value\": ...}. "
                      "path 배열은 그 경로들 중 하나(OR). return 은 결과마다 보여 줄 경로 key 목록. "
                      "aggregate = {\"fn\": count|max|min|count_members, \"path\", \"value\", \"order\", \"limit\", \"having\"}. "
                      "결과: entities(라벨·충족 조건 수 matched·values·근거 트리플과 chunk_ids). zero 면 message 확인.")
async def query_plan(kb_id: str, kind: str, where: Optional[Any] = None, return_paths: Optional[List[Any]] = None,
                     aggregate: Optional[Dict[str, Any]] = None, rank_by: Optional[str] = "matched",
                     limit: int = 50, include_evidence: bool = True,
                     schema_version: Optional[str] = None) -> Dict[str, Any]:
    from app.services.agent_query.plan import run_plan
    try:
        return await run_plan(kb_id, {"kind": kind, "where": where, "return": return_paths or [],
                                      "aggregate": aggregate, "rank_by": rank_by, "limit": limit,
                                      "include_evidence": include_evidence, "schema_version": schema_version})
    except Exception as e:
        return _err(e)


@mcp.tool(description="근거 청크 원문과 문서명 (query_plan 결과의 chunk_ids). 최대 50개.")
async def get_chunks(kb_id: str, chunk_ids: List[str], max_chars: int = 1500) -> Dict[str, Any]:
    from app.services.agent_query import catalog
    try:
        return await catalog.get_chunks(kb_id, chunk_ids, max_chars)
    except Exception as e:
        return _err(e)


@mcp.tool(description="자연어 검색 (RAGaaS 검색 파이프라인, 수 초~수십 초, LLM 사용). 질의 계획으로 표현하기 어려운 "
                      "설명·정의형 질문에만. answer=false(기본)면 근거만 준다.")
async def search(kb_id: str, query: str, answer: bool = False, top_k: int = 8) -> Dict[str, Any]:
    from app.api.retrieval import ChatRequest, chat_with_kb
    try:
        resp = await chat_with_kb(kb_id, ChatRequest(query=query))
        d = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        chunks = []
        for c in (d.get("chunks") or [])[: max(1, min(top_k, 20))]:
            if c.get("chunk_id") == "GRAPH_METADATA_ONLY":
                continue
            chunks.append({"chunk_id": c.get("chunk_id"), "score": c.get("score"),
                           "text": (c.get("content") or "")[:800]})
        g = next((c.get("graph_metadata") for c in d.get("chunks") or [] if c.get("graph_metadata")), None) or {}
        out = {"result_summary": g.get("result_summary"), "triples": (g.get("triples") or [])[:40], "chunks": chunks,
               "execution_time": d.get("execution_time")}
        if answer:
            out["answer"] = d.get("answer")
        return out
    except Exception as e:
        return _err(e)


def mount(app) -> None:
    """FastAPI 앱에 /api/mcp 로 마운트하고, 세션 매니저를 앱 수명에 묶는다."""
    sub = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True,
                                  transport_security=_security())
    app.mount("/api/mcp", sub)
    state: Dict[str, Any] = {}

    @app.on_event("startup")
    async def _mcp_start():
        cm = mcp.session_manager.run()
        await cm.__aenter__()
        state["cm"] = cm

    @app.on_event("shutdown")
    async def _mcp_stop():
        cm = state.pop("cm", None)
        if cm is not None:
            await cm.__aexit__(None, None, None)
