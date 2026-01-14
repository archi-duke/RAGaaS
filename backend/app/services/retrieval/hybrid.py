from typing import List, Dict, Any
from .base import RetrievalStrategy
from .vector import VectorRetrievalStrategy
from .graph import GraphRetrievalStrategy
from app.core.milvus import create_collection
from app.services.embedding import embedding_service
from rank_bm25 import BM25Okapi
import numpy as np

class HybridRetrievalStrategy(RetrievalStrategy):
    """Combines BM25, Vector, and optional Graph Search results."""
    
    def __init__(self):
        self.vector_strategy = VectorRetrievalStrategy()
        self.graph_strategy = GraphRetrievalStrategy()

    async def search(self, kb_id: str, query: str, top_k: int, **kwargs) -> List[Dict[str, Any]]:
        metric_type = kwargs.get("metric_type", "COSINE")
        score_threshold = kwargs.get("score_threshold", 0.0)
        enable_graph = kwargs.get("enable_graph_search", False)
        
        collection = create_collection(kb_id)
        collection.load()
        
        # 1. Embed query
        query_vectors = await embedding_service.get_embeddings([query])
        query_vec = query_vectors[0]
        
        # 2. Fetch all docs for BM25 (Note: Not scalable for huge datasets, okay for MVP)
        all_docs = collection.query(
            expr="chunk_id != ''",
            output_fields=["content", "doc_id", "chunk_id", "vector"],
            limit=10000 
        )
        
        if not all_docs:
            return []
        
        # Use shared tokenizer utility - choose mode based on use_multi_pos
        from app.services.retrieval.tokenizer import korean_tokenize
        use_multi_pos = kwargs.get("use_multi_pos", True)
        tokenize_mode = 'extended' if use_multi_pos else 'strict'
        print(f"[Hybrid] use_multi_pos={use_multi_pos}, tokenize_mode={tokenize_mode}")

        # Optional: LLM Keyword Extraction
        use_llm_kw = kwargs.get("use_llm_keyword_extraction", False)
        search_query = query
        
        # CORPUS TOKENIZATION (mode depends on use_multi_pos)
        corpus = [doc["content"] for doc in all_docs]
        tokenized_corpus = [korean_tokenize(content, mode=tokenize_mode, include_original_words=False, min_length=1) for content in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        
        # QUERY TOKENIZATION
        if use_llm_kw:
             # If LLM is ON, use LLM logic
             from app.services.retrieval.keyword import KeywordRetrievalStrategy
             ks = KeywordRetrievalStrategy()
             search_query = await ks.extract_keywords_with_llm(query)
             tokenized_query = search_query.split()
        else:
             # If Multi-POS (extended): Verbs + Adjectives included by Kiwi
             # If Legacy (strict): Nouns only
             # Force include_original_words=False to avoid noise like "사용하"
             tokenized_query = korean_tokenize(search_query, mode=tokenize_mode, include_original_words=False, min_length=1)

        bm25_scores = bm25.get_scores(tokenized_query)
        
        bm25_candidates = []
        for idx, score in enumerate(bm25_scores):
            if score > 0:
                bm25_candidates.append({"idx": idx, "bm25_score": float(score)})
        
        bm25_candidates.sort(key=lambda x: x["bm25_score"], reverse=True)
        
        # === Parallel Mode (Original RRF) ===
        if kwargs.get("use_parallel_search", False):
            print("[Hybrid] Using Parallel Search Mode")
            rrf_k = 60
            chunk_scores = {} # cid -> RRF score
            
            # 1. Rank BM25 Results
            top_bm25 = bm25_candidates[:top_k * 3]
            for rank, item in enumerate(top_bm25):
                idx = item["idx"]
                doc = all_docs[idx]
                cid = doc["chunk_id"]
                if cid not in chunk_scores: chunk_scores[cid] = 0.0
                chunk_scores[cid] += 1.0 / (rrf_k + rank + 1)
                
            # 2. Rank Vector Results (Independent Search)
            ann_results = await self.vector_strategy.search(kb_id, query, top_k=top_k * 3, metric_type=metric_type, score_threshold=score_threshold)
            
            for rank, res in enumerate(ann_results):
                cid = res["chunk_id"]
                if cid not in chunk_scores: chunk_scores[cid] = 0.0
                chunk_scores[cid] += 1.0 / (rrf_k + rank + 1)
                
            # 3. Rank Graph Results
            graph_metadata = None
            chunk_to_graph_meta = {}
            
            if enable_graph:
                graph_results = await self.graph_strategy.search(kb_id, query, top_k=top_k * 3, **kwargs)
                real_graph_results = []
                
                for res in graph_results:
                    if res.get("chunk_id") == "GRAPH_METADATA_ONLY":
                        if "graph_metadata" in res:
                            graph_metadata = res["graph_metadata"]
                    else:
                        real_graph_results.append(res)
                        if "graph_metadata" in res and not graph_metadata:
                             graph_metadata = res["graph_metadata"]
                        if res.get("chunk_id"):
                            chunk_to_graph_meta[res["chunk_id"]] = res.get("graph_metadata")

                for rank, res in enumerate(real_graph_results):
                    cid = res["chunk_id"]
                    if cid not in chunk_scores: chunk_scores[cid] = 0.0
                    chunk_scores[cid] += 1.0 / (rrf_k + rank + 1)
            
            # 4. Sort and Build Results
            sorted_chunks = sorted(chunk_scores.items(), key=lambda x: x[1], reverse=True)
            top_ids = [cid for cid, score in sorted_chunks[:top_k]]
            
            final_results = []
            chunk_id_to_doc = {d["chunk_id"]: d for d in all_docs}
            
            # Also need to consider docs found by ANN that might not be in all_docs (if all_docs limited to 10000)
            # But all_docs query is limit 10000, so it should cover most. 
            # If ANN finds something not in all_docs (e.g. if we fetched BM25 separately), we might miss content.
            # However, vector_strategy returns content, so we can use that if needed.
            # Let's rely on chunk_id_to_doc for now, or fallback to ANN result content.
            
            ann_result_map = {r["chunk_id"]: r for r in ann_results}
            graph_result_map = {r["chunk_id"]: r for r in real_graph_results} if enable_graph else {}
            
            for cid in top_ids:
                content = ""
                doc_id = ""
                
                if cid in chunk_id_to_doc:
                    content = chunk_id_to_doc[cid]["content"]
                    doc_id = chunk_id_to_doc[cid]["doc_id"]
                elif cid in ann_result_map:
                    content = ann_result_map[cid]["content"]
                    doc_id = ann_result_map[cid].get("doc_id", "")
                elif cid in graph_result_map:
                    content = graph_result_map[cid].get("content", "")
                    doc_id = graph_result_map[cid].get("metadata", {}).get("doc_id", "")
                
                if not content: continue
                
                final_results.append({
                    "chunk_id": cid,
                    "content": content,
                    "doc_id": doc_id,
                    "score": chunk_scores[cid],
                    "metadata": {
                        "extracted_keywords": tokenized_query
                    },
                    "graph_metadata": chunk_to_graph_meta.get(cid) or graph_metadata
                })
                
            return final_results

        # === Sequential Mode (BM25 Candidates -> Vector Rescore) ===
        print("[Hybrid] Using Sequential Search Mode")
        
        # 1-2. Select BM25 Candidates
        bm25_limit = kwargs.get("bm25_top_k", 50)
        top_bm25_items = bm25_candidates[:bm25_limit]
        
        candidate_map = {} # chunk_id -> {doc_data, bm25_score, graph_score}
        
        for item in top_bm25_items:
            idx = item["idx"]
            doc = all_docs[idx]
            cid = doc["chunk_id"]
            if cid not in candidate_map:
                candidate_map[cid] = {
                    "doc": doc,
                    "bm25_score": item["bm25_score"],
                    "graph_metadata": None,
                    "vector_score": 0.0
                }

        # 4. Graph Search (Optional) & Add to Candidates
        graph_metadata = None
        if enable_graph:
            # Graph search returns results based on graph traversal
            graph_results = await self.graph_strategy.search(kb_id, query, top_k=top_k * 3, **kwargs)
            
            for res in graph_results:
                if res.get("chunk_id") == "GRAPH_METADATA_ONLY":
                    if "graph_metadata" in res:
                        graph_metadata = res["graph_metadata"]
                else:
                    if "graph_metadata" in res and not graph_metadata:
                        graph_metadata = res["graph_metadata"]

                    cid = res["chunk_id"]
                    # Find doc content for graph result
                    doc_entry = next((d for d in all_docs if d["chunk_id"] == cid), None)
                    
                    if doc_entry:
                        if cid not in candidate_map:
                             candidate_map[cid] = {
                                "doc": doc_entry,
                                "bm25_score": 0.0,
                                "graph_metadata": res.get("graph_metadata"),
                                "vector_score": 0.0,
                                "original_metadata": res.get("metadata", {})
                            }
                    elif "content" in res:
                        # Fallback: Use content from graph result itself
                        if cid not in candidate_map:
                             candidate_map[cid] = {
                                "doc": {
                                    "content": res["content"],
                                    "doc_id": res.get("metadata", {}).get("doc_id", ""),
                                    "vector": res.get("vector") # Might be missing, handle below
                                },
                                "bm25_score": 0.0,
                                "graph_metadata": res.get("graph_metadata"),
                                "vector_score": 0.0,
                                "original_metadata": res.get("metadata", {})
                            }
                        else:
                            # Update existing candidate with graph metadata
                            candidate_map[cid]["graph_metadata"] = res.get("graph_metadata")
                            # Merge original metadata (preserve source if graph found it)
                            if "original_metadata" not in candidate_map[cid]:
                                candidate_map[cid]["original_metadata"] = {}
                            candidate_map[cid]["original_metadata"].update(res.get("metadata", {}))

        # 5. Vector Scoring (Re-ranking) on Candidates
        # Calculate Cosine Similarity between Query Vector and Candidate Vectors
        
        # Prepare vectors
        candidate_cids = list(candidate_map.keys())
        if not candidate_cids:
            return []
            
        final_results = []
        
        for cid in candidate_cids:
            item = candidate_map[cid]
            doc_vec = item["doc"]["vector"]
            
            # Skip if no vector (should not happen)
            if not doc_vec:
                continue
                
            # Cosine Similarity
            vec1 = np.array(query_vec)
            vec2 = np.array(doc_vec)
            
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 > 0 and norm2 > 0:
                sim = np.dot(vec1, vec2) / (norm1 * norm2)
            else:
                sim = 0.0
            
            # Apply Score Threshold?
            # If using RRF within candidates, we might want to keep low vector score items 
            # if they have high BM25 score. So we skip strict threshold filtering here,
            # or apply it loosely. Let's Apply it only if BM25 score is also low?
            # For now, let's skip threshold filtering for candidates to allow RRF to do its job.
            # checks: Only filter if vector score is REALLY low (e.g. 0) AND user wanted filtering.
            # But "Duke" vector score might be 0.2 while threshold is 0.6.
            # Let's keep all candidates.
                
            item["vector_score"] = float(sim)
            
        # 5.5. Compute RRF within Candidates
        # We have BM25 Rank (from top_bm25_items order) and Vector Rank (need to sort)
        
        # Sort by Vector Score to get Vector Rank
        # Create a list of (cid, vector_score)
        vec_ranking = [(cid, candidate_map[cid]["vector_score"]) for cid in candidate_cids]
        vec_ranking.sort(key=lambda x: x[1], reverse=True)
        
        # Map cid -> vector rank (0-based)
        cid_to_vec_rank = {cid: i for i, (cid, score) in enumerate(vec_ranking)}
        
        # Map cid -> bm25 rank (0-based)
        # top_bm25_items is already sorted by BM25
        # Note: top_bm25_items contains {idx, bm25_score}
        # We need to map cid back from idx... allow efficient lookup?
        # Actually top_bm25_items iteration order determines rank.
        cid_to_bm25_rank = {}
        for rank, item in enumerate(top_bm25_items):
             idx = item["idx"]
             # We need to get cid from idx again (or store it earlier)
             # Accessing all_docs[idx] again is cheap (list access)
             doc = all_docs[idx]
             cid = doc["chunk_id"]
             # If duplicate cids exist in bm25 results? (Usually one doc one chunk... wait chunk_id is unique)
             if cid not in cid_to_bm25_rank:
                 cid_to_bm25_rank[cid] = rank
        
        # Compute Output RRF
        rrf_k = 60
        final_results = []
        
        for cid in candidate_cids:
            item = candidate_map[cid]
            
            bm25_rank = cid_to_bm25_rank.get(cid, 9999)
            vec_rank = cid_to_vec_rank.get(cid, 9999)
            
            # RRF Formula
            rrf_score = (1.0 / (rrf_k + bm25_rank + 1)) + (1.0 / (rrf_k + vec_rank + 1))
            
            # Additional Boost from Graph
            if item["graph_metadata"]:
                # Boost graph results significantly to ensure they appear?
                # Or just treat graph presence as a tie-breaker?
                # Let's add small boost
                rrf_score += 0.001
            
            final_results.append({
                "chunk_id": cid,
                "content": item["doc"]["content"],
                "doc_id": item["doc"]["doc_id"],
                "score": float(rrf_score), # Final RRF Score
                "metadata": {
                    "bm25_score": item["bm25_score"],
                    "vector_score": item["vector_score"],
                    "bm25_rank": bm25_rank,
                    "vector_rank": vec_rank,
                    **(item.get("original_metadata", {}) or {})
                },
                "graph_metadata": item["graph_metadata"] or graph_metadata
            })
            
        # 6. Sort by RRF Score (descending)
        final_results.sort(key=lambda x: x["score"], reverse=True)
        
        sliced_results = final_results[:top_k]
        
        # Attach extracted keywords to metadata
        for res in sliced_results:
             if "metadata" not in res: res["metadata"] = {}
             res["metadata"]["extracted_keywords"] = tokenized_query
             
        return sliced_results

    def _cosine_similarity(self, vec1, vec2) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))
