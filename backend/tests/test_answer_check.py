"""답변 근거 검사 (추출 품질 후속 C, 2026-11-25)."""
import asyncio

from app.services.retrieval import answer_check as ac


def test_split_and_skip():
    ans = ("가용성 확보에 유리한 스타일은 다음과 같습니다:\n\n"
           "1. **Microservices**: 가용성에 중간 정도의 긍정 효과가 있습니다. [Chunk 2]에 따르면 장애를 격리할 수 있다.\n"
           "[Chunk 1]")
    s = ac.split_sentences(ans)
    assert len(s) == 4
    assert ac._skip("[Chunk 1]") and not ac._skip(s[1])


def test_stage_of():
    assert ac.stage_of({"stages": [{"type": "graph"}, {"type": "answer_check", "params": {"action": "remove"}}]})["params"]["action"] == "remove"
    assert ac.stage_of({"stages": [{"type": "graph"}]}) is None


def test_remove_mode(monkeypatch):
    async def fake_achat(cfg, msgs, **kw):
        return '{"results": [{"id": 0, "verdict": "supported"}, {"id": 1, "verdict": "unsupported", "reason": "근거에 비용 수치 없음"}]}'
    import app.core.llm as llm
    monkeypatch.setattr(llm, "achat", fake_achat)
    out = asyncio.run(ac.check_answer("CQRS는 확장성에 강한 긍정 효과가 있다.\n도입 비용은 30% 늘어난다.", "ctx",
                                      {"model": "m"}, "remove"))
    assert out["checked"] == 2 and len(out["unsupported"]) == 1
    assert "30%" not in out["answer"] and "확장성" in out["answer"]
    mark = asyncio.run(ac.check_answer("CQRS는 확장성에 강한 긍정 효과가 있다.\n도입 비용은 30% 늘어난다.", "ctx",
                                       {"model": "m"}, "mark"))
    assert "answer" not in mark and mark["unsupported"][0]["sentence"].startswith("도입 비용")
