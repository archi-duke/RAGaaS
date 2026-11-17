"""KB 검색 정책 + 파이프라인 버전 (docs/design/agent/design-search-entry-and-pipeline-versions.md)."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services.retrieval import search_policy as sp
from app.services import pipeline_versions as pv

LIVE = {"stages": [{"type": "agentic", "params": {}},
                   {"type": "graph", "params": {"max_hops": 4, "resolve_terms": False}},
                   {"type": "rerank", "params": {}}]}


def _kb(**kw):
    base = dict(pipeline_config=LIVE, pipeline_draft=None, pipeline_draft_base=None, pipeline_live_ref="abc")
    base.update(kw)
    return SimpleNamespace(**base)


def test_summarize_reports_filters_and_graph_options():
    s = sp.summarize(LIVE)
    assert s["search_filters"] == ["graph"] and s["post_filters"] == ["rerank"] and s["agentic"]
    assert s["graph"] == {"max_hops": 4, "typo_synonym": False, "list_supplement": True, "graph_fallback": "vector"}
    assert sp.summarize({"stages": [{"type": "smalltalk"}, {"type": "rerank"}]})["search_filters"] == []


def test_without_agentic_keeps_original():
    p = sp.without_agentic(LIVE)
    assert [s["type"] for s in p["stages"]] == ["graph", "rerank"]
    assert LIVE["stages"][0]["type"] == "agentic"


def test_resolve_pipeline_priority():
    draft = {"stages": [{"type": "ann", "params": {}}]}
    kb = _kb(pipeline_draft=draft)
    run = lambda *a: asyncio.new_event_loop().run_until_complete(sp.resolve_pipeline(*a))
    assert run(kb, "live")[0] is LIVE and run(kb, "live")[1]["ref"] == "abc"
    assert run(kb, "draft")[0] is draft
    inline = {"stages": []}
    assert run(kb, "live", inline)[0] is inline
    p, meta = run(_kb(), "draft")          # 테스트 구성이 없으면 운영으로
    assert p is LIVE and meta["kind"] == "draft" and meta.get("note")


def test_diff_lists_param_and_stage_changes():
    new = {"stages": [{"type": "graph", "params": {"max_hops": 8, "resolve_terms": False}},
                      {"type": "rerank", "params": {}}, {"type": "ann", "params": {"top_k": 5}}]}
    d = pv.diff(LIVE, new)
    assert "스테이지 추가: ann" in d and "스테이지 제거: agentic" in d
    assert "graph.max_hops 4 → 8" in d
    assert pv.diff(LIVE, LIVE) == []


def test_normalize_requires_stages_and_drops_private_keys():
    with pytest.raises(ValueError):
        pv.normalize({"foo": 1})
    n = pv.normalize({**LIVE, "_applied": {"x": 1}})
    assert n["schema"] == pv.SCHEMA and "_applied" not in n
    assert pv.warnings_of({"stages": [{"type": "old_stage"}]})


def test_publish_commits_before_switching_live(monkeypatch):
    saved = {}

    class KB(SimpleNamespace):
        async def save(self):
            saved["live"] = self.pipeline_config

    kb = KB(name="t", pipeline_config=LIVE, pipeline_live_ref="abc", pipeline_draft_base="abc", updated_at=None,
            pipeline_draft={"stages": [{"type": "graph", "params": {"max_hops": 8}}]})

    async def fake_kb(_):
        return kb
    monkeypatch.setattr(pv, "_kb", fake_kb)

    async def git_down(*a, **k):
        raise pv.GitUnavailable("down")
    monkeypatch.setattr(pv, "commit_file", git_down)
    loop = asyncio.new_event_loop()
    with pytest.raises(pv.GitUnavailable):
        loop.run_until_complete(pv.publish("kb1", "시험"))
    assert kb.pipeline_config is LIVE and kb.pipeline_live_ref == "abc"     # 운영 그대로

    async def git_ok(kb_id, cfg, msg):
        assert msg.startswith("시험") and "스테이지 제거: agentic" in msg
        return "def"
    monkeypatch.setattr(pv, "commit_file", git_ok)
    out = loop.run_until_complete(pv.publish("kb1", "시험"))
    assert out["ref"] == "def" and kb.pipeline_live_ref == "def" and not out["dirty"]
    assert loop.run_until_complete(pv.publish("kb1", "다시"))["unchanged"]
