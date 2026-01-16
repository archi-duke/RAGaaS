"""
Pipeline Executor - Sequential execution of search pipeline stages
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from app.schemas.pipeline import PipelineStage, PipelineConfig, StageContext


@dataclass
class ExecutionContext:
    """Runtime context for pipeline execution"""
    query: str
    kb_id: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    graph_backend: str = "ontology"
    metric_type: str = "COSINE"


class PipelineExecutor:
    """Execute search pipeline stages sequentially"""
    
    def __init__(self):
        # Stage handlers registry
        self._handlers = {
            "ann": self._execute_ann,
            "bm25": self._execute_bm25,
            "brute_force": self._execute_brute_force,
            "graph": self._execute_graph,
            "rerank": self._execute_rerank,
            "ner_filter": self._execute_ner_filter,
        }
    
    async def execute(
        self, 
        kb_id: str, 
        query: str, 
        config: PipelineConfig,
        graph_backend: str = "ontology",
        metric_type: str = "COSINE"
    ) -> ExecutionContext:
        """
        Execute all stages in the pipeline sequentially.
        
        Args:
            kb_id: Knowledge base ID
            query: Search query
            config: Pipeline configuration with stages
            graph_backend: Graph backend type (ontology/neo4j)
            metric_type: Vector metric type
            
        Returns:
            ExecutionContext with final results
        """
        ctx = ExecutionContext(
            query=query,
            kb_id=kb_id,
            graph_backend=graph_backend,
            metric_type=metric_type
        )
        
        log_msg = f"[Pipeline] Executing {len(config.stages)} stages for query: {query[:50]}..."
        print(log_msg)
        ctx.logs.append(log_msg)
        
        # Log the full pipeline config for verification
        ctx.logs.append(f"[Pipeline Configuration] {config}")
        
        for i, stage in enumerate(config.stages):
            handler = self._handlers.get(stage.type)
            if not handler:
                msg = f"[Pipeline] Unknown stage type: {stage.type}, skipping"
                print(msg)
                ctx.logs.append(msg)
                continue
                
            msg = f"[Pipeline] Stage {i+1}/{len(config.stages)}: {stage.type} (params: {stage.params})"
            print(msg)
            ctx.logs.append(msg)
            
            try:
                ctx = await handler(ctx, stage.params)
                msg = f"[Pipeline] Stage {stage.type} completed, {len(ctx.results)} results"
                print(msg)
                ctx.logs.append(msg)
            except Exception as e:
                msg = f"[Pipeline] Error in stage {stage.type}: {str(e)}"
                print(msg)
                ctx.logs.append(msg)
                # Decide whether to continue or break. For now, continuing with previous results might be safer or break.
                # Let's verify if we should stop. Generally pipeline failure should be noted.
        
        # Sort final results by the latest score
        if ctx.results:
            ctx.results.sort(key=lambda x: x.get('score', 0), reverse=True)
            
        return ctx
    
    async def _execute_ann(self, ctx: ExecutionContext, params: dict) -> ExecutionContext:
        """Execute ANN (vector) search stage"""
        from app.services.retrieval import retrieval_factory
        
        top_k = params.get("top_k", 10)
        threshold = params.get("threshold", 0.5)
        index_type = params.get("index_type", "IVF_FLAT")
        merge_mode = params.get("merge_mode", "union")
        
        strategy = retrieval_factory.get_strategy("ann")
        new_results = await strategy.search(
            ctx.kb_id,
            ctx.query,
            top_k,
            metric_type=ctx.metric_type,
            score_threshold=threshold,
            index_type=index_type
        )
        
        ctx.results = self._update_results_with_history(ctx.results, new_results, "ANN", merge_mode)
        return ctx
    
    async def _execute_bm25(self, ctx: ExecutionContext, params: dict) -> ExecutionContext:
        """Execute BM25 (keyword) search stage"""
        from app.services.retrieval import retrieval_factory
        
        top_k = params.get("top_k", 50)
        use_multi_pos = params.get("use_multi_pos", True)
        merge_mode = params.get("merge_mode", "union")
        
        strategy = retrieval_factory.get_strategy("keyword")
        new_results = await strategy.search(
            ctx.kb_id,
            ctx.query,
            top_k,
            use_multi_pos=use_multi_pos
        )
        
        ctx.results = self._update_results_with_history(ctx.results, new_results, "BM25", merge_mode)
        return ctx
    
    async def _execute_brute_force(self, ctx: ExecutionContext, params: dict) -> ExecutionContext:
        """Execute brute-force L2 re-ranking"""
        import numpy as np
        from app.services.embedding import embedding_service
        
        top_k = params.get("top_k", 3)
        threshold = params.get("threshold", 1.5)
        
        if not ctx.results:
            return ctx
        
        # Embed query
        query_embedding = (await embedding_service.get_embeddings([ctx.query]))[0]
        
        # Embed candidates
        candidate_contents = [r.get('content', '') for r in ctx.results]
        candidate_embeddings = await embedding_service.get_embeddings(candidate_contents)
        
        # Compute L2 distance and filter
        reranked = []
        for i, doc_emb in enumerate(candidate_embeddings):
            dist = float(np.linalg.norm(np.array(query_embedding) - np.array(doc_emb)))
            if dist <= threshold:
                chunk = ctx.results[i].copy()
                score = 1.0 / (1.0 + dist)
                chunk['score'] = score
                chunk['l2_score'] = dist
                
                # Update history
                if 'metadata' not in chunk: chunk['metadata'] = {}
                if 'score_history' not in chunk['metadata']: chunk['metadata']['score_history'] = {}
                chunk['metadata']['score_history']['BruteForce'] = score
                
                reranked.append(chunk)
        
        # Sort by score descending and take top_k (BruteForce explicitly re-ranks)
        reranked.sort(key=lambda x: x['score'], reverse=True)
        ctx.results = reranked[:top_k]
        return ctx
    
    async def _execute_graph(self, ctx: ExecutionContext, params: dict) -> ExecutionContext:
        """Execute graph search stage"""
        from app.services.retrieval import retrieval_factory
        
        hops = params.get("hops", 2)
        use_relation_filter = params.get("use_relation_filter", True)
        enable_inverse = params.get("enable_inverse", False)
        use_schema_mode = params.get("use_schema_mode", True)
        merge_mode = params.get("merge_mode", "union")
        
        strategy = retrieval_factory.get_strategy("hybrid_graph")
        new_results = await strategy.search(
            ctx.kb_id,
            ctx.query,
            top_k=10,
            metric_type=ctx.metric_type,
            enable_graph_search=True,
            graph_hops=hops,
            graph_backend=ctx.graph_backend,
            use_relation_filter=use_relation_filter,
            enable_inverse_search=enable_inverse,
            use_schema_mode=use_schema_mode
        )
        
        ctx.results = self._update_results_with_history(ctx.results, new_results, "Graph", merge_mode)
        
        # Store graph metadata if available
        if new_results and new_results[0].get("graph_metadata"):
            ctx.metadata["graph_metadata"] = new_results[0]["graph_metadata"]
        
        return ctx
    
    async def _execute_rerank(self, ctx: ExecutionContext, params: dict) -> ExecutionContext:
        """Execute reranking stage"""
        from app.services.retrieval import reranking_service
        
        top_k = params.get("top_k", 5)
        threshold = params.get("threshold", 0.0)
        use_llm = params.get("use_llm", False)
        llm_strategy = params.get("llm_strategy", "full")
        
        if not ctx.results:
            return ctx
        
        # Reranker completely replaces results and scores
        reranked_results = []
        if use_llm:
            reranked_results = await reranking_service.llm_rerank_results(
                query=ctx.query,
                results=ctx.results,
                top_k=top_k,
                threshold=threshold,
                strategy=llm_strategy
            )
        else:
            reranked_results = await reranking_service.rerank_results(
                query=ctx.query,
                results=ctx.results,
                top_k=top_k,
                threshold=threshold
            )
            
        # Update history for reranked items AND preserve previous history
        stage_name = "LLM Rerank" if use_llm else "Rerank"
        
        # specific to rerank: we need to merge back the history from ctx.results because reranker might return new dict objects
        existing_map = {r['chunk_id']: r for r in ctx.results}
        
        for r in reranked_results:
            if 'metadata' not in r: r['metadata'] = {}
            if 'score_history' not in r['metadata']: r['metadata']['score_history'] = {}
            
            # Restore previous history if available
            chunk_id = r.get('chunk_id')
            if chunk_id and chunk_id in existing_map:
                prev_history = existing_map[chunk_id].get('metadata', {}).get('score_history', {})
                # Merge previous history into current (current empty or has partial)
                # We use update to blindly copy over all previous stage scores
                if prev_history:
                    # Make sure not to overwrite if somehow already present, though typically safe to overwrite
                    for k, v in prev_history.items():
                        if k not in r['metadata']['score_history']:
                            r['metadata']['score_history'][k] = v
                            
            # Record current stage score
            r['metadata']['score_history'][stage_name] = r['score']
            
        ctx.results = reranked_results
        return ctx
    
    async def _execute_ner_filter(self, ctx: ExecutionContext, params: dict) -> ExecutionContext:
        """Execute NER filter stage - this filters, doesn't re-score usually"""
        from app.services.ner import ner_service
        
        penalty = params.get("penalty", 0.3)
        
        if not ctx.results:
            return ctx
        
        # NER filter modifies existing scores (apply penalty)
        ctx.results = ner_service.filter_by_entities(ctx.query, ctx.results, penalty=penalty)
        
        # Log the penalty application
        for r in ctx.results:
             if 'metadata' not in r: r['metadata'] = {}
             if 'score_history' not in r['metadata']: r['metadata']['score_history'] = {}
             # Record the post-penalty score
             r['metadata']['score_history']['NER Filter'] = r['score']
             
        return ctx
    
    def _update_results_with_history(
        self, 
        existing: List[dict], 
        new_results: List[dict], 
        stage_name: str,
        mode: str = "union"
    ) -> List[dict]:
        """
        Merge new search results update score history.
        Results are keyed by chunk_id.
        Final list is sorted by the NEW score from this stage (if present) or kept if not updated.
        """
        if not new_results and not existing:
            return []
            
        # Map existing by ID for easy access
        combined_map = {r['chunk_id']: r for r in existing}
        
        for new_r in new_results:
            chunk_id = new_r['chunk_id']
            score = new_r['score']
            
            if chunk_id in combined_map:
                # Update existing chunk
                chunk = combined_map[chunk_id]
                chunk['score'] = score # Update main score to latest
                
                # Merge metadata
                if 'metadata' not in chunk: chunk['metadata'] = {}
                if 'score_history' not in chunk['metadata']: chunk['metadata']['score_history'] = {}
                
                # Record history
                chunk['metadata']['score_history'][stage_name] = score
                
                # If new result has specific metadata like graph info, merge it
                if new_r.get('metadata'):
                     chunk['metadata'].update({k:v for k,v in new_r['metadata'].items() if k != 'score_history'})

            else:
                # New chunk found
                if mode == "union":
                    chunk = new_r
                    if 'metadata' not in chunk: chunk['metadata'] = {}
                    if 'score_history' not in chunk['metadata']: chunk['metadata']['score_history'] = {}
                    chunk['metadata']['score_history'][stage_name] = score
                    combined_map[chunk_id] = chunk
        
        # If intersection mode, filter map
        if mode == "intersection":
            new_ids = {r['chunk_id'] for r in new_results}
            combined_map = {k: v for k, v in combined_map.items() if k in new_ids}
            
        return list(combined_map.values())


# Singleton instance
pipeline_executor = PipelineExecutor()
