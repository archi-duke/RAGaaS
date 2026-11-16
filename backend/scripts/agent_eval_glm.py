"""GLM 에이전트 평가 — ragaas-query 스킬 + agent 도구(MCP 와 같은 기능)로 질문을 풀고 토큰을 잰다.

docs/design-mcp-agent-query.md §7 평가. 운영에서 쓸 GLM-5 계열 에이전트를 흉내 낸다:
  - 질문마다 새 대화. 시스템 프롬프트 = 스킬 + 캐시된 스키마(describe_kb compact) — 클라이언트가 KB 당 한 번 받아 두는 상황.
  - 도구는 서비스 함수를 직접 부른다 (HTTP 왕복 없음, 결과는 REST 와 동일).
  - Z.ai 응답의 usage 로 질문별 입력·출력 토큰을 합산한다.
  - 10문항마다 Z.ai 5시간 한도를 확인해 90% 를 넘으면 멈춘다.

사용 (컨테이너 안): python scripts/agent_eval_glm.py <kb_id> <questions.json> <out.json> [--model glm-5.2] [--par 3]
"""
import argparse
import asyncio
import json
import time
from typing import Any, Dict, List

SKILL = "/tmp/SKILL.md"
EXAMPLES = "/tmp/examples.md"
MAX_TURNS = 10
TOOL_RESULT_MAX = 12000

TOOLS = [
    {"type": "function", "function": {"name": "lookup_values", "description": "질문 속 말 → 그래프 값 후보 (matches / narrower / suggestions). terms_en 에 영어 표기(오탈자 교정)를 함께.",
     "parameters": {"type": "object", "properties": {"terms": {"type": "array", "items": {"type": "string"}},
                                                     "terms_en": {"type": "object", "additionalProperties": {"type": "string"}},
                                                     "kind": {"type": "string"}}, "required": ["terms"]}}},
    {"type": "function", "function": {"name": "resolve_entities", "description": "이름 → 그래프 엔티티. names_en 에 영어 표기를 함께.",
     "parameters": {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}},
                                                     "names_en": {"type": "object", "additionalProperties": {"type": "string"}},
                                                     "kind": {"type": "string"}}, "required": ["names"]}}},
    {"type": "function", "function": {"name": "describe_entity", "description": "엔티티 하나의 관계 전부 (out=(엔티티,p,o), in=(s,p,엔티티)) + chunk_ids",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "name_en": {"type": "string"}},
                    "required": ["name"]}}},
    {"type": "function", "function": {"name": "query_plan", "description": "질의 계획 실행. where 는 조건 트리 {all:[..]}/{any:[..]}/{path,op,value}. return 은 함께 볼 경로 key 목록.",
     "parameters": {"type": "object", "properties": {"kind": {"type": "string"}, "where": {"type": "object"},
                                                     "return": {"type": "array", "items": {"type": "string"}},
                                                     "aggregate": {"type": "object"}, "limit": {"type": "integer"},
                                                     "evidence": {"type": "string", "enum": ["compact", "full", "none"]}},
                    "required": ["kind"]}}},
    {"type": "function", "function": {"name": "get_chunks", "description": "근거 청크 원문 + 문서명. expand_doc=true 면 같은 문서의 다른 청크도",
     "parameters": {"type": "object", "properties": {"chunk_ids": {"type": "array", "items": {"type": "string"}},
                                                     "expand_doc": {"type": "boolean"}},
                    "required": ["chunk_ids"]}}},
    {"type": "function", "function": {"name": "search", "description": "자연어 검색 (느림, 마지막 수단). 근거 청크와 트리플을 준다",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read_examples", "description": "스킬의 질의 계획 예시 5개를 읽는다",
     "parameters": {"type": "object", "properties": {}}}},
]


async def run_tool(kb_id: str, name: str, args: Dict[str, Any]) -> Any:
    from app.services.agent_query import catalog
    from app.services.agent_query.plan import run_plan
    if name == "lookup_values":
        return await catalog.lookup_values(kb_id, args.get("terms") or [], args.get("kind"), 8, args.get("terms_en") or {})
    if name == "resolve_entities":
        return await catalog.resolve_entities(kb_id, args.get("names") or [], args.get("kind"), 5, args.get("names_en") or {})
    if name == "describe_entity":
        return await catalog.describe_entity(kb_id, args.get("name") or "", args.get("name_en"))
    if name == "query_plan":
        body = {"kind": args.get("kind"), "where": args.get("where"), "return": args.get("return") or [],
                "aggregate": args.get("aggregate"), "limit": args.get("limit") or 50,
                "evidence": args.get("evidence") or "compact"}
        body["include_evidence"] = body["evidence"] != "none"
        r = await run_plan(kb_id, body)
        r.pop("sparql", None)
        return r
    if name == "get_chunks":
        return await catalog.get_chunks(kb_id, args.get("chunk_ids") or [], 1500, bool(args.get("expand_doc")))
    if name == "search":
        from app.mcp_server import search as mcp_search
        return await mcp_search(kb_id, args.get("query") or "", False, 8)
    if name == "read_examples":
        return open(EXAMPLES).read()
    return {"error": f"unknown tool {name}"}


async def quota_pct(cfg) -> float:
    import httpx
    async with httpx.AsyncClient(timeout=20) as c:
        d = (await c.get("https://api.z.ai/api/monitor/usage/quota/limit", headers={"Authorization": cfg["api_key"]})).json()
    return max(l.get("percentage", 0) for l in d["data"]["limits"] if l["type"] == "TOKENS_LIMIT" and l.get("unit") == 3)


async def chat(cfg, model: str, messages, tools):
    import httpx
    from app.core.llm import chat_endpoint, build_headers, _async_sem, _retry_wait
    url = chat_endpoint(cfg.get("base_url"))
    payload = {"model": model, "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0.2,
               "max_tokens": 4000, "thinking": {"type": "disabled"}}
    for attempt in range(4):
        async with _async_sem(url):
            async with httpx.AsyncClient(timeout=180) as c:
                r = await c.post(url, headers=build_headers(cfg.get("api_key"), cfg.get("extra_headers")), json=payload)
        if r.status_code == 429 and attempt < 3:
            await asyncio.sleep(_retry_wait(r, attempt))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


async def solve(kb_id: str, cfg, model: str, system: str, q: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.time()
    msgs: List[Dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": q["question"]}]
    pt = ct = calls = 0
    answer = ""
    tools_used: List[str] = []
    for turn in range(MAX_TURNS):
        last = turn == MAX_TURNS - 1
        resp = await chat(cfg, model, msgs if not last else msgs + [{"role": "user", "content": "도구를 더 쓰지 말고 지금까지 근거로 답하라."}],
                          [] if last else TOOLS)
        u = resp.get("usage") or {}
        pt += u.get("prompt_tokens", 0)
        ct += u.get("completion_tokens", 0)
        m = resp["choices"][0]["message"]
        tcs = m.get("tool_calls") or []
        if not tcs:
            answer = m.get("content") or ""
            break
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
        for tc in tcs:
            calls += 1
            name = tc["function"]["name"]
            tools_used.append(name)
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
                out = await run_tool(kb_id, name, args)
            except Exception as e:
                out = {"error": str(e)[:300]}
            txt = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, default=str)
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": txt[:TOOL_RESULT_MAX]})
    return {"id": q["id"], "answer": answer, "tool_calls": calls, "tools": tools_used, "turns": turn + 1,
            "prompt_tokens": pt, "completion_tokens": ct, "sec": round(time.time() - t0, 1),
            "used_chat_fallback": "search" in tools_used}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kb_id")
    ap.add_argument("questions")
    ap.add_argument("out")
    ap.add_argument("--model", default="glm-5.2")
    ap.add_argument("--par", type=int, default=3)
    ap.add_argument("--stop-pct", type=float, default=90.0)
    a = ap.parse_args()
    from app.core.database import init_db
    await init_db()
    from app.models.knowledge_base import KnowledgeBase
    from app.core.models_resolver import resolve_model_config
    from app.services.agent_query import catalog
    kb = await KnowledgeBase.get(a.kb_id)
    g = next(s for s in kb.pipeline_config["stages"] if s["type"] == "graph")
    cfg = await resolve_model_config(g["params"]["llm_model"])
    schema = await catalog.describe_kb(a.kb_id, None, 15, "compact", 2)
    system = (open(SKILL).read() + "\n\n# 도구 사용 환경\n- 도구는 함수 호출로 쓴다 (kb_id 는 자동). describe_kb 결과는 아래에 이미 있다 (캐시).\n"
              "- 답변은 한국어로 1~3문장, 핵심 이름·연도·용어를 포함. 그래프·원문에 없으면 '지식 그래프에서 찾지 못했다'고 답한다.\n\n"
              "# 캐시된 스키마 (describe_kb, compact)\n" + json.dumps(schema, ensure_ascii=False))
    qs = json.load(open(a.questions))
    print(f"질문 {len(qs)}개, 모델 {a.model}, 시작 5시간 한도 {await quota_pct(cfg)}%", flush=True)
    results: List[Dict[str, Any]] = []
    sem = asyncio.Semaphore(a.par)

    async def one(q):
        async with sem:
            try:
                r = await solve(a.kb_id, cfg, a.model, system, q)
            except Exception as e:
                r = {"id": q["id"], "answer": "", "error": str(e)[:300], "prompt_tokens": 0, "completion_tokens": 0}
            results.append(r)
            print(f"{r['id']} {r.get('sec')}s 호출 {r.get('tool_calls')} 토큰 {r['prompt_tokens'] + r['completion_tokens']:,} | {r['answer'][:70]!r}", flush=True)
            json.dump(sorted(results, key=lambda x: x["id"]), open(a.out, "w"), ensure_ascii=False, indent=1)

    for i in range(0, len(qs), 10):
        pct = await quota_pct(cfg)
        if pct >= a.stop_pct:
            print(f"5시간 한도 {pct}% — 중단", flush=True)
            break
        await asyncio.gather(*(one(q) for q in qs[i:i + 10]))
    tot_p = sum(r["prompt_tokens"] for r in results)
    tot_c = sum(r["completion_tokens"] for r in results)
    n = max(len(results), 1)
    print(f"\n완료 {len(results)}문항 | 입력 {tot_p:,} 출력 {tot_c:,} | 문항당 {(tot_p + tot_c) / n:,.0f} 토큰 | "
          f"끝 5시간 한도 {await quota_pct(cfg)}%", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
