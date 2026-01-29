from typing import List, Dict, Any
from .base import RetrievalStrategy
from .vector import VectorRetrievalStrategy
from app.core.milvus import create_collection
from app.services.embedding import embedding_service
from sentence_transformers import CrossEncoder # type: ignore
import numpy as np

class TwoStageRetrievalStrategy(RetrievalStrategy):
    def __init__(self):
        self.reranker = None
        
    def _get_reranker(self):
        if not self.reranker:
            self.reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        return self.reranker

    async def search(self, kb_id: str, query: str, top_k: int, **kwargs) -> List[Dict[str, Any]]:
        metric_type = kwargs.get("metric_type", "COSINE")
        score_threshold = kwargs.get("score_threshold", 0.0)
        
        # 1. Candidate Generation (Vector Search with high K)
        collection = create_collection(kb_id)
        collection.load()
        
        query_vectors = await embedding_service.get_embeddings([query])
        query_vec = query_vectors[0]
        
        search_params = {
            "metric_type": metric_type,
            "params": {"nprobe": 10},
        }
        
        results = collection.search(
            data=query_vectors, 
            anns_field="vector", 
            param=search_params, 
            limit=top_k * 5, 
            output_fields=["content", "doc_id", "chunk_id", "vector"]
        )
        
        candidates = []
        for hits in results:
            for hit in hits:
                candidates.append({
                    "chunk_id": hit.entity.get("chunk_id"),
                    "content": hit.entity.get("content"),
                    "metadata": {"doc_id": hit.entity.get("doc_id")},
                    "vector": hit.entity.get("vector")
                })
        
        if not candidates:
            return []

        # 2. Reranking
        reranker = self._get_reranker()
        pairs = [[query, doc["content"]] for doc in candidates]
        cross_scores = reranker.predict(pairs)
        
        for i, doc in enumerate(candidates):
            doc["cross_score"] = float(cross_scores[i])
            
        candidates.sort(key=lambda x: x["cross_score"], reverse=True)
        
        # 3. Final selection (Unified Scoring with Cosine)
        filtered = []
        for doc in candidates:
            chunk_vector = doc.get("vector")
            doc["score"] = 0.0
            if chunk_vector:
                doc["score"] = self._cosine_similarity(query_vec, chunk_vector)
            
            doc.pop("vector", None)
            doc.pop("cross_score", None)
            
            if doc["score"] >= score_threshold:
                filtered.append(doc)
                
        return filtered[:top_k]
        
    def _cosine_similarity(self, vec1, vec2) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))
