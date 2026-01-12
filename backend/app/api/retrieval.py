from fastapi import APIRouter, Depends, HTTPException
from app.schemas import RetrievalRequest, RetrievalResult
from app.services.retrieval import retrieval_factory, reranking_service
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from pydantic import BaseModel
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
    use_raw_log: bool = False
    
    class Config:
        extra = "ignore"

class ChatResponse(BaseModel):
    answer: str
    chunks: List[RetrievalResult]
    execution_time: float = 0.0
    strategy: str = "unknown"

@router.post("/{kb_id}/retrieve", response_model=List[RetrievalResult])
async def retrieve_chunks(
    kb_id: str,
    request: RetrievalRequest,
    db: AsyncSession = Depends(get_db)
):
    print(f"[DEBUG] Retrieve Request: brute={request.use_brute_force} bf_top_k={request.brute_force_top_k} bf_thresh={request.brute_force_threshold}")
    # Fetch KB to get metric_type
    from app.models.knowledge_base import KnowledgeBase
    result = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.id == kb_id))
    kb = result.scalars().first()
    
    with open("backend_debug.log", "a") as f:
        f.write(f"\n--- REQ ---\nDefault TopK: {request.top_k}\nBF: {request.use_brute_force}\n")
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
        
    metric_type = kb.metric_type or "COSINE"

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
        # Graph specific
        enable_inverse_search=request.enable_inverse_search,
        inverse_extraction_mode=request.inverse_extraction_mode,
        use_relation_filter=request.use_relation_filter
    )
    
    # 2. Reranking (Cross-Encoder)
    # Different logic for 2-stage as it's built-in, but separate reranker can still apply if requested explicitly
    # adhering to original logic: if use_reranker and NOT 2-stage (which has it built in)
    if request.use_reranker and request.strategy != "2-stage" and results:
        print(f"[DEBUG] Applying reranker: top_k={request.reranker_top_k}, threshold={request.reranker_threshold}")
        
        if request.use_llm_reranker:
            results = await reranking_service.llm_rerank_results(
                query=request.query,
                results=results,
                top_k=request.reranker_top_k,
                threshold=request.reranker_threshold,
                strategy=request.llm_chunk_strategy
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
        
    # 3.5. Flat Index (L2) Re-ranking (Exact L2 Distance on Candidates)
    if request.use_brute_force and results:
        from app.services.embedding import embedding_service
        import numpy as np
        
        print(f"[DEBUG] Applying Flat Index L2 Re-ranking (Top K: {request.brute_force_top_k}, Threshold (Max Dist): {request.brute_force_threshold})")
        
        # 1. Embed query
        query_embedding = (await embedding_service.get_embeddings([request.query]))[0]
        
        # 2. Embed content of candidates
        candidate_contents = [r['content'] for r in results]
        candidate_embeddings = await embedding_service.get_embeddings(candidate_contents)
        
        # 3. Compute L2 Distance
        reranked = []
        for i, doc_embedding in enumerate(candidate_embeddings):
            # L2 Metric
            vec1 = np.array(query_embedding)
            vec2 = np.array(doc_embedding)
            dist = float(np.linalg.norm(vec1 - vec2))
            
            # Apply threshold (LOWER is better for L2)
            if dist <= request.brute_force_threshold:
                # Update score to Similarity Score (Higher is better)
                try:
                    sim_score = 1.0 / (1.0 + dist)
                except:
                    sim_score = 0.0
                
                # Safety check for NaN
                if np.isnan(sim_score) or np.isinf(sim_score):
                    sim_score = 0.0
                if np.isnan(dist) or np.isinf(dist):
                    pass # Allow NaN dist if score is handled
                
                chunk = results[i].copy()
                chunk['score'] = float(sim_score)
                chunk['l2_score'] = float(dist) if not np.isnan(dist) else None
                reranked.append(chunk)
        
        # 4. Sort and Top K (DESCENDING for Similarity)
        reranked.sort(key=lambda x: x['score'], reverse=True)
        results = reranked[:request.brute_force_top_k]
        
    return results

@router.post("/{kb_id}/chat", response_model=ChatResponse)
async def chat_with_kb(
    kb_id: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    start_time = time.time()
    print(f"[DEBUG] Chat Request: brute={request.use_brute_force} bf_top_k={request.brute_force_top_k} bf_thresh={request.brute_force_threshold}")
    """
    Chat endpoint that retrieves relevant chunks and generates an LLM response
    """
    # First, retrieve relevant chunks using the same logic as retrieve_chunks
    from app.models.knowledge_base import KnowledgeBase
    result = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.id == kb_id))
    kb = result.scalars().first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
        
    metric_type = kb.metric_type or "COSINE"
    
    # Auto-enable graph search if KB has Graph RAG enabled
    use_graph_search = request.enable_graph_search
    if kb.enable_graph_rag and kb.graph_backend:
        use_graph_search = True
        print(f"[DEBUG] Auto-enabled graph search for KB with graph_backend={kb.graph_backend}")

    # 1. Retrieve chunks
    strategy = retrieval_factory.get_strategy(request.strategy)
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
        use_raw_log=request.use_raw_log
    )
    
    with open("backend_debug.log", "a") as f:
        f.write(f"Strategy: {request.strategy}, Initial Results: {len(results) if results else 0}\n")

    # 2. Reranking
    if request.use_reranker and request.strategy != "2-stage" and results:
        if request.use_llm_reranker:
            results = await reranking_service.llm_rerank_results(
                query=request.query,
                results=results,
                top_k=request.reranker_top_k,
                threshold=request.reranker_threshold,
                strategy=request.llm_chunk_strategy
            )
        else:
            results = await reranking_service.rerank_results(
                query=request.query,
                results=results,
                top_k=request.reranker_top_k,
                threshold=request.reranker_threshold
            )

    if request.use_ner and results:
        from app.services.ner import ner_service
        results = ner_service.filter_by_entities(request.query, results, penalty=0.3)
        
    # 3.5. Flat Index (L2) Re-ranking (Exact L2 Distance on Candidates)
    if request.use_brute_force and results:
        with open("backend_debug.log", "a") as f:
            f.write(f"Entering BF Block. Results: {len(results)}\n")
            
        from app.services.embedding import embedding_service
        import numpy as np
        
        print(f"[DEBUG] Applying Flat Index L2 Re-ranking (Top K: {request.brute_force_top_k}, Threshold (Max Dist): {request.brute_force_threshold})")
        
        # 1. Embed query
        query_embedding = (await embedding_service.get_embeddings([request.query]))[0]
        
        # 2. Embed content of candidates
        candidate_contents = [r['content'] for r in results]
        candidate_embeddings = await embedding_service.get_embeddings(candidate_contents)
        
        # 3. Compute L2 Distance
        reranked = []
        debug_dists = []
        for i, doc_embedding in enumerate(candidate_embeddings):
            # L2 Metric
            vec1 = np.array(query_embedding)
            vec2 = np.array(doc_embedding)
            dist = float(np.linalg.norm(vec1 - vec2))
            debug_dists.append(dist)
            
            print(f"[DEBUG] L2: {dist:.4f} vs Threshold: {request.brute_force_threshold:.4f} -> {'KEEP' if dist <= request.brute_force_threshold else 'DROP'}")
            
            # Apply threshold (LOWER is better for L2)
            if dist <= request.brute_force_threshold:
                # Update score to Similarity Score (Higher is better)
                # Convert L2 distance to a 0-1 similarity score for consistent sorting/display
                try:
                    sim_score = 1.0 / (1.0 + dist)
                except:
                    sim_score = 0.0
                
                # Safety check for NaN
                if np.isnan(sim_score) or np.isinf(sim_score):
                    sim_score = 0.0
                if np.isnan(dist) or np.isinf(dist):
                    pass # Keep dist as is for debug or set to -1? Pydantic allows Inf for float, but NaN -> Null.
                         # But dist is sent as l2_score. 
                         # If dist is NaN/Inf, let's allow it but ensure score is valid.
                
                chunk = results[i].copy()
                chunk['score'] = float(sim_score)
                chunk['l2_score'] = float(dist) if not np.isnan(dist) else None
                reranked.append(chunk)
        
        # 4. Sort and Top K (DESCENDING for Similarity)
        reranked.sort(key=lambda x: x['score'], reverse=True)
        results = reranked[:request.brute_force_top_k]
        
        if not results and candidate_contents:
             debug_msg = f"BF Filtered All! Threshold: {request.brute_force_threshold}. Dists: {debug_dists}"
             with open("backend_debug.log", "a") as f:
                 f.write(f"BF Cut All: {debug_dists}\n")
             raise HTTPException(status_code=418, detail=debug_msg)
             
        with open("backend_debug.log", "a") as f:
            f.write(f"BF Final Results: {len(results)}\n")
    
    # 4. Generate LLM response based on retrieved chunks
    if not results:
        return ChatResponse(
            answer="I couldn't find any relevant information to answer your question.",
            chunks=[]
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
    
    # Call OpenAI API
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")
    
    client = openai.OpenAI(api_key=openai_api_key)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that answers questions based on the provided context. "
                               "The context generally consists of Korean documents. "
                               "Regardless of the language of the system instructions, YOU MUST ANSWER IN KOREAN (한국어). "
                               "If multiple entities or items match the question, LIST ALL OF THEM. "
                               "When asked about 'participants' or 'users' of a skill/item, ALSO INCLUDE its 'creators', 'masters', or 'teachers' mentioned in the context. "
                               "If the context doesn't contain enough information to answer the question, say so. "
                               "Always cite which chunks you used (e.g., '[Chunk 1]에 따르면...')."
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
    
    return ChatResponse(
        answer=answer,
        chunks=results,
        execution_time=time.time() - start_time,
        strategy=f"{request.strategy}{' (+Graph)' if request.enable_graph_search else ''}"
    )
