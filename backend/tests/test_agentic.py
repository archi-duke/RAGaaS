"""에이전틱 필터 단위 테스트 (docs/design-agentic-filter.md)."""
import asyncio
import json
from types import SimpleNamespace

from app.services.retrieval import agentic as ag


def test_looks_complex():
    assert ag.looks_complex("사용자가 원하는 서비스를 빠르게 추가하는 스타일들이 가지는 공통적인 약점은?")
    assert ag.looks_complex("아인슈타인과 보어의 차이는?")
    assert ag.looks_complex("Hexagonal 과 Clean Architecture 비교")
    assert not ag.looks_complex("마이크로서비스 아키텍처의 단점은?")
    assert not ag.looks_complex("플랑크가 받은 상은?")


def test_single_run_failed():
    assert ag.single_run_failed([], {})
    assert ag.single_run_failed([{"chunk_id": "GRAPH_METADATA_ONLY"}], {})
    assert ag.single_run_failed([{"chunk_id": "c1"}], {"reasoning": {"targeting": {"mode": "V"}}})
    assert not ag.single_run_failed([{"chunk_id": "c1"}], {"reasoning": {"targeting": {"mode": "A"}}})
    # 트리플만 있어도 근거
    assert not ag.single_run_failed([], {"triples": [{"subject": "a", "predicate": "p", "object": "b"}]})


def test_parse_step():
    tools = ["graph_search", "vector_search"]
    raw = json.dumps({"thought": "대상 먼저", "action": "search",
                      "calls": [{"tool": "graph_search", "query": "A 인 것"}, {"tool": "모름", "query": "B"},
                                {"tool": "vector_search", "query": ""}]})
    p = ag.parse_step(raw, tools)
    assert p["action"] == "search"
    assert [c["tool"] for c in p["calls"]] == ["graph_search", "graph_search"]  # 모르는 도구 → 첫 도구, 빈 질문 제외
    assert ag.parse_step("```json\n{\"action\": \"finish\", \"note\": \"공통점만\"}\n```", tools)["action"] == "finish"
    assert ag.parse_step("{\"action\": \"search\", \"calls\": []}", tools)["action"] == "finish"  # 호출 없으면 종료
    p = ag.parse_step(json.dumps({"action": "search", "calls": [{"tool": "graph_search", "query": f"q{i}"} for i in range(9)]}), tools)
    assert len(p["calls"]) == ag.MAX_CALLS_PER_STEP


def test_merge_evidence_round_robin_and_dedupe():
    t = {"subject": "s", "predicate": "p", "object": "o"}
    gathered = [
        {"step": 1, "query": "목록", "results": [{"chunk_id": "a1"}, {"chunk_id": "a2"}, {"chunk_id": "a3"}],
         "meta": {"triples": [t], "result_summary": "대상 3개"}},
        {"step": 2, "query": "X 의 단점", "results": [{"chunk_id": "b1"}, {"chunk_id": "a1"}],
         "meta": {"triples": [t, {"subject": "x", "predicate": "cons", "object": "느림"}]}},
    ]
    history = [{"step": 1, "thought": "목록", "calls": [{"query": "목록", "observation": "..."}]}]
    out = ag.merge_evidence(gathered, note="공통점만", query="원래 질문", history=history)
    ids = [r["chunk_id"] for r in out["results"]]
    assert ids == ["a1", "b1", "a2", "a3"]  # 라운드로빈 + 중복 제거
    assert len(out["graph_metadata"]["triples"]) == 2
    s = out["graph_metadata"]["result_summary"]
    assert "원래 질문" in s and "대상 3개" in s and "공통점만" in s


def test_run_agentic_loop(monkeypatch):
    """계획 LLM 을 흉내 내 2단계 검색 후 종료하는 흐름."""
    plans = iter([
        {"thought": "대상 찾기", "action": "search", "calls": [{"tool": "graph_search", "query": "조건 대상"}]},
        {"thought": "대상별 속성", "action": "search",
         "calls": [{"tool": "graph_search", "query": "A 의 단점"}, {"tool": "graph_search", "query": "B 의 단점"}]},
        {"thought": "충분", "action": "finish", "note": "공통점"},
    ])

    async def fake_achat(cfg, messages, **kw):
        return json.dumps(next(plans))

    async def fake_describe(*a, **k):
        return "[유형 K1] 멤버 2개: A, B"

    import app.core.llm as llm
    monkeypatch.setattr(llm, "achat", fake_achat)
    monkeypatch.setattr(ag, "describe_kb", fake_describe)

    calls = []

    async def run_stage(st_type, params, query):
        calls.append(query)
        return [{"chunk_id": f"c-{query}", "content": query}], {"triples": [{"subject": query, "predicate": "p", "object": "o"}]}

    ctx = SimpleNamespace(query="A·B 공통 단점", kb_id="kb", graph_backend="ontology", metadata={}, logs=[])
    out = asyncio.run(ag.run_agentic(ctx, {"max_steps": 5, "time_budget_s": 60},
                                     {"graph_search": ("graph", {})}, run_stage, {"model": "m"}))
    assert calls == ["조건 대상", "A 의 단점", "B 의 단점"]
    assert out["stop_reason"] == "근거 충분"
    assert len(out["results"]) == 3
    assert out["graph_metadata"]["reasoning"]["targeting"]["mode"] == "AG"
    assert any("[Agentic] 종료" in l for l in ctx.logs)
