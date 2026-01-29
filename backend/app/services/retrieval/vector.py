from typing import List, Dict, Any

from app.core.milvus import create_collection
from app.services.embedding import embedding_service
from .base import RetrievalStrategy

class VectorRetrievalStrategy(RetrievalStrategy):
    async def search(self, kb_id: str, query: str, top_k: int, **kwargs) -> List[Dict[str, Any]]:
        score_threshold = kwargs.get("score_threshold", 0.0)
        metric_type = kwargs.get("metric_type", "COSINE")
        index_type = kwargs.get("index_type", "IVF_FLAT")
        
        collection = create_collection(kb_id, metric_type=metric_type, index_type=index_type)
        collection.load()

        # 1. Embed query
        query_vectors = await embedding_service.get_embeddings([query])
        query_vec = query_vectors[0]
        
        # 2. Search
        search_params = {
            "metric_type": metric_type,
            "params": {},
        }
        
        if index_type == "IVF_FLAT":
            search_params["params"] = {"nprobe": 10}
        elif index_type == "HNSW":
            search_params["params"] = {"ef": 64}
        # FLAT and LSH typically don't need complex search-time params in simple cases
        
        # Don't need vector field anymore if we trust Milvus score
        output_fields = ["content", "doc_id", "chunk_id"]

        results = collection.search(
            data=query_vectors, 
            anns_field="vector", 
            param=search_params, 
            limit=top_k * 3,  # Fetch more for filtering
            output_fields=output_fields
        )
        
        retrieved = []
        for hits in results:
            for hit in hits:
                # Use Milvus returned score
                # Note: For L2, lower is better (distance). For IP/Cosine, higher is better.
                milvus_score = hit.score
                final_score = milvus_score

                # If Metric is L2, typically we want to return a similarity score (higher is better)
                # or just return distance if that's what user expects.
                # Here we stick to the convention: score is "similarity" or "relevance".
                # If metric is L2, convert distance to similarity: 1 / (1 + distance)
                if metric_type == "L2":
                    try:
                        final_score = 1.0 / (1.0 + milvus_score)
                    except ZeroDivisionError:
                        final_score = 1.0

                if final_score < score_threshold:
                    continue
                
                retrieved.append({
                    "chunk_id": hit.entity.get("chunk_id"),
                    "content": hit.entity.get("content"),
                    "score": final_score,
                    "metadata": {
                        "doc_id": hit.entity.get("doc_id"),
                        "milvus_raw_score": milvus_score,
                        "metric_type": metric_type 
                    }
                })
        
        retrieved.sort(key=lambda x: x["score"], reverse=True)
        return retrieved[:top_k]


    # _cosine_similarity is no longer needed as we use Milvus scores directly
