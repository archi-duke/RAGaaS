"""ExampleMemory — Level 2 "success example" memory for the query generation Outer Loop.

See docs/design-query-generation-loop.md §4.5 (design) and §9 (implementation
decisions, revised).

Storage: MongoDB collection `query_gen_examples` is the single store —
{_id, kb_id, backend, question, question_vector, query_text, use_count, created_at}.

NOTE (revision of §9 decision): the original design used a shared Milvus
collection for vector search. In this deployment the Milvus server cannot
load/flush newly created collections (load and flush both hit
`wait_for_loading_collection` / DEADLINE_EXCEEDED timeouts, while pre-existing
`kb_*` collections work fine). Since example memory is tiny by design
(MAX_EXAMPLES_PER_KB = 200 per KB/backend), similarity search is done
in-process instead: fetch the KB's example vectors from Mongo and compute
cosine similarity with numpy. This removes the Milvus dependency, the fixed
dim=1536 shared-collection constraint, and the Mongo/Milvus dual-write
consistency problem in one move.

Every public method on ExampleMemory swallows its own exceptions and returns
an empty/neutral result on failure -- a broken example-memory path must never
take down query generation itself. All Mongo I/O is motor (async), so nothing
here can block the event loop.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.config import settings

MONGO_COLLECTION_NAME = "query_gen_examples"

DEDUPE_SIMILARITY_THRESHOLD = 0.95
MAX_EXAMPLES_PER_KB = 200


def _cosine(a: List[float], b: List[float]) -> float:
    """두 벡터의 코사인 유사도. 크기 0 벡터는 0.0 처리."""
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _get_mongo_col():
    """Mongo 컬렉션 지연 참조 (database.client 는 앱 시작 시점에 생성됨)."""
    from app.core import database

    if database.client is None:
        return None
    return database.client[settings.MONGO_DB][MONGO_COLLECTION_NAME]


class ExampleMemory:
    """Stores and retrieves successful (question, query) pairs per KB/backend."""

    async def store(
        self,
        kb_id: str,
        backend: str,
        question: str,
        query_text: str,
        emb_service: Any,
    ) -> None:
        """Store a successful question->query example (or bump use_count on a near-dupe)."""
        try:
            mongo_col = _get_mongo_col()
            if mongo_col is None:
                print("[ExampleMemory] WARNING: Mongo client not initialized, skipping store")
                return

            vectors = await emb_service.get_embeddings([question])
            vector = list(vectors[0])

            # Dedupe: 동일 kb/backend 범위의 기존 예시와 유사도 비교 (최대 200개라 전수 비교로 충분)
            best_id, best_score = None, -1.0
            cursor = mongo_col.find(
                {"kb_id": kb_id, "backend": backend},
                {"question_vector": 1},
            )
            async for doc in cursor:
                score = _cosine(vector, doc.get("question_vector") or [])
                if score > best_score:
                    best_id, best_score = doc["_id"], score

            if best_id is not None and best_score >= DEDUPE_SIMILARITY_THRESHOLD:
                await mongo_col.update_one({"_id": best_id}, {"$inc": {"use_count": 1}})
                return

            await mongo_col.insert_one(
                {
                    "kb_id": kb_id,
                    "backend": backend,
                    "question": question,
                    "question_vector": vector,
                    "query_text": query_text,
                    "use_count": 1,
                    "created_at": datetime.utcnow(),
                }
            )

            await self._evict_if_over_limit(kb_id, backend, mongo_col)

        except Exception as e:
            print(f"[ExampleMemory] WARNING: failed to store example: {e}")

    async def search(
        self,
        kb_id: str,
        backend: str,
        question: str,
        emb_service: Any,
        top_k: int = 3,
        min_score: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Search for similar past successful examples. Never raises; returns [] on failure."""
        try:
            mongo_col = _get_mongo_col()
            if mongo_col is None:
                print("[ExampleMemory] WARNING: Mongo client not initialized, skipping search")
                return []

            vectors = await emb_service.get_embeddings([question])
            vector = list(vectors[0])

            scored: List[Dict[str, Any]] = []
            cursor = mongo_col.find(
                {"kb_id": kb_id, "backend": backend},
                {"question": 1, "query_text": 1, "question_vector": 1},
            )
            async for doc in cursor:
                score = _cosine(vector, doc.get("question_vector") or [])
                if score >= min_score:
                    scored.append(
                        {
                            "id": str(doc["_id"]),
                            "_oid": doc["_id"],
                            "question": doc.get("question"),
                            "query_text": doc.get("query_text"),
                            "score": score,
                        }
                    )

            scored.sort(key=lambda x: x["score"], reverse=True)
            results = scored[:top_k]

            if results:
                try:
                    await mongo_col.update_many(
                        {"_id": {"$in": [r["_oid"] for r in results]}},
                        {"$inc": {"use_count": 1}},
                    )
                except Exception as e:
                    print(f"[ExampleMemory] WARNING: failed to bump use_count on search hits: {e}")

            # 내부용 ObjectId 는 반환하지 않는다
            for r in results:
                r.pop("_oid", None)
            return results

        except Exception as e:
            print(f"[ExampleMemory] WARNING: failed to search examples: {e}")
            return []

    async def _evict_if_over_limit(self, kb_id: str, backend: str, mongo_col) -> None:
        """Evict least-used/oldest examples for a KB once the count exceeds MAX_EXAMPLES_PER_KB."""
        try:
            count = await mongo_col.count_documents({"kb_id": kb_id, "backend": backend})
            if count <= MAX_EXAMPLES_PER_KB:
                return

            excess = count - MAX_EXAMPLES_PER_KB
            cursor = (
                mongo_col.find({"kb_id": kb_id, "backend": backend}, {"_id": 1})
                .sort([("use_count", 1), ("created_at", 1)])
                .limit(excess)
            )
            to_delete_ids = [doc["_id"] async for doc in cursor]
            if to_delete_ids:
                await mongo_col.delete_many({"_id": {"$in": to_delete_ids}})

        except Exception as e:
            print(f"[ExampleMemory] WARNING: failed to evict over-limit examples for kb_id={kb_id}: {e}")
