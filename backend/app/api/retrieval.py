from fastapi import APIRouter, Depends, HTTPException
from app.schemas import RetrievalRequest, RetrievalResult
from app.services.retrieval import retrieval_factory, reranking_service
from typing import Any, List, Optional, Dict
from pydantic import BaseModel, Field
import asyncio
import openai
import os
import time
import json
import re

router = APIRouter()

import contextvars as _contextvars
# 스트리밍 요청일 때만 설정되는 큐 (chat_with_kb 가 답변 조각을 넣는다)
_STREAM_QUEUE: "_contextvars.ContextVar" = _contextvars.ContextVar("ragaas_chat_stream_queue", default=None)

_RETRIEVAL_MODEL_KEYMAP = {
    "default": {
        "provider": "retrieval_llm_provider",
        "model": "retrieval_llm_model",
        "base_url": "retrieval_llm_base_url",
        "provider_id": "retrieval_llm_provider_id",
    },
    "keyword": {
        "provider": "keyword_llm_provider",
        "model": "keyword_llm_model",
        "base_url": "keyword_llm_base_url",
        "provider_id": "keyword_llm_provider_id",
    },
}


def _has_model_selection(config: Optional[dict]) -> bool:
    if not config:
        return False
    return any(config.get(k) for k in ("provider", "provider_id", "model", "api_key", "base_url"))


def _format_model_error_message(error_text: str) -> str:
    if "not configured" in error_text.lower() or "모델 지정" in error_text:
        return f"모델 지정이 안되었습니다: {error_text}"
    return error_text


def _read_model_from_kb_storage(kb, kind: str) -> dict:
    mapping = _RETRIEVAL_MODEL_KEYMAP[kind]
    cfg = kb.chunking_config or {}
    return {
        "provider": cfg.get(mapping["provider"]),
        "model": cfg.get(mapping["model"]),
        "base_url": cfg.get(mapping["base_url"]),
        "provider_id": cfg.get(mapping["provider_id"]),
    }


def _write_model_to_kb_storage(kb, kind: str, model_cfg: dict) -> bool:
    if not _has_model_selection(model_cfg):
        return False
    mapping = _RETRIEVAL_MODEL_KEYMAP[kind]
    cfg = kb.chunking_config.copy() if kb.chunking_config else {}
    changed = False
    for src, dst in mapping.items():
        value = model_cfg.get(src)
        # provider/model 은 값이 있을 때만 갱신하되, base_url/provider_id 는
        # 새 선택에 값이 없으면 명시적으로 비운다(None). 그러지 않으면 커스텀
        # 프로바이더(z.ai 등) → 빌트인(OpenAI 등) 전환 시 이전 base_url 이
        # 잔존해 "gpt 모델을 z.ai 로 보내는" 설정 오염이 재발한다.
        if src in ("provider", "model") and value in (None, ""):
            continue
        if value == "":
            value = None
        if cfg.get(dst) != value:
            cfg[dst] = value
            changed = True
    if changed:
        kb.chunking_config = cfg
    return changed


async def _resolve_retrieval_model_configs(
    kb,
    request_default: Optional[dict],
    request_keyword: Optional[dict],
    persist: bool,
) -> tuple[dict, dict]:
    stored_default = _read_model_from_kb_storage(kb, "default")
    stored_keyword = _read_model_from_kb_storage(kb, "keyword")

    default_cfg = (
        request_default if _has_model_selection(request_default)
        else stored_default if _has_model_selection(stored_default)
        else (kb.llm_model_config or {})
    )
    keyword_cfg = (
        request_keyword if _has_model_selection(request_keyword)
        else stored_keyword if _has_model_selection(stored_keyword)
        else default_cfg
    )

    if persist:
        changed = False
        if _has_model_selection(request_default):
            if kb.llm_model_config != request_default:
                kb.llm_model_config = request_default
                changed = True
            changed = _write_model_to_kb_storage(kb, "default", request_default) or changed
        if _has_model_selection(request_keyword):
            changed = _write_model_to_kb_storage(kb, "keyword", request_keyword) or changed
        if changed:
            await kb.save()

    return default_cfg or {}, keyword_cfg or {}

class ChatRequest(BaseModel):
    query: str  # Reverted to query to match frontend
    top_k: int = 5
    score_threshold: float = 0.0
    strategy: str = "hybrid"
    use_reranker: bool = False
    reranker_top_k: int = 10
    reranker_threshold: float = 0.3
    use_llm_reranker: bool = False
    llm_chunk_strategy: str = "full"
    use_ner: bool = False
    use_llm_keyword_extraction: bool = False
    use_multi_pos: bool = True  # Multi-POS tokenization
    bm25_top_k: int = 50
    use_parallel_search: bool = False
    enable_graph_search: bool = False
    graph_hops: int = 2
    use_brute_force: bool = False
    brute_force_top_k: int = 3
    brute_force_threshold: float = 1.5
    use_relation_filter: bool = True  # Neo4j: filter by relationship keywords

    # Fields sent by frontend but not strictly used in backend logic yet (or mapped differently)
    ann_top_k: int = 5
    ann_threshold: float = 0.0
    enable_inverse_search: bool = False
    inverse_extraction_mode: str = "auto"
    use_schema_mode: bool = True  # Schema-aware SPARQL generation for promoted KBs
    use_dynamic_schema: bool = True  # Dynamic schema injection for non-promoted KBs (기본 ON — 미주입 시 LLM 이 술어를 지어냄)
    use_raw_log: bool = False
    
    # Pipeline configuration (optional - if provided, uses pipeline executor)
    pipeline: Optional[dict] = None
    # 단일 검색 진입점 파라미터 (docs/design/agent/design-search-entry-and-pipeline-versions.md §3)
    config: Optional[str] = None     # live(운영, 기본) | draft(테스트). pipeline 이 있으면 그것이 우선 (편집 중인 구성)
    agentic: str = "pipeline"        # pipeline(구성대로) | skip(에이전틱 스테이지 건너뜀 — MCP 기본)
    answer: bool = True              # False 면 답변 생성 없이 근거만
    caller: str = "api"              # ui | api | mcp — 기록용 (동작을 바꾸지 않는다)
    
    # Model configurations for dynamic model selection
    pipeline_model_config: Optional[dict] = None         # Default chat LLM (backend 필드명)
    frontend_model_config: Optional[dict] = Field(None, alias="model_config") # 프론트엔드 호환용
    model_config_keyword: Optional[dict] = None

    class Config:
        extra = "allow"
        populate_by_name = True

class ChatResponse(BaseModel):
    answer: str
    chunks: List[RetrievalResult]
    execution_time: float = 0.0
    strategy: str = "unknown"
    execution_log: Optional[List[str]] = None
    pipeline_config: Optional[Dict] = None
    has_error: bool = False  # Query generation or execution error occurred
    used_fallback: bool = False  # Fallback search was triggered due to error/no results
    status: str = "ok"           # ok | disabled (검색 필터 없음)
    applied_policy: Optional[Dict] = None   # 실행한 구성·검색 필터·건너뛴 단계·Graph 옵션
    # 실패한 검색 스테이지 (2026-11-25): [{stage, index, kind: error|empty, message, routed_to}]
    # routed_to 가 있으면 실패 연결로 그 스테이지가 이어 받았고, 없으면 파이프라인이 거기서 멈췄다.
    stage_failures: List[Dict[str, Any]] = []
    # 답변 근거 검사 (answer_check 카드, 2026-11-25): {checked, unsupported: [{sentence, reason}], action, model} 또는 {error}
    answer_check: Optional[Dict[str, Any]] = None


from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent.parent
RERANK_PROMPT_PATH = "/app/data/prompts/rerank_llm_prompt.txt"
CHAT_PROMPT_PATH = _APP_ROOT / "data" / "prompts" / "chat_answer_prompt.txt"

DEFAULT_CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions based on the provided context. "
    "The context generally consists of Korean documents. "
    "Regardless of the language of the system instructions, YOU MUST ANSWER IN KOREAN (한국어). "
    "If multiple entities or items match the question, LIST ALL OF THEM. "
    "When asked about 'participants' or 'users' of a skill/item, ALSO INCLUDE its 'creators', 'masters', or 'teachers' mentioned in the context. "
    "If the context doesn't contain enough information to answer the question, say so. "
    "Always cite which chunks you used (e.g., '[Chunk 1]에 따르면...')."
)


def _load_chat_system_prompt() -> str:
    if CHAT_PROMPT_PATH.exists():
        return CHAT_PROMPT_PATH.read_text(encoding="utf-8")
    return DEFAULT_CHAT_SYSTEM_PROMPT


class PromptUpdateRequest(BaseModel):
    content: str


@router.get("/settings/rerank-prompt")
async def get_rerank_prompt():
    """Get the current LLM Rerank prompt"""
    try:
        with open(RERANK_PROMPT_PATH, 'r', encoding='utf-8') as f:
            return {"content": f.read()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Prompt file not found")


@router.put("/settings/rerank-prompt")
async def update_rerank_prompt(request: PromptUpdateRequest):
    """Update the LLM Rerank prompt"""
    try:
        with open(RERANK_PROMPT_PATH, 'w', encoding='utf-8') as f:
            f.write(request.content)
        return {"message": "Prompt updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_format_model_error_message(str(e)))


@router.get("/settings/chat-prompt")
async def get_chat_prompt():
    """Get the current Chat answer generation system prompt"""
    return {"content": _load_chat_system_prompt()}


@router.put("/settings/chat-prompt")
async def update_chat_prompt(request: PromptUpdateRequest):
    """Update the Chat answer generation system prompt"""
    CHAT_PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAT_PROMPT_PATH.write_text(request.content, encoding="utf-8")
    return {"message": "Chat prompt updated successfully"}


@router.post("/{kb_id}/retrieve", response_model=List[RetrievalResult])
async def retrieve_chunks(
    kb_id: str,
    request: RetrievalRequest,
    # db: AsyncSession = Depends(get_db) # Removed SQL Session
):
    print(f"[DEBUG] Retrieve Request: brute={request.use_brute_force} bf_top_k={request.brute_force_top_k} bf_thresh={request.brute_force_threshold}")
    
    from app.models.knowledge_base import KnowledgeBase
    from app.services.embedding import get_embedding_service
    kb = await KnowledgeBase.get(kb_id)
    
    with open("backend_debug.log", "a") as f:
        f.write(f"\n--- REQ ---\nDefault TopK: {request.top_k}\nBF: {request.use_brute_force}\n")
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    llm_default_config, llm_keyword_config = await _resolve_retrieval_model_configs(
        kb=kb,
        request_default=None,
        request_keyword=None,
        persist=False,
    )
        
    metric_type = kb.metric_type or "COSINE"
    kb_emb_service = await get_embedding_service(kb)

    # 1. Selection & Retrieval
    strategy = retrieval_factory.get_strategy(request.strategy)
    results = await strategy.search(
        kb_id, 
        request.query, 
        request.top_k, 
        metric_type=metric_type, 
        score_threshold=request.score_threshold,
        enable_graph_search=request.enable_graph_search,
        graph_hops=request.graph_hops,
        graph_backend=kb.graph_backend or "ontology",
        use_llm_keyword_extraction=request.use_llm_keyword_extraction,
        use_multi_pos=request.use_multi_pos,
        bm25_top_k=request.bm25_top_k,
        use_parallel_search=request.use_parallel_search,
        # Graph specific - 사용자 설정 그대로 전달
        enable_inverse_search=request.enable_inverse_search,
        inverse_extraction_mode=request.inverse_extraction_mode,
        use_relation_filter=request.use_relation_filter,
        embedding_service=kb_emb_service,
        llm_model_config=llm_default_config,
        keyword_llm_model_config=llm_keyword_config,
    )
    
    # 2. Reranking (Cross-Encoder)
    rerank_llm_config = llm_default_config
    if request.use_reranker and request.strategy != "2-stage" and results:
        print(f"[DEBUG] Applying reranker: top_k={request.reranker_top_k}, threshold={request.reranker_threshold}")
        
        if request.use_llm_reranker:
            results = await reranking_service.llm_rerank_results(
                query=request.query,
                results=results,
                top_k=request.reranker_top_k,
                threshold=request.reranker_threshold,
                strategy=request.llm_chunk_strategy,
                llm_model_config=rerank_llm_config or {},
            )
        else:
            results = await reranking_service.rerank_results(
                query=request.query,
                results=results,
                top_k=request.reranker_top_k,
                threshold=request.reranker_threshold
            )

    # 3. NER Filtering
    if request.use_ner and results:
        from app.services.ner import ner_service
        print(f"[DEBUG] Applying NER filter")
        results = ner_service.filter_by_entities(request.query, results, penalty=0.3)
        
    # 3.5. Flat Index (L2) Re-ranking
    if request.use_brute_force and results:
        from app.services.embedding import embedding_service
        import numpy as np
        
        print(f"[DEBUG] Applying Flat Index L2 Re-ranking (Top K: {request.brute_force_top_k}, Threshold (Max Dist): {request.brute_force_threshold})")
        
        query_embedding = (await embedding_service.get_embeddings([request.query]))[0]
        candidate_contents = [r['content'] for r in results]
        candidate_embeddings = await embedding_service.get_embeddings(candidate_contents)
        
        reranked = []
        for i, doc_embedding in enumerate(candidate_embeddings):
            vec1 = np.array(query_embedding)
            vec2 = np.array(doc_embedding)
            dist = float(np.linalg.norm(vec1 - vec2))
            
            if dist <= request.brute_force_threshold:
                try:
                    sim_score = 1.0 / (1.0 + dist)
                except:
                    sim_score = 0.0
                
                if np.isnan(sim_score) or np.isinf(sim_score):
                    sim_score = 0.0
                if np.isnan(dist) or np.isinf(dist):
                    pass
                
                chunk = results[i].copy()
                chunk['score'] = float(sim_score)
                chunk['l2_score'] = float(dist) if not np.isnan(dist) else None
                reranked.append(chunk)
        
        reranked.sort(key=lambda x: x['score'], reverse=True)
        results = reranked[:request.brute_force_top_k]

    # Parent-Child(small-to-big): child 로 찾은 결과를 parent 로 치환 (해당 청크만)
    from app.services.retrieval.parent_child import expand_to_parents
    results = await expand_to_parents(kb_id, results)

    return results

@router.post("/{kb_id}/chat", response_model=ChatResponse)
async def chat_with_kb(
    kb_id: str,
    request: ChatRequest,
    # db: AsyncSession = Depends(get_db)
):
    start_time = time.time()
    
    # 파라미터 로깅 (프론트엔드 → 백엔드 전달 확인)
    print("=" * 80)
    print("📥 [Backend] Received Chat Request")
    
    from app.models.knowledge_base import KnowledgeBase
    from app.services.embedding import get_embedding_service
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    llm_default_config, llm_keyword_config = await _resolve_retrieval_model_configs(
        kb=kb,
        request_default=request.pipeline_model_config or request.frontend_model_config,
        request_keyword=request.model_config_keyword,
        persist=True,
    )
        
    metric_type = kb.metric_type or "COSINE"
    kb_emb_service = await get_embedding_service(kb)

    # 파이프라인(= KB 검색 정책) 결정 — 편집 중인 구성(request.pipeline) > 테스트(draft) > 운영(live)
    from app.services.retrieval import search_policy as sp
    pipeline_config, _cfg_meta = await sp.resolve_pipeline(kb, request.config or "live", request.pipeline)
    _skipped: List[str] = []
    if request.agentic == "skip" and any(s.get("type") == sp.AGENTIC_STAGE for s in sp.stages_of(pipeline_config)):
        pipeline_config = sp.without_agentic(pipeline_config)
        _skipped.append(f"agentic ({request.caller})")
    applied_policy = {"config": _cfg_meta, "caller": request.caller, "answer": request.answer,
                      **sp.summarize(pipeline_config), "skipped": _skipped}
    if applied_policy["graph"] and not applied_policy["graph"]["typo_synonym"]:
        _skipped.append("typo_synonym (꺼짐)")
    print(f"[Pipeline] {_cfg_meta.get('kind')} 구성 {len(sp.stages_of(pipeline_config))} 스테이지 (caller={request.caller})")

    # 검색 필터가 없으면 검색하지 않는다 — 옛 '레거시 전략' 경로는 쓰지 않는다
    if not applied_policy["search_filters"]:
        return ChatResponse(
            answer="", chunks=[], execution_time=time.time() - start_time, strategy="없음",
            execution_log=["[Policy] 파이프라인에 검색 필터가 없어 검색하지 않음 — 검색 결과 없음"],
            pipeline_config=pipeline_config, status="disabled", applied_policy=applied_policy,
        )

    # 'smalltalk' 필터 스테이지가 파이프라인에 있을 때만 스몰톡 게이트가 동작한다.
    # (파이프라인 빌더에서 이 스테이지를 삭제하면 스몰톡 처리도 비활성 → 그냥 검색.)
    _has_smalltalk_stage = bool(pipeline_config) and any(
        s.get("type") == "smalltalk" for s in (pipeline_config.get("stages") or [])
    )
    if _has_smalltalk_stage and not request.answer:
        # 근거만 달라는 호출(MCP 등)에는 잡담 판정이 의미 없다 — 게이트를 건너뛴다
        _has_smalltalk_stage = False
        _skipped.append("gate (근거만 요청)")

    # --- Gate: 지정된 LLM 이 '검색 필요 여부'를 판별. 검색이 불필요하면(인사·잡담·자기소개 등)
    #     바로 응답하고 파이프라인을 중단한다. 검색이 필요하면 아래 검색 흐름으로 통과시킨다. ---
    if _has_smalltalk_stage:
        from app.core.models_resolver import resolve_model_config
        # 모델 우선순위: Gate 스테이지에 지정된 llm_model → KB 모델 → 기본 모델
        _gate_stage = next(
            (s for s in (pipeline_config.get("stages") or []) if s.get("type") == "smalltalk"),
            {},
        )
        _gate_model = (_gate_stage.get("params") or {}).get("llm_model")
        st_cfg = (
            _gate_model if (_gate_model or {}).get("model")
            else (kb.llm_model_config if (kb.llm_model_config or {}).get("model")
                  else (llm_default_config or {}))
        )
        st_resolved = await resolve_model_config(st_cfg or {})
        if st_resolved.get("api_key"):
            try:
                st_kwargs = {"api_key": st_resolved["api_key"]}
                if st_resolved.get("base_url"):
                    st_kwargs["base_url"] = st_resolved["base_url"]
                if st_resolved.get("extra_headers"):
                    st_kwargs["default_headers"] = st_resolved["extra_headers"]
                st_client = openai.OpenAI(**st_kwargs)
                gate_kwargs = dict(
                    model=st_resolved.get("model"),
                    messages=[
                        {"role": "system", "content": (
                            "당신은 RAGaaS 지식베이스 어시스턴트의 '게이트' 분류기입니다.\n"
                            "사용자 입력이 (A) 지식베이스 문서에서 정보를 찾아야 답할 수 있는 질문인지, "
                            "(B) 검색 없이 답할 수 있는 인사·감사·잡담·자기소개/능력 질문 등 일반 대화인지 "
                            "판별하세요.\n"
                            "반드시 아래 JSON 한 줄로만 출력하세요 (그 외 텍스트·설명·사고과정 금지):\n"
                            '{"needs_search": true|false, "answer": "..."}\n'
                            "- needs_search=true 이면 answer 는 빈 문자열.\n"
                            "- needs_search=false 이면 answer 에 한국어로 1~2문장의 친근한 최종 답변만 담을 것."
                        )},
                        {"role": "user", "content": request.query},
                    ],
                    temperature=0.0, max_tokens=400,
                )
                # 추론 모델(z.ai GLM 등)이 사고과정을 content 로 흘리지 않도록 thinking 비활성
                if "glm" in str(st_resolved.get("model", "")).lower():
                    gate_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                # 동기 클라이언트 — 스레드로 넘겨 이벤트 루프를 막지 않는다
                gate_resp = await asyncio.to_thread(st_client.chat.completions.create, **gate_kwargs)
                raw = (gate_resp.choices[0].message.content or "").strip()
                # JSON 추출 (코드펜스/여분 텍스트 방어)
                verdict = None
                try:
                    verdict = json.loads(raw)
                except Exception:
                    m = re.search(r"\{.*\}", raw, re.DOTALL)
                    if m:
                        try:
                            verdict = json.loads(m.group(0))
                        except Exception:
                            verdict = None
                if isinstance(verdict, dict) and not verdict.get("needs_search", True):
                    return ChatResponse(
                        answer=verdict.get("answer") or "",
                        chunks=[],
                        execution_time=time.time() - start_time,
                        strategy="Gate (검색 생략)",
                        execution_log=["[Gate] LLM 판별: 검색 불필요 — 직접 응답"],
                        pipeline_config=None, applied_policy=applied_policy,
                    )
                print("[Gate] LLM 판별: 검색 필요 — 파이프라인 진행")
            except Exception as e:
                print(f"[Gate] 판별 실패, 일반 파이프라인으로 진행: {e}")
        # 모델 미설정/실패/검색필요 시 아래 일반 검색 흐름으로 진행

    execution_logs = []
    stage_failures: List[Dict[str, Any]] = []

    # 검색 스테이지 = smalltalk(비검색 게이트)·answer_check(답변 뒤 검사)를 제외한 실제 검색 필터들
    search_stages = [
        s for s in (pipeline_config.get("stages") or [] if pipeline_config else [])
        if s.get("type") not in ("smalltalk", "answer_check")
    ]

    # Pipeline mode execution
    if search_stages:
        from app.services.retrieval.pipeline_executor import pipeline_executor
        from app.schemas.pipeline import PipelineConfig, PipelineStage

        # Convert dict to PipelineConfig (smalltalk 스테이지는 이미 제외됨)
        stages = [PipelineStage(**s) for s in search_stages]
        config = PipelineConfig(stages=stages)
        
        llm_config = llm_default_config
        exec_ctx = await pipeline_executor.execute(
            kb_id=kb_id,
            query=request.query,
            config=config,
            graph_backend=kb.graph_backend or "ontology",
            metric_type=metric_type,
            embedding_service=kb_emb_service,
            llm_model_config=llm_config or {},
        )
        
        results = exec_ctx.results
        execution_logs = exec_ctx.logs
        stage_failures = exec_ctx.failures
        graph_metadata = exec_ctx.metadata.get("graph_metadata")
        
        # Attach graph metadata to first result if present
        if graph_metadata and results:
            results[0]["graph_metadata"] = graph_metadata
    with open("backend_debug.log", "a") as f:
        f.write(f"Strategy: {request.strategy}, Final Results: {len(results) if results else 0}\\n")
    
    async def get_openai_client(config: Optional[dict]):
        """ModelConfig를 기반으로 OpenAI 호환 클라이언트 생성."""
        if not config or not any(config.get(k) for k in ("provider", "provider_id", "model", "api_key", "base_url")):
            raise HTTPException(
                status_code=500,
                detail="모델 지정이 안되었습니다: LLM 모델을 먼저 선택해주세요.",
            )
        from app.core.models_resolver import resolve_model_config
        from app.core.llm import has_credentials
        resolved = await resolve_model_config(config)
        if not has_credentials(resolved):
            raise HTTPException(status_code=500, detail="LLM API key/헤더가 설정되지 않았습니다.")
        return resolved, resolved.get("model")

    def _display_strategy() -> str:
        if pipeline_config and pipeline_config.get("stages"):
            names = []
            for stage in pipeline_config["stages"]:
                if stage.get("type") in ("smalltalk", "answer_check"):
                    continue  # 게이트·답변 검사는 검색 단계가 아니므로 전략명에서 제외
                s_type = stage.get("type", "unknown").upper()
                names.append("Vector" if s_type == "ANN" else s_type)
            return " → ".join(names)
        base = request.strategy.lower()
        name = {"hybrid": "Hybrid", "keyword": "Keyword", "ann": "Vector", "vector": "Vector",
                "2-stage": "2-Stage (L2)"}.get(base, base.capitalize())
        if request.enable_graph_search or (kb.enable_graph_rag and kb.graph_backend):
            return f"Graph → {name}"
        return name

    stage_error = any(f.get("kind") == "error" for f in stage_failures)

    # Parent-Child(small-to-big): child 로 찾은 결과를 parent 로 치환 (해당 청크만).
    # 파이프라인/레거시 경로 모두 여기를 지나므로 한 곳에서 처리한다.
    from app.services.retrieval.parent_child import expand_to_parents
    results = await expand_to_parents(kb_id, results, logs=execution_logs)

    # 근거만 요청 (MCP 등) — 답변 생성을 하지 않는다 (호출당 LLM 1회·4~8초 절약)
    if not request.answer:
        elapsed = time.time() - start_time
        asyncio.create_task(_save_chat_trace(kb_id, request.query, "", "근거만", elapsed, stage_error, False,
                                             execution_logs, results, {**pipeline_config, "_applied": applied_policy}))
        return ChatResponse(answer="", chunks=results or [], execution_time=elapsed, strategy="근거만",
                            execution_log=execution_logs, pipeline_config=pipeline_config,
                            applied_policy=applied_policy, has_error=stage_error,
                            stage_failures=stage_failures)

    # 4. Generate LLM response based on retrieved chunks
    if not results:
        # 결과가 없을 때도 실패를 숨기지 않는다 — 어떤 스테이지가 왜 실패했는지 답변·응답에 싣는다
        if stage_failures:
            lines = [f"- {f['stage']} (Stage {f.get('index')}): "
                     + ("오류 — " if f.get("kind") == "error" else "결과 없음 — ") + str(f.get("message") or "")
                     + (f" → {f['routed_to']} 로 넘김" if f.get("routed_to") else " → 파이프라인 중단")
                     for f in stage_failures]
            answer = ("검색 단계가 실패해 답변할 근거를 찾지 못했습니다.\n" if stage_error
                      else "관련 정보를 찾지 못했습니다.\n") + "\n".join(lines)
        else:
            answer = "I couldn't find any relevant information to answer your question."
        elapsed = time.time() - start_time
        display_strategy = _display_strategy()
        asyncio.create_task(_save_chat_trace(kb_id, request.query, answer, display_strategy, elapsed, stage_error,
                                             False, execution_logs, [],
                                             {**(pipeline_config or {}), "_applied": applied_policy}))
        return ChatResponse(
            answer=answer,
            chunks=[],
            execution_time=elapsed,
            strategy=display_strategy,
            execution_log=execution_logs,
            pipeline_config=pipeline_config, applied_policy=applied_policy,
            has_error=stage_error, stage_failures=stage_failures,
        )
    
    # Build context from top chunks
    context_parts = []
    
    # Check for graph metadata in the first result (where it's attached)
    if results and results[0].get("graph_metadata"):
        metadata = results[0]["graph_metadata"]
        triples = metadata.get("triples", [])
        # 유형 수준 질문: 조건을 만족하는 엔티티 전체 목록 (답변이 빠짐없이 나열하도록)
        if metadata.get("result_summary"):
            context_parts.append(f"### Query Plan Result:\n{metadata['result_summary']}\n")
        if triples:
            # Check type of triples
            # Graph logic might return strings like "(s) -[p]-> (o)" OR dicts
            # 관계 타게팅 경로의 트리플은 근거 청크 id 를 갖는다 → 컨텍스트의 [Chunk n] 번호를 붙여
            # 답변 LLM 이 트리플과 청크의 연결을 보도록 한다.
            chunk_no = {
                r.get("chunk_id"): i + 1 for i, r in enumerate(results[:10]) if r.get("chunk_id")
            }
            formatted_triples = []
            for t in triples:
                if isinstance(t, str):
                    formatted_triples.append(f"- {t}")
                elif isinstance(t, dict):
                    refs = sorted({chunk_no[c] for c in (t.get("chunk_ids") or []) if c in chunk_no})
                    ref_txt = (" " + " ".join(f"[Chunk {n}]" for n in refs)) if refs else ""
                    formatted_triples.append(
                        f"- {t.get('subject', '?')} {t.get('predicate', '?')} {t.get('object', '?')}{ref_txt}"
                    )
            
            triples_text = "\n".join(formatted_triples)
            context_parts.append(f"### Graph Relationships (Derived from Knowledge Graph):\n{triples_text}\n")
            
    context_parts.extend([
        f"[Chunk {i+1}] {chunk['content']}"
        for i, chunk in enumerate(results[:10])  # Use top 10 chunks for context
    ])
    
    context = "\n\n".join(context_parts)

    # LLM 모델 설정: model_config (프론트) / pipeline_model_config (백엔드) 호환
    llm_config = llm_default_config or {}
    
    llm_cfg, llm_model = await get_openai_client(llm_config)

    system_prompt = _load_chat_system_prompt()

    try:
        from app.core.llm import achat, achat_stream
        _q = _STREAM_QUEUE.get()
        _answer_msgs = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {request.query}\n\nPlease provide a comprehensive answer based on the context above. If there are multiple answers, please list them all.\n"
                 "질문에 없는 사용자 상황(예: 팀 규모, 운영 성숙도, 예산)을 사실처럼 쓰지 마라 — 판단에 필요하면 '가정' 이라고 밝히고, "
                 "그 가정이 달라지면 결론이 어떻게 바뀌는지 한 줄로 덧붙여라."},
            ]
        _answer_kw = dict(model=llm_model, temperature=0.3, max_tokens=1000,
                          # 추론 모델(glm 계열)이 사고과정을 답변에 섞지 않도록 thinking 비활성 (OpenAI 등엔 미적용)
                          extra_body={"thinking": {"type": "disabled"}} if "glm" in (llm_model or "").lower() else None)
        if _q is not None:
            # 스트리밍 요청: 검색 결과를 먼저 보내고, 답변은 생성되는 대로 조각을 보낸다
            await _q.put(("retrieval", {"chunks": results, "execution_log": list(execution_logs)}))
            _parts = []
            async for _piece in achat_stream(llm_cfg, _answer_msgs, **_answer_kw):
                _parts.append(_piece)
                await _q.put(("token", _piece))
            answer = "".join(_parts)
        else:
            answer = await achat(llm_cfg, _answer_msgs, **_answer_kw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate response: {str(e)}")
    
    # 답변 근거 요약 (Execution Log 마지막 줄) — 그래프 트리플/청크 중 무엇이 쓰였는지
    try:
        g_meta = results[0].get("graph_metadata") if results else None
        n_triples = len((g_meta or {}).get("triples") or [])
        n_chunks = len([r for r in results[:10] if r.get("chunk_id") != "GRAPH_METADATA_ONLY"])
        cited = sorted({int(n) for n in re.findall(r"\[Chunk (\d+)\]", answer or "")})
        cited_txt = ", ".join(f"[Chunk {n}]" for n in cited) if cited else "(인용 표기 없음)"
        cited_ids = [
            str(results[n - 1].get("chunk_id", "")).split("::")[-1]
            for n in cited if 0 < n <= len(results)
        ]
        execution_logs.append(
            f"[Answer] 근거: 그래프 트리플 {n_triples}건 + 청크 {n_chunks}건 | 답변이 인용한 청크: {cited_txt}"
            + (f" = {', '.join(cited_ids)}" if cited_ids else "")
        )
    except Exception as e_ans:
        print(f"[Answer] grounding summary skipped: {e_ans}")

    # 답변 근거 검사 — 파이프라인 맨 끝의 'answer_check' 카드가 있을 때만 (추출 품질 후속 C)
    answer_check = None
    from app.services.retrieval import answer_check as ac
    _ac_stage = ac.stage_of(pipeline_config)
    if _ac_stage is not None and answer:
        _ac_params = _ac_stage.get("params") or {}
        try:
            _ac_cfg = llm_cfg
            if (_ac_params.get("llm_model") or {}).get("model"):
                from app.core.models_resolver import resolve_model_config
                _ac_cfg = await resolve_model_config(_ac_params["llm_model"])
            answer_check = await ac.check_answer(answer, context, _ac_cfg, _ac_params.get("action") or "mark")
            if answer_check.get("answer"):
                answer = answer_check.pop("answer")
            execution_logs.extend(ac.log_lines(answer_check))
        except Exception as e_ac:   # 검사 실패가 답변을 막지 않는다 — 실패를 알린다
            answer_check = {"error": str(e_ac)[:300]}
            execution_logs.append(f"[AnswerCheck] 검사 실패: {str(e_ac)[:200]}")

    display_strategy = _display_strategy()
    # Detect error and fallback states — 스테이지 실패 기록이 우선, 로그 스캔은 보조
    has_error = stage_error
    used_fallback = False
    in_reasoning_report = False
    for log_entry in execution_logs:
        # 그래프 추론 리포트 구간은 데이터(트리플 값 'graceful_fallback' 등)를 그대로 싣으므로 스캔 제외
        if "━━ 추론 리포트 ━━" in log_entry:
            in_reasoning_report = True
            continue
        if in_reasoning_report:
            if "── 상세 trace ──" in log_entry:
                in_reasoning_report = False
            continue
        log_lower = log_entry.lower()
        if "error" in log_lower or "failed" in log_lower or "generation failed" in log_lower:
            has_error = True
        if "fallback" in log_lower or "entity-guided" in log_lower:
            # Exclude false positives like "No fallback search performed"
            if "no fallback" not in log_lower and "fallback search disabled" not in log_lower:
                used_fallback = True
    
    elapsed = time.time() - start_time
    # 검색 기록 저장 (사후 검토용) — 응답을 늦추지 않도록 백그라운드로
    asyncio.create_task(_save_chat_trace(kb_id, request.query, answer, display_strategy, elapsed, has_error,
                                         used_fallback, execution_logs, results,
                                         {**(pipeline_config or {}), "_applied": applied_policy}))
    return ChatResponse(
        answer=answer,
        chunks=results,
        execution_time=elapsed,
        strategy=display_strategy,
        execution_log=execution_logs,
        pipeline_config=pipeline_config,
        has_error=has_error,
        used_fallback=used_fallback,
        applied_policy=applied_policy,
        stage_failures=stage_failures,
        answer_check=answer_check,
    )


CHAT_TRACE_KEEP = 300   # KB 당 최근 기록 수


async def _save_chat_trace(kb_id, query, answer, strategy, elapsed, has_error, used_fallback, logs, results, pipeline):
    try:
        from app.models.chat_trace import ChatTrace
        gm = next((r.get("graph_metadata") for r in (results or []) if (r.get("graph_metadata") or {}).get("reasoning")), None) \
            or next((r.get("graph_metadata") for r in (results or []) if r.get("graph_metadata")), None) or {}
        triples = [t for t in (gm.get("triples") or []) if isinstance(t, dict)][:150]
        chunks = [{"chunk_id": r.get("chunk_id"), "doc_id": (r.get("metadata") or {}).get("doc_id"),
                   "score": r.get("score"), "content": (r.get("content") or "")[:300]} for r in (results or [])[:15]]
        await ChatTrace(kb_id=kb_id, query=query, answer=answer or "", strategy=strategy, execution_time=round(elapsed, 2),
                        has_error=has_error, used_fallback=used_fallback, execution_log=[str(x)[:4000] for x in (logs or [])][:600],
                        reasoning=gm.get("reasoning") or {}, result_summary=gm.get("result_summary"),
                        triples=[{k: t.get(k) for k in ("subject", "predicate", "object", "chunk_ids")} for t in triples],
                        chunks=chunks, pipeline=pipeline).insert()
        old = await ChatTrace.find(ChatTrace.kb_id == kb_id).sort(-ChatTrace.created_at).skip(CHAT_TRACE_KEEP).to_list()
        for o in old:
            await o.delete()
    except Exception as e:
        print(f"[ChatTrace] 저장 실패: {e}")


@router.get("/{kb_id}/chat/traces")
async def list_chat_traces(kb_id: str, limit: int = 20):
    """최근 검색 기록 (질문·답변 요약·시간·전략)."""
    from app.models.chat_trace import ChatTrace
    rows = await ChatTrace.find(ChatTrace.kb_id == kb_id).sort(-ChatTrace.created_at).limit(max(1, min(limit, 100))).to_list()
    return [{"id": str(r.id), "query": r.query, "answer": r.answer[:300], "strategy": r.strategy,
             "execution_time": r.execution_time, "has_error": r.has_error, "used_fallback": r.used_fallback,
             "agentic": bool((r.reasoning or {}).get("agentic")), "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/{kb_id}/chat/traces/{trace_id}")
async def get_chat_trace(kb_id: str, trace_id: str):
    """검색 기록 하나 전체 — 실행 로그·추론 과정(스크래치패드)·트리플·청크."""
    from app.models.chat_trace import ChatTrace
    r = await ChatTrace.get(trace_id)
    if not r or r.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="기록 없음")
    d = r.model_dump(mode="json")
    d["id"] = str(r.id)
    return d

# ---------------------------------------------------------------------------
# 답변 스트리밍 (SSE) — 검색이 끝나면 결과를 먼저 보내고, 답변은 생성되는 대로 (첫 글자를 일찍 보여 준다)
# 이벤트: retrieval {chunks, execution_log} → token {t} … → done {ChatResponse} | error {detail}
# 게이트웨이 /ragaas/api/ 는 proxy_buffering off.
# ---------------------------------------------------------------------------

@router.post("/{kb_id}/chat/stream")
async def chat_with_kb_stream(kb_id: str, request: ChatRequest):
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import StreamingResponse
    q: asyncio.Queue = asyncio.Queue()
    token = _STREAM_QUEUE.set(q)
    try:
        task = asyncio.create_task(chat_with_kb(kb_id, request))   # 컨텍스트(큐)가 태스크로 복사된다
    finally:
        _STREAM_QUEUE.reset(token)

    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"

    async def gen():
        while True:
            getter = asyncio.create_task(q.get())
            done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                kind, payload = getter.result()
                yield sse(kind, {"t": payload} if kind == "token" else payload)
                continue
            getter.cancel()
            while not q.empty():   # 끝나기 직전에 들어온 조각
                kind, payload = q.get_nowait()
                yield sse(kind, {"t": payload} if kind == "token" else payload)
            try:
                resp = task.result()
                yield sse("done", resp)
            except HTTPException as e:
                yield sse("error", {"detail": e.detail, "status": e.status_code})
            except Exception as e:
                yield sse("error", {"detail": str(e)[:500]})
            break

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{kb_id}/chunks/{chunk_id}")
async def get_chunk(kb_id: str, chunk_id: str):
    """
    Fetch a single chunk content from Milvus by ID.
    Used for previewing chunk content in the Graph Data View.
    """
    from app.core.milvus import load_collection, run_milvus, MilvusUnavailableError, MILVUS_OP_TIMEOUT
    try:
        # Search for the chunk by chunk_id (VARCHAR), not internal id (INT64)
        expr = f'chunk_id == "{chunk_id}"'

        def _sync_query():
            collection = load_collection(kb_id)
            return collection.query(
                expr=expr,
                output_fields=["content", "metadata"],
                limit=1,
                timeout=MILVUS_OP_TIMEOUT,
            )

        res = await run_milvus(_sync_query, what="청크 조회")

        if not res:
            # Fallback: Try searching by id if implicit conversion works or for legacy reasons? 
            # But schema says id is INT64. Let's assume chunk_id is the correct field.
            raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")
            
        return res[0]
    except (HTTPException, MilvusUnavailableError):
        raise
    except Exception as e:
        print(f"[ChunkPreview] Error fetching chunk {chunk_id}: {e}")
        # Milvus error or connection error
        raise HTTPException(status_code=500, detail=_format_model_error_message(str(e)))
