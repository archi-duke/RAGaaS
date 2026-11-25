"""파이프라인 성공/실패 분기 테스트 (2026-11-25).

- 정상 연결: 성공하면 다음 스테이지. 실패 연결의 대상은 성공 경로에서 건너뛴다.
- 실패 연결(on_failure): 예외·그래프 근거 없음이면 그 스테이지로 넘어간다.
- 실패 연결이 없으면 실패를 기록하고 멈춘다 (오류를 삼키고 다음으로 가지 않는다).
"""
import asyncio

from app.schemas.pipeline import PipelineConfig, PipelineStage
from app.services.retrieval.pipeline_executor import PipelineExecutor


def _chunk(cid, score=0.9):
    return {"chunk_id": cid, "doc_id": "d", "content": cid, "score": score}


def _executor(calls, graph_mode="ok"):
    ex = PipelineExecutor()

    async def graph(ctx, params):
        calls.append(("graph", params.get("graph_fallback")))
        if graph_mode == "error":
            raise RuntimeError("Fuseki 연결 실패")
        if graph_mode == "empty":
            ctx.metadata["_stage_empty"] = True
            ctx.metadata["_stage_empty_reason"] = "그래프에서 근거(트리플·청크)를 찾지 못함"
            return ctx
        ctx.results = [_chunk("g1")]
        return ctx

    async def ann(ctx, params):
        calls.append(("ann", None))
        ctx.results = ctx.results + [_chunk("v1", 0.5)]
        return ctx

    async def rerank(ctx, params):
        calls.append(("rerank", None))
        return ctx

    ex._handlers.update(graph=graph, ann=ann, rerank=rerank)
    return ex


def _run(ex, stages):
    return asyncio.run(ex.execute("kb", "질문", PipelineConfig(stages=stages)))


def _stages(link=True):
    return [
        PipelineStage(type="graph", id="g", on_failure="v" if link else None),
        PipelineStage(type="ann", id="v"),
        PipelineStage(type="rerank", id="r"),
    ]


def test_success_skips_failure_target():
    calls = []
    ctx = _run(_executor(calls, "ok"), _stages())
    assert [c[0] for c in calls] == ["graph", "rerank"]
    assert calls[0][1] == "none"          # 실패 연결이 있으면 그래프 내부 문서 검색 대체는 끈다
    assert ctx.failures == [] and not ctx.stopped
    assert [r["chunk_id"] for r in ctx.results] == ["g1"]


def test_empty_graph_routes_to_failure_target():
    calls = []
    ctx = _run(_executor(calls, "empty"), _stages())
    assert [c[0] for c in calls] == ["graph", "ann", "rerank"]
    assert ctx.failures[0]["kind"] == "empty" and ctx.failures[0]["routed_to"] == "ann"
    assert not ctx.has_error and not ctx.stopped
    assert any("실패 연결로 Stage 2 ann" in l for l in ctx.logs)


def test_error_routes_and_is_reported():
    calls = []
    ctx = _run(_executor(calls, "error"), _stages())
    assert [c[0] for c in calls] == ["graph", "ann", "rerank"]
    assert ctx.has_error
    assert "Fuseki" in ctx.failures[0]["message"]


def test_no_link_stops_pipeline():
    calls = []
    ctx = _run(_executor(calls, "error"), _stages(link=False))
    assert [c[0] for c in calls] == ["graph"]
    assert ctx.stopped and ctx.has_error
    assert ctx.failures[0]["routed_to"] is None


def test_no_link_keeps_graph_fallback_param():
    calls = []
    _run(_executor(calls, "ok"), [PipelineStage(type="graph", params={"graph_fallback": "vector"})])
    assert calls[0] == ("graph", "vector")


def test_link_to_earlier_stage_is_ignored():
    calls = []
    stages = [PipelineStage(type="ann", id="v"), PipelineStage(type="graph", id="g", on_failure="v")]
    ctx = _run(_executor(calls, "empty"), stages)
    assert [c[0] for c in calls] == ["ann", "graph"]
    assert ctx.stopped


def test_version_hash_ignores_ids_and_tracks_links():
    from app.services import pipeline_versions as pv
    a = {"stages": [{"type": "graph", "params": {}, "id": "a1", "on_failure": "a2"},
                    {"type": "ann", "params": {}, "id": "a2"}]}
    b = {"stages": [{"type": "graph", "params": {}, "id": "b1", "on_failure": "b2"},
                    {"type": "ann", "params": {}, "id": "b2"}]}
    c = {"stages": [{"type": "graph", "params": {}, "id": "c1"}, {"type": "ann", "params": {}, "id": "c2"}]}
    assert pv.config_hash(a) == pv.config_hash(b)
    assert pv.config_hash(a) != pv.config_hash(c)
    assert pv.normalize(a)["stages"][0]["on_failure"] == "a2"
    assert "graph.실패 연결 \"ann\" → 없음" in pv.diff(a, c)
