"""Inner Loop for LLM-generated graph query retry logic.

See docs/design-query-generation-loop.md §3, §4.1 for the design rationale.

QueryGenerationLoop wraps a backend-agnostic "generate -> execute" cycle with
error feedback re-generation: if a generated query is missing, throws, or
returns zero results, the failure is fed back into the next generation
attempt as `retry_context`. Retries are capped (max_retries) and the whole
run is bounded by a wall-clock timeout (total_timeout).
"""

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


@dataclass
class AttemptLog:
    attempt_no: int
    generated_query: Optional[str]
    error: Optional[str]
    result_count: int
    elapsed_ms: int
    succeeded: bool


GenerateFn = Callable[[str, Optional[str]], Awaitable[Dict[str, Any]]]
ExecuteFn = Callable[[str], Awaitable[List[Any]]]


def _build_retry_context(query: Optional[str], error: Optional[str], schema_hint: Optional[str] = None) -> str:
    reason = error if error else "실행은 성공했으나 결과 0건"
    hint_block = f"\n{schema_hint}" if schema_hint else ""
    return (
        "[이전 시도 실패]\n"
        "실패한 쿼리:\n"
        f"{query}\n"
        f"실패 원인: {reason}{hint_block}\n"
        "위 실패를 참고해 수정된 쿼리를 생성하라. 존재하지 않는 관계/속성을 추측하지 말고, "
        "제공된 스키마 정보에 있는 것만 사용하라. 수정된 쿼리만 출력하라."
    )


class QueryGenerationLoop:
    """Backend-agnostic generate->execute retry loop (the "Inner Loop")."""

    def __init__(self, max_retries: int = 2, total_timeout: float = 120.0):
        self.max_retries = max_retries
        self.total_timeout = total_timeout

    async def run(
        self,
        question: str,
        generate_fn: GenerateFn,
        execute_fn: ExecuteFn,
        schema_hint_fn=None,
    ) -> Dict[str, Any]:
        """
        generate_fn(question, retry_context) -> {"query": str|None, "raw": dict}
        execute_fn(query) -> list of result records (may raise)
        schema_hint_fn(failed_query) -> Optional[str]  (선택)
            실패한 쿼리가 그래프에 없는 관계/predicate 를 참조하면 재시도
            프롬프트에 주입할 힌트 문자열을 반환. 실행을 차단하지 않으며,
            이미 실패한 시도의 재시도 피드백만 강화한다.

        Returns: {"query": str|None, "results": list, "attempts": [AttemptLog...], "succeeded": bool}
        """
        start_time = time.monotonic()
        attempts: List[AttemptLog] = []
        retry_context: Optional[str] = None

        last_query: Optional[str] = None
        last_results: List[Any] = []

        total_attempts = 1 + max(self.max_retries, 0)

        for attempt_no in range(1, total_attempts + 1):
            if time.monotonic() - start_time >= self.total_timeout:
                break

            attempt_start = time.monotonic()
            query: Optional[str] = None
            error: Optional[str] = None
            results: List[Any] = []

            # --- Generation ---
            try:
                gen_result = await generate_fn(question, retry_context)
                query = (gen_result or {}).get("query")
            except Exception as e:
                error = str(e)

            if error is None and (not query or not str(query).strip()):
                error = error or "생성된 쿼리가 비어 있음"
                query = None

            # --- Execution (only if we have a query) ---
            if query and error is None:
                try:
                    results = await execute_fn(query)
                    if results is None:
                        results = []
                except Exception as e:
                    error = str(e)
                    results = []

            result_count = len(results) if results else 0
            succeeded = error is None and result_count >= 1
            elapsed_ms = int((time.monotonic() - attempt_start) * 1000)

            attempts.append(
                AttemptLog(
                    attempt_no=attempt_no,
                    generated_query=query,
                    error=error,
                    result_count=result_count,
                    elapsed_ms=elapsed_ms,
                    succeeded=succeeded,
                )
            )

            last_query = query
            last_results = results

            if succeeded:
                return {
                    "query": query,
                    "results": results,
                    "attempts": attempts,
                    "succeeded": True,
                }

            # Prepare retry context for the next attempt (if any remain).
            # schema_hint_fn 은 실패한 쿼리를 스키마와 대조해 힌트를 만든다 (실행 차단 아님).
            schema_hint = None
            if schema_hint_fn is not None and query:
                try:
                    schema_hint = schema_hint_fn(query)
                except Exception:
                    schema_hint = None
            retry_context = _build_retry_context(query, error, schema_hint)

            if time.monotonic() - start_time >= self.total_timeout:
                break

        return {
            "query": last_query,
            "results": last_results,
            "attempts": attempts,
            "succeeded": False,
        }
