from typing import List, Dict, Any
from app.core.milvus import load_collection, run_milvus, MILVUS_OP_TIMEOUT
from .base import RetrievalStrategy
from .vector import VectorRetrievalStrategy
from app.services.embedding import embedding_service as default_embedding_service
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
        emb_service = kwargs.get("embedding_service", default_embedding_service)
        
        # 1. Candidate Generation (Vector Search with high K)
        query_vectors= await emb_service.get_embeddings([query])
        query_vec = query_vectors[0]
        
        search_params = {
            "metric_type": metric_type,
            "params": {"nprobe": 10},
        }
        
        def _sync_search():
            collection = load_collection(kb_id)
            return collection.search(
                data=query_vectors,
                anns_field="vector",
                param=search_params,
                limit=top_k * 5,
                output_fields=["content", "doc_id", "chunk_id", "vector"],
                timeout=MILVUS_OP_TIMEOUT,
            )

        results = await run_milvus(_sync_search, what="2-stage 후보 검색")

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

        # 2. 1단계 관련성 게이트: score_threshold 는 기존과 같이 cosine 유사도 기준으로 적용
        #    (재랭크 점수는 범위가 달라 같은 임계값을 쓸 수 없다)
        gated = []
        for doc in candidates:
            chunk_vector = doc.pop("vector", None)
            cosine = self._cosine_similarity(query_vec, chunk_vector) if chunk_vector else 0.0
            if cosine >= score_threshold:
                doc["metadata"]["vector_score"] = cosine
                gated.append(doc)

        if not gated:
            return []

        # 3. Reranking — 최종 score 는 Cross-Encoder 점수(sigmoid 로 0~1 변환)
        #    이전엔 재랭크 점수로 정렬만 하고 score 를 cosine 으로 덮어써, 재랭크 결과와
        #    표시/후속 단계가 보는 점수가 어긋났다.
        reranker = self._get_reranker()
        pairs = [[query, doc["content"]] for doc in gated]
        cross_scores = reranker.predict(pairs)

        for doc, raw in zip(gated, cross_scores):
            raw = float(raw)
            doc["score"] = float(1.0 / (1.0 + np.exp(-raw)))
            doc["metadata"]["cross_encoder_raw_score"] = raw
            doc["metadata"]["score_history"] = {
                "ANN": doc["metadata"]["vector_score"],
                "Rerank": doc["score"],
            }

        gated.sort(key=lambda x: x["score"], reverse=True)
        return gated[:top_k]

    def _cosine_similarity(self, vec1, vec2) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))
