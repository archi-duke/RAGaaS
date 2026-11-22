"""Milvus 호출 시간 격리(run_milvus) 테스트.

Milvus 컬렉션이 load 되지 않고 멈춰도 검색 요청이 이벤트 루프 전체를 묶지 않고
MilvusUnavailableError(→ HTTP 503)로 끝나야 한다 (2026-11-22 장애).
"""
import asyncio
import time

import pytest
from pymilvus.exceptions import MilvusException

from app.core import milvus as milvus_core
from app.core.milvus import MilvusUnavailableError, run_milvus
from app.services.retrieval import vector as vector_mod


def test_timeout_raises_unavailable_and_keeps_loop_free():
    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        t = asyncio.create_task(ticker())
        started = time.monotonic()
        with pytest.raises(MilvusUnavailableError, match="시간 초과"):
            await run_milvus(time.sleep, 2, timeout=0.3, what="테스트")
        elapsed = time.monotonic() - started
        t.cancel()
        return elapsed, ticks

    elapsed, ticks = asyncio.run(main())
    assert elapsed < 1.0          # 한도에서 바로 끝난다
    assert ticks >= 5             # 기다리는 동안 이벤트 루프가 다른 작업을 돌렸다


def test_milvus_exception_converted():
    def boom():
        raise MilvusException(code=1, message="should create connection first.")

    with pytest.raises(MilvusUnavailableError, match="should create connection first"):
        asyncio.run(run_milvus(boom, what="테스트"))


def test_other_exceptions_pass_through():
    def boom():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        asyncio.run(run_milvus(boom))


def test_result_returned():
    assert asyncio.run(run_milvus(lambda: 42)) == 42


def test_vector_search_fails_fast_when_load_hangs(monkeypatch):
    class _Emb:
        async def get_embeddings(self, texts):
            return [[0.0] * 4]

    def hanging_load(kb_id):
        time.sleep(2)
        raise AssertionError("not reached in time")

    monkeypatch.setattr(vector_mod, "load_collection", hanging_load)

    real_run = milvus_core.run_milvus

    async def short_run(fn, *a, **kw):
        kw["timeout"] = 0.3
        return await real_run(fn, *a, **kw)

    monkeypatch.setattr(vector_mod, "run_milvus", short_run)

    async def main():
        # asyncio.run 종료 시 남은 스레드를 기다리므로 시간은 코루틴 안에서 잰다
        started = time.monotonic()
        with pytest.raises(MilvusUnavailableError):
            await vector_mod.VectorRetrievalStrategy().search(
                "kb-1", "질문", top_k=3, embedding_service=_Emb())
        return time.monotonic() - started

    assert asyncio.run(main()) < 1.0


def test_ensure_connection_reconnects_when_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(milvus_core.connections, "has_connection", lambda alias: False)
    monkeypatch.setattr(milvus_core, "connect_milvus", lambda: calls.append("connect"))
    milvus_core.ensure_milvus_connection()
    assert calls == ["connect"]

    calls.clear()
    monkeypatch.setattr(milvus_core.connections, "has_connection", lambda alias: True)
    milvus_core.ensure_milvus_connection()
    assert calls == []
