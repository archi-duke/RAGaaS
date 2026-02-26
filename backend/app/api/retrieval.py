from fastapi import APIRouter, Depends, HTTPException
from app.schemas import RetrievalRequest, RetrievalResult
from app.services.retrieval import retrieval_factory, reranking_service
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
import openai
import os
import time

router = APIRouter()

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
    use_dynamic_schema: bool = False  # Dynamic schema injection for non-promoted KBs
    use_raw_log: bool = False
    
    # Pipeline configuration (optional - if provided, uses pipeline executor)
    pipeline: Optional[dict] = None
    
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
        raise HTTPException(status_code=500, detail=str(e))


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
    )
    
    # 2. Reranking (Cross-Encoder)
    rerank_llm_config = request.pipeline_model_config or request.frontend_model_config or {}
    if request.use_reranker and request.strategy != "2-stage" and results:
        print(f"[DEBUG] Applying reranker: top_k={request.reranker_top_k}, threshold={request.reranker_threshold}")
        
        if request.use_llm_reranker:
            results = await reranking_service.llm_rerank_results(
                query=request.query,
                results=results,
                top_k=request.reranker_top_k,
                threshold=request.reranker_threshold,
                strategy=request.llm_chunk_strategy,
                llm_model_config=rerank_llm_config or kb.llm_model_config or {},
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
        
    metric_type = kb.metric_type or "COSINE"
    kb_emb_service = await get_embedding_service(kb)

    # Check if pipeline mode is enabled
    pipeline_config = None
    if request.pipeline:
        # Use provided pipeline
        pipeline_config = request.pipeline
        print(f"[Pipeline] Using request-provided pipeline with {len(pipeline_config.get('stages', []))} stages")
    elif kb.pipeline_config and kb.pipeline_config.get("stages"):
        # Use KB's saved pipeline
        pipeline_config = kb.pipeline_config
        print(f"[Pipeline] Using KB saved pipeline with {len(pipeline_config.get('stages', []))} stages")
    
    execution_logs = []
    
    # Pipeline mode execution
    if pipeline_config and pipeline_config.get("stages"):
        from app.services.retrieval.pipeline_executor import pipeline_executor
        from app.schemas.pipeline import PipelineConfig, PipelineStage
        
        # Convert dict to PipelineConfig
        stages = [PipelineStage(**s) for s in pipeline_config["stages"]]
        config = PipelineConfig(stages=stages)
        
        llm_config = request.pipeline_model_config or request.frontend_model_config
        exec_ctx = await pipeline_executor.execute(
            kb_id=kb_id,
            query=request.query,
            config=config,
            graph_backend=kb.graph_backend or "ontology",
            metric_type=metric_type,
            embedding_service=kb_emb_service,
            llm_model_config=llm_config or kb.llm_model_config or {},
        )
        
        results = exec_ctx.results
        execution_logs = exec_ctx.logs
        graph_metadata = exec_ctx.metadata.get("graph_metadata")
        
        # Attach graph metadata to first result if present
        if graph_metadata and results:
            results[0]["graph_metadata"] = graph_metadata
    else:
        # Legacy mode (backward compatibility)
        # Auto-enable graph search if KB has Graph RAG enabled
        use_graph_search = request.enable_graph_search
        target_strategy = request.strategy
        
        execution_logs.append("[Legacy] No pipeline config. Using legacy strategy execution.")
        execution_logs.append(f"[Legacy] Strategy: {target_strategy}")
        
        if kb.enable_graph_rag and kb.graph_backend:
            use_graph_search = True
            if target_strategy == 'ann' or target_strategy == 'vector':
                target_strategy = 'hybrid'
            print(f"[DEBUG] Auto-enabled graph search for KB with graph_backend={kb.graph_backend}. Strategy switched to '{target_strategy}'")
            execution_logs.append(f"[Legacy] Auto-enabled graph search (Backend: {kb.graph_backend}). Strategy switched to '{target_strategy}'")

        # 1. Retrieve chunks
        llm_config = request.pipeline_model_config or request.frontend_model_config
        strategy = retrieval_factory.get_strategy(target_strategy)
        results = await strategy.search(
            kb_id, 
            request.query, 
            request.top_k, 
            metric_type=metric_type, 
            score_threshold=request.score_threshold,
            enable_graph_search=use_graph_search,
            graph_hops=request.graph_hops,
            graph_backend=kb.graph_backend or "ontology",
            use_llm_keyword_extraction=request.use_llm_keyword_extraction,
            use_multi_pos=request.use_multi_pos,
            bm25_top_k=request.bm25_top_k,
            use_parallel_search=request.use_parallel_search,
            use_relation_filter=request.use_relation_filter,
            enable_inverse_search=request.enable_inverse_search,
            inverse_extraction_mode=request.inverse_extraction_mode,
            use_schema_mode=request.use_schema_mode,
            use_raw_log=request.use_raw_log,
            execution_logs=execution_logs,
            embedding_service=kb_emb_service,
            llm_model_config=llm_config or kb.llm_model_config or {},
        )
        execution_logs.append(f"[Legacy] Search complete. Found {len(results)} chunks.")
        
        # [Trace Log Integration] Merge graph trace_logs into execution_logs
        if results:
            for res in results:
                if res.get("graph_metadata") and res["graph_metadata"].get("trace_logs"):
                    execution_logs.extend(res["graph_metadata"]["trace_logs"])
                    break  # Only need to get trace_logs once (it's the same for all)
        
        # 2. Reranking (legacy)
        if request.use_reranker and request.strategy != "2-stage" and results:
            execution_logs.append(f"[Legacy] Applying Reranker (Top K: {request.reranker_top_k})")
            if request.use_llm_reranker:
                results = await reranking_service.llm_rerank_results(
                    query=request.query,
                    results=results,
                    top_k=request.reranker_top_k,
                    threshold=request.reranker_threshold,
                    strategy=request.llm_chunk_strategy,
                    llm_model_config=llm_config or kb.llm_model_config or {},
                )
            else:
                results = await reranking_service.rerank_results(
                    query=request.query,
                    results=results,
                    top_k=request.reranker_top_k,
                    threshold=request.reranker_threshold
                )

        # 3. NER Filter (legacy)
        if request.use_ner and results:
            from app.services.ner import ner_service
            execution_logs.append("[Legacy] Applying NER Filter")
            results = ner_service.filter_by_entities(request.query, results, penalty=0.3)
            
        # 3.5. Brute Force (legacy)
        if request.use_brute_force and results:
            from app.services.embedding import embedding_service
            import numpy as np
            
            execution_logs.append(f"[Legacy] Applying Brute Force L2 (Top K: {request.brute_force_top_k})")
            
            query_embedding = (await embedding_service.get_embeddings([request.query]))[0]
            candidate_contents = [r['content'] for r in results]
            candidate_embeddings = await embedding_service.get_embeddings(candidate_contents)
            
            reranked = []
            for i, doc_embedding in enumerate(candidate_embeddings):
                vec1 = np.array(query_embedding)
                vec2 = np.array(doc_embedding)
                dist = float(np.linalg.norm(vec1 - vec2))
                
                if dist <= request.brute_force_threshold:
                    chunk = results[i].copy()
                    chunk['score'] = 1.0 / (1.0 + dist)
                    chunk['l2_score'] = dist
                    reranked.append(chunk)
            
            reranked.sort(key=lambda x: x['score'], reverse=True)
            results = reranked[:request.brute_force_top_k]
    
    with open("backend_debug.log", "a") as f:
        f.write(f"Strategy: {request.strategy}, Final Results: {len(results) if results else 0}\\n")
    
    async def get_openai_client(config: Optional[dict]):
        """ModelConfig를 기반으로 OpenAI 호환 클라이언트 생성."""
        from app.core.models_resolver import resolve_model_config
        resolved = await resolve_model_config(config)
        api_key = resolved["api_key"]
        base_url = resolved["base_url"]
        model = resolved["model"]
        extra_headers = resolved.get("extra_headers") or {}
        if not api_key:
            raise HTTPException(status_code=500, detail="LLM API key (OpenAI or Custom) not configured")
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if extra_headers:
            kwargs["default_headers"] = extra_headers
        client = openai.OpenAI(**kwargs)
        return client, model

    # 4. Generate LLM response based on retrieved chunks
    if not results:
        return ChatResponse(
            answer="I couldn't find any relevant information to answer your question.",
            chunks=[],
            execution_log=execution_logs,
            pipeline_config=pipeline_config
        )
    
    # Build context from top chunks
    context_parts = []
    
    # Check for graph metadata in the first result (where it's attached)
    if results and results[0].get("graph_metadata"):
        metadata = results[0]["graph_metadata"]
        triples = metadata.get("triples", [])
        if triples:
            # Check type of triples
            # Graph logic might return strings like "(s) -[p]-> (o)" OR dicts
            formatted_triples = []
            for t in triples:
                if isinstance(t, str):
                    formatted_triples.append(f"- {t}")
                elif isinstance(t, dict):
                    formatted_triples.append(f"- {t.get('subject', '?')} {t.get('predicate', '?')} {t.get('object', '?')}")
            
            triples_text = "\n".join(formatted_triples)
            context_parts.append(f"### Graph Relationships (Derived from Knowledge Graph):\n{triples_text}\n")
            
    context_parts.extend([
        f"[Chunk {i+1}] {chunk['content']}"
        for i, chunk in enumerate(results[:10])  # Use top 10 chunks for context
    ])
    
    context = "\n\n".join(context_parts)

    # LLM 모델 설정: model_config (프론트) / pipeline_model_config (백엔드) 호환
    llm_config = request.pipeline_model_config or request.frontend_model_config
    
    client, llm_model = await get_openai_client(llm_config)
    
    system_prompt = _load_chat_system_prompt()

    try:
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {request.query}\n\nPlease provide a comprehensive answer based on the context above. If there are multiple answers, please list them all."
                }
            ],
            temperature=0.3,
            max_tokens=1000
        )
        answer = response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate response: {str(e)}")
    
    # Determine display strategy name
    if pipeline_config and pipeline_config.get("stages"):
        # Pipeline Mode
        stage_names = []
        for stage in pipeline_config["stages"]:
            s_type = stage.get("type", "unknown").upper()
            if s_type == "ANN": s_type = "Vector"
            stage_names.append(s_type)
        display_strategy = " → ".join(stage_names)
    else:
        # Standard Mode - Mapping to user-friendly names
        base_strategy = request.strategy.lower()
        strategy_map = {
            "hybrid": "Hybrid",
            "keyword": "Keyword",
            "ann": "Vector",
            "vector": "Vector",
            "2-stage": "2-Stage (L2)"
        }
        name = strategy_map.get(base_strategy, base_strategy.capitalize())
        
        if request.enable_graph_search or (kb.enable_graph_rag and kb.graph_backend):
            display_strategy = f"Graph → {name}"
        else:
            display_strategy = name
    
    # Detect error and fallback states from execution logs
    has_error = False
    used_fallback = False
    for log_entry in execution_logs:
        log_lower = log_entry.lower()
        if "error" in log_lower or "failed" in log_lower or "generation failed" in log_lower:
            has_error = True
        if "fallback" in log_lower or "entity-guided" in log_lower:
            # Exclude false positives like "No fallback search performed"
            if "no fallback" not in log_lower and "fallback search disabled" not in log_lower:
                used_fallback = True
    
    return ChatResponse(
        answer=answer,
        chunks=results,
        execution_time=time.time() - start_time,
        strategy=display_strategy,
        execution_log=execution_logs,
        pipeline_config=pipeline_config,
        has_error=has_error,
        used_fallback=used_fallback
    )

@router.get("/{kb_id}/chunks/{chunk_id}")
async def get_chunk(kb_id: str, chunk_id: str):
    """
    Fetch a single chunk content from Milvus by ID.
    Used for previewing chunk content in the Graph Data View.
    """
    from app.core.milvus import create_collection
    try:
        # Load collection (using create_collection handles name mapping and loading)
        collection = create_collection(kb_id)
        collection.load()
        
        # Search for the chunk by chunk_id (VARCHAR), not internal id (INT64)
        expr = f'chunk_id == "{chunk_id}"'
        res = collection.query(
            expr=expr,
            output_fields=["content", "metadata"],
            limit=1
        )
        
        if not res:
            # Fallback: Try searching by id if implicit conversion works or for legacy reasons? 
            # But schema says id is INT64. Let's assume chunk_id is the correct field.
            raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")
            
        return res[0]
    except Exception as e:
        print(f"[ChunkPreview] Error fetching chunk {chunk_id}: {e}")
        # Milvus error or connection error
        raise HTTPException(status_code=500, detail=str(e))
