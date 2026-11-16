"""외부 에이전트용 조회 API (docs/design-mcp-agent-query.md §4, §5).

/api/v2/knowledge-bases/{kb_id}/agent/...  — MCP 도구(P3)도 같은 서비스 함수를 부른다.
모든 엔드포인트는 읽기 전용이며 LLM 을 호출하지 않는다.
"""
import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.agent_query import catalog

router = APIRouter()


class ValuesRequest(BaseModel):
    terms: List[str] = Field(..., description="질문 속 말 (예: ['수정 용이성', '유지보수성'])")
    terms_en: Dict[str, str] = Field(default_factory=dict,
                                     description="말 → 영어 표기 (클라이언트가 오탈자를 고쳐 번역). 사전에 없을 때만 쓰임")
    kind: Optional[str] = None
    limit: int = 8


class EntitiesRequest(BaseModel):
    names: List[str]
    names_en: Dict[str, str] = Field(default_factory=dict, description="이름 → 영어 표기 (사전에 없을 때만 쓰임)")
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
async def agent_describe(kb_id: str, kinds: Optional[str] = None, max_values: int = catalog.MAX_VALUES_DEFAULT,
                         format: str = "json", min_members: int = 2):
    """① 스키마: 유형, 경로(정의·계열·값 어휘), 스키마 버전. format=compact 면 경로를 한 줄 문자열로."""
    t = time.time()
    out = await catalog.describe_kb(kb_id, [k for k in (kinds or "").split(",") if k], max_values, format, min_members)
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


@router.post("/{kb_id}/agent/values")
async def agent_values(kb_id: str, req: ValuesRequest):
    """② 말 → 경로별 값 후보."""
    t = time.time()
    out = await catalog.lookup_values(kb_id, req.terms, req.kind, max(1, min(req.limit, 30)), req.terms_en)
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


@router.post("/{kb_id}/agent/entities")
async def agent_entities(kb_id: str, req: EntitiesRequest):
    """② 이름 → 유형 멤버 엔티티."""
    t = time.time()
    out = await catalog.resolve_entities(kb_id, req.names, req.kind, max(1, min(req.limit, 20)), req.names_en)
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


class EntityRequest(BaseModel):
    name: str
    name_en: Optional[str] = None
    kind: Optional[str] = None


@router.post("/{kb_id}/agent/entity")
async def agent_entity(kb_id: str, req: EntityRequest):
    """엔티티 하나의 모든 관계 (나가는·들어오는, 구조 노드 한 단계) + 근거 청크 ID."""
    t = time.time()
    out = await catalog.describe_entity(kb_id, req.name, req.name_en, req.kind)
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


@router.post("/{kb_id}/agent/chunks")
async def agent_chunks(kb_id: str, req: ChunksRequest):
    """⑤ 근거 청크 원문."""
    t = time.time()
    out = await catalog.get_chunks(kb_id, req.chunk_ids, req.max_chars)
    out["elapsed_ms"] = int((time.time() - t) * 1000)
    return out


class PlanRequest(BaseModel):
    kind: Optional[str] = None
    where: Optional[Any] = None
    # 'return' 은 파이썬 예약어라 별칭으로 받는다
    returns: List[Any] = Field(default_factory=list, alias="return")
    aggregate: Optional[Dict[str, Any]] = None
    rank_by: Optional[str] = None
    limit: int = 50
    include_evidence: bool = True
    evidence: str = "compact"          # compact | full | none (응답 크기)
    schema_version: Optional[str] = None

    model_config = {"populate_by_name": True}


@router.post("/{kb_id}/agent/plan")
async def agent_plan(kb_id: str, req: PlanRequest):
    """④ 질의 계획 실행 — 검증 → 컴파일 → 실행 → 엔티티·근거 트리플·청크 ID (LLM 없음, §4.4)."""
    from app.services.agent_query.plan import run_plan
    body = req.model_dump(by_alias=True)
    return await run_plan(kb_id, body)


# ---------------------------------------------------------------------------
# 용어 사전 (docs/design-kb-lexicon.md)
# ---------------------------------------------------------------------------

@router.post("/{kb_id}/lexicon/build")
async def lexicon_build(kb_id: str, rebuild: bool = False):
    """사전 생성 (백그라운드). 기본은 사전에 없는 라벨만 — rebuild=true 면 LLM 항목을 다시."""
    from app.services.agent_query import lexicon as lx
    if lx.build_status(kb_id).get("state") == "running":
        return lx.build_status(kb_id)
    asyncio.create_task(lx.build_lexicon(kb_id, rebuild=rebuild))
    await asyncio.sleep(0)
    return {"state": "running"}


@router.get("/{kb_id}/lexicon/status")
async def lexicon_status(kb_id: str):
    from app.services.agent_query import lexicon as lx
    return lx.build_status(kb_id)


@router.get("/{kb_id}/lexicon")
async def lexicon_list(kb_id: str, q: Optional[str] = None, limit: int = 200):
    from app.models.lexicon import KbLexiconEntry
    rows = await KbLexiconEntry.find({"kb_id": kb_id}).to_list()
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in " ".join([r.label] + r.ko + r.en + r.syn).lower()]
    rows.sort(key=lambda r: (r.concept_only, r.label))
    return {"total": len(rows), "entries": [r.model_dump(exclude={"id", "revision_id"}) for r in rows[:max(1, min(limit, 2000))]]}


@router.get("/{kb_id}/lexicon/duplicates")
async def lexicon_duplicates(kb_id: str):
    from app.services.agent_query import lexicon as lx
    return {"groups": await lx.duplicates(kb_id)}


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
