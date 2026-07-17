"""AttemptLogger — Level 1 observability for the query generation Inner Loop.

See docs/design-query-generation-loop.md §4.4 (schema), §5 (failure isolation),
§9 (motor-direct decision).

This is an insert-only logger; it deliberately bypasses Beanie (no Document
model / no document_models registration) and writes straight through the
module-global motor client in `app.core.database`. That client is created
lazily at app startup (`init_db()`), so it must be referenced lazily here too
(module-level `from app.core.database import client` would bind `None`
forever) -- hence the `from app.core import database` + `database.client`
indirection inside the function body.

Logging failures must never propagate: a Mongo outage should not break the
retrieval response itself.
"""

from datetime import datetime
from typing import List, Optional

from app.core.config import settings
from app.services.retrieval.query_gen_loop import AttemptLog

COLLECTION_NAME = "query_gen_logs"


async def log_attempts(
    kb_id: str,
    backend: str,
    question: str,
    attempts: List[AttemptLog],
    model: str,
    few_shot_used: Optional[List[str]] = None,
) -> None:
    """Persist all attempts (success or failure) from one Inner Loop run.

    Never raises -- any error is caught and only printed as a warning.
    """
    if not attempts:
        return

    try:
        from app.core import database

        if database.client is None:
            print("[QueryGenAttemptLogger] WARNING: Mongo client not initialized, skipping log write")
            return

        now = datetime.utcnow()
        few_shot_ids = few_shot_used or []

        docs = [
            {
                "kb_id": kb_id,
                "backend": backend,
                "question": question,
                "generated_query": attempt.generated_query,
                "attempt_no": attempt.attempt_no,
                "error": attempt.error,
                "result_count": attempt.result_count,
                "elapsed_ms": attempt.elapsed_ms,
                "model": model,
                "few_shot_used": few_shot_ids,
                "succeeded": attempt.succeeded,
                "created_at": now,
            }
            for attempt in attempts
        ]

        collection = database.client[settings.MONGO_DB][COLLECTION_NAME]
        await collection.insert_many(docs)

    except Exception as e:
        print(f"[QueryGenAttemptLogger] WARNING: failed to log attempts: {e}")
