"""외부 에이전트용 조회 API (docs/design-mcp-agent-query.md §4, §5).

/api/v2/knowledge-bases/{kb_id}/agent/...  — MCP 도구(P3)도 같은 서비스 함수를 부른다.
모든 엔드포인트는 읽기 전용이며 LLM 을 호출하지 않는다.
"""
import asyncio
import os
import re
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.agent_query import catalog

router = APIRouter()


class ValuesRequest(BaseModel):
    terms: List[str] = Field(..., description="질문 속 말 (예: ['수정 용이성', '유지보수성'])")
    kind: Optional[str] = None
    limit: int = 8


class EntitiesRequest(BaseModel):
    names: List[str]
    kind: Optional[str] = None
    limit: int = 5


class ChunksRequest(BaseModel):
    chunk_ids: List[str]
    max_chars: int = 1500


class SparqlRequest(BaseModel):
    query: str
    limit: int = 500
    timeout_ms: int = 5000


@router.get("/{kb_id}/agent/describe")
async def agent_describe(kb_id: str, kinds: Optional[str] = None, max_values: int = catalog.MAX_VALUES_DEFAULT):
    """① 스키마: 유형, 경로(정의·계열·값 어휘), 스키마 버전."""
    t = time.time()
    out = await catalog.describe_kb(kb_id, [k for k in (kinds or "").split(",") if k], max_values)
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


@router.post("/{kb_id}/agent/values")
async def agent_values(kb_id: str, req: ValuesRequest):
    """② 말 → 경로별 값 후보."""
    t = time.time()
    out = await catalog.lookup_values(kb_id, req.terms, req.kind, max(1, min(req.limit, 30)))
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


@router.post("/{kb_id}/agent/entities")
async def agent_entities(kb_id: str, req: EntitiesRequest):
    """② 이름 → 유형 멤버 엔티티."""
    t = time.time()
    out = await catalog.resolve_entities(kb_id, req.names, req.kind, max(1, min(req.limit, 20)))
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


@router.post("/{kb_id}/agent/chunks")
async def agent_chunks(kb_id: str, req: ChunksRequest):
    """⑤ 근거 청크 원문."""
    t = time.time()
    out = await catalog.get_chunks(kb_id, req.chunk_ids, req.max_chars)
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


# ---------------------------------------------------------------------------
# 원문 SPARQL — 관리자·디버깅 전용 (§4.5, §9-5). 기본 꺼짐: AGENT_SPARQL_ENABLED=true
# ---------------------------------------------------------------------------

_SPARQL_SEM = asyncio.Semaphore(int(os.getenv("AGENT_SPARQL_MAX_CONCURRENCY", "2")))
_FORBIDDEN = re.compile(r"\b(INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|COPY|MOVE|ADD|SERVICE|WITH)\b", re.I)
_FORM = re.compile(r"^\s*(?:(?:PREFIX|BASE)\s+[^\n]*\n\s*)*(SELECT|ASK|CONSTRUCT|DESCRIBE)\b", re.I)


def check_readonly(query: str) -> str:
    """읽기 전용 질의 형식만 통과. 문자열 리터럴·IRI 안의 단어는 검사에서 뺀다."""
    if not query or len(query) > 20000:
        raise HTTPException(status_code=400, detail="질의가 비었거나 너무 김 (20,000자)")
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|<[^>\s]*>|#[^\n]*', " ", query)
    if _FORBIDDEN.search(stripped):
        raise HTTPException(status_code=400, detail="읽기 전용 질의만 허용 (INSERT/DELETE/LOAD/SERVICE 등 금지)")
    m = _FORM.match(stripped)
    if not m:
        raise HTTPException(status_code=400, detail="SELECT / ASK / CONSTRUCT / DESCRIBE 만 허용")
    return m.group(1).upper()


@router.post("/{kb_id}/agent/sparql")
async def agent_sparql(kb_id: str, req: SparqlRequest, request: Request):
    if os.getenv("AGENT_SPARQL_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="원문 SPARQL 은 관리자·디버깅 전용이며 꺼져 있음 — query_plan 을 쓰세요")
    form = check_readonly(req.query)
    if form != "SELECT":
        raise HTTPException(status_code=400, detail="현재 SELECT 만 지원")
    await catalog.load_catalog(kb_id)       # ontology KB 확인
    limit = max(1, min(req.limit, 5000))
    timeout = max(500, min(req.timeout_ms, 20000)) / 1000
    import requests
    from app.core.fuseki import fuseki_client
    url = fuseki_client._get_dataset_url(kb_id) + "/query"

    def _run():
        r = requests.post(url, data={"query": req.query, "timeout": str(int(timeout * 1000))},
                          headers={"Accept": "application/sparql-results+json"},
                          auth=fuseki_client.auth, timeout=timeout + 2)
        if r.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Fuseki 오류 {r.status_code}: {r.text[:300]}")
        return r.json()

    t = time.time()
    async with _SPARQL_SEM:
        try:
            data = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout + 3)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail=f"질의 시간 초과 ({timeout:g}초)")
    vars_ = data.get("head", {}).get("vars", [])
    rows = [{v: b[v]["value"] for v in vars_ if v in b} for b in data.get("results", {}).get("bindings", [])]
    return {"vars": vars_, "rows": rows[:limit], "truncated": len(rows) > limit,
            "elapsed_ms": int((time.time() - t) * 1000)}
