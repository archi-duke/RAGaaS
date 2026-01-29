from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class RetrievalRequest(BaseModel):
    query: str
    top_k: int = 5
    score_threshold: float = 0.5
    strategy: str = "ann"  # keyword, ann, hybrid, 2-stage
    
    # Reranking
    use_reranker: bool = False
    reranker_top_k: int = 5
    reranker_threshold: float = 0.0
    use_llm_reranker: bool = False
    llm_chunk_strategy: str = "full"
    
    # Filters
    use_ner: bool = False
    use_llm_keyword_extraction: bool = False
    use_multi_pos: bool = True  # Multi-POS tokenization (nouns + verbs + adjectives)
    bm25_top_k: int = 50  # Candidates for Hybrid 2nd stage
    use_parallel_search: bool = False # If True, run BM25 and ANN in parallel and fuse. If False, run sequential.
    
    # Graph Search
    enable_graph_search: bool = False
    graph_hops: int = 2
    enable_inverse_search: bool = False
    inverse_extraction_mode: str = "auto"
    use_relation_filter: bool = True
    use_raw_log: bool = False
    custom_query_prompt: Optional[str] = None
    
    # Brute Force
    use_brute_force: bool = False
    brute_force_top_k: int = 1
    brute_force_threshold: float = 1.5


class RetrievalResult(BaseModel):
    chunk_id: str
    content: str
    score: float
    l2_score: Optional[float] = None
    metadata: Dict[str, Any] = {}
    graph_metadata: Optional[Dict[str, Any]] = None
