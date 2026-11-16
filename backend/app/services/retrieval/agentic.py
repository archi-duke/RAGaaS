"""에이전틱 필터 — 검색 방식을 정하고 검색 과정을 단계별로 진행한다 (docs/design-agentic-filter.md).

파이프라인에 `agentic` 스테이지가 있으면 실행기가 제어권을 이 모듈에 넘긴다.
- 도구 = 파이프라인에 등록된 검색 스테이지 (graph → 그래프 검색, ann → 벡터, bm25 → 키워드).
  빌더에서 뺀 검색은 쓰지 않는다. 각 도구는 그 스테이지의 파라미터 그대로 하위 질문 하나를 실행한다.
- LLM(필터의 llm_model)은 하위 질문과 도구를 고르고, 관찰을 보고 다음 단계 또는 종료를 정한다.
  SPARQL 은 쓰지 않는다 — 그래프 질의는 graph 스테이지의 결정적 경로가 만든다.
- mode=auto: 복합 질문(조건으로 대상을 고른 뒤 다시 묻기·비교·공통점)이거나, 단일 실행이 근거 없이
  끝나면(문서 검색 V 전환·결과 0) 단계 진행. 그 외에는 기존 순차 실행 그대로.
"""

import asyncio
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_MAX_STEPS = 6
DEFAULT_TIME_BUDGET_S = 60.0
SCRATCHPAD_MAX = 2500       # 스크래치패드 길이 상한 (다음 단계 프롬프트·답변 컨텍스트에 그대로 들어감)
ESCALATED_MAX_STEPS = 2   # 단일 실행 실패 후 승격된 경우의 단계 상한 (없는 사실을 오래 찾지 않게)
MAX_CALLS_PER_STEP = 4
MAX_TRIPLES = 150
MIN_STEP_S = 8.0       # 새 단계를 시작할 최소 남은 시간
CALL_TIMEOUT_S = 20.0   # 하위 검색 하나의 상한 (남은 예산이 더 짧으면 그만큼)

TOOL_DESC = {
    "graph_search": "지식 그래프 검색. 하위 질문 하나(한 대상·한 관계, 또는 '조건을 만족하는 대상 목록')를 넣으면 "
                    "트리플과 근거 청크를 돌려준다. 유형 조건 질의('수정 용이성이 높은 스타일은?')와 "
                    "특정 대상의 속성 질의('Hexagonal 의 단점은?')에 적합.",
    "vector_search": "문서 의미 검색(벡터). 그래프에 구조화되지 않은 서술·설명을 찾을 때.",
    "keyword_search": "문서 키워드 검색(BM25). 고유명사·용어가 정확히 들어간 문단을 찾을 때.",
}
STAGE_TOOL = {"graph": "graph_search", "ann": "vector_search", "bm25": "keyword_search"}

# 단일 실행으로 풀기 어려운 복합 질문 신호 (auto 모드 사전 판정)
_COMPLEX_PATTERNS = [
    r"공통", r"비교", r"차이", r"각각", r"모두의", r"대비", r"vs\.?", r"어느 쪽",
    r"(들|것들)(이|의|은|는|에)\s*\S*\s*(가지|갖|있|공유|약점|강점|단점|장점|특징|문제)",
    r"(인|하는|한|되는|높은|낮은|빠른|많은)\s*\S*(들)(이|의|은|는)",
    # 조건 여러 개를 '과/와/및' 으로 묶은 질문: "배포 용이성과 수정 용이성이 좋은 스타일은?" — 교차 확인이 필요
    r"\S+(과|와|및)\s+\S+.{0,20}(좋은|높은|낮은|강한|뛰어난|우수한|빠른|적합한|유리한|불리한|나쁜)",
    r"(모두|둘\s*다|동시에|함께)\s*\S*(좋|높|만족|충족|해당|가진|갖)",
]
_COMPLEX_RE = re.compile("|".join(_COMPLEX_PATTERNS))


def count_unknown(scratchpad: str) -> int:
    """스크래치패드 '후보 × 조건' 표의 미확인(?) 칸 수."""
    n = 0
    for line in (scratchpad or "").splitlines():
        if line.strip().startswith("|") and not set(line.replace("|", "").strip()) <= set("-: "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")][1:]
            n += sum(1 for c in cells if c.startswith("?"))
    return n


def looks_complex(query: str) -> bool:
    return bool(_COMPLEX_RE.search(query or ""))


def graph_mode(meta: Optional[Dict[str, Any]]) -> Optional[str]:
    return (((meta or {}).get("reasoning") or {}).get("targeting") or {}).get("mode")


def single_run_failed(results: List[Dict[str, Any]], meta: Optional[Dict[str, Any]]) -> bool:
    """단일 실행이 근거 없이 끝났는가 — 결과 0 이거나 그래프가 문서 검색(V)으로 넘어감."""
    real = [r for r in results or [] if r.get("chunk_id") != "GRAPH_METADATA_ONLY"]
    if not real and not (meta or {}).get("triples"):
        return True
    return graph_mode(meta) == "V"


# ---------------------------------------------------------------------------
# KB 요약 (계획 프롬프트용)
# ---------------------------------------------------------------------------

async def describe_kb(kb_id: str, graph_backend: str, llm_model_config: Optional[dict]) -> str:
    """유형·멤버 예시·속성(값 어휘) 요약. 그래프가 없거나 실패하면 빈 문자열."""
    if graph_backend != "ontology":
        return ""
    try:
        from app.services.retrieval.graph_backends.fuseki import FusekiBackend
        from app.services.retrieval.relation_targeting import local_name
        kinds, catalogs = await FusekiBackend()._class_catalog(
            kb_id, lambda _m: None, {"llm_model_config": llm_model_config} if llm_model_config else {})
    except Exception as e:
        return f"(KB 구조 요약 실패: {e})"
    lines = []
    for k in kinds[:6]:
        ex = ", ".join(local_name(m) for m in k["members"][:15])
        lines.append(f"[유형 {k['name']}]" + (f" {k['description']}" if k.get("description") else "")
                     + f" 멤버 {len(k['members'])}개: {ex}" + (" …" if len(k["members"]) > 15 else ""))
        for p in (catalogs.get(k["name"]) or [])[:80]:
            if p.get("equiv_rep") and p["equiv_rep"] != p["key"]:
                continue
            labels = [str(v["label"]) for v in p["values"]]
            note = (f" — {p['description']}" if p.get("description") else "") + (
                f" (별칭: {', '.join(p['aliases'])})" if p.get("aliases") else "")
            if p["type"] == "number":
                lo, hi = p.get("range", [0, 0])
                lines.append(f"  - {p['key']} [수치 {lo:g}~{hi:g}]{note}")
            elif p["type"] == "enum" and all(len(l) <= 30 for l in labels):
                lines.append(f"  - {p['key']} [값: {', '.join(labels[:8])}]{note}")
            else:
                # 긴 서술 값은 예시 하나만 짧게 — 요약이 잘려 뒤쪽 속성(tradeoffs.* 등)이 빠지지 않게
                ex = labels[0].replace("\n", " ")[:40] if labels else ""
                lines.append(f"  - {p['key']} [서술 {len(labels)}종, 예: {ex}]{note}")
    text = "\n".join(lines)
    return text[:8000]


# ---------------------------------------------------------------------------
# 계획 LLM
# ---------------------------------------------------------------------------

def build_step_messages(query: str, kb_summary: str, tools: List[str], history: List[Dict[str, Any]],
                        step_no: int, max_steps: int, scratchpad: str = "", final: bool = False) -> List[Dict[str, str]]:
    tool_lines = "\n".join(f"- {t}: {TOOL_DESC[t]}" for t in tools)
    hist = []
    # 지난 단계는 짧게 (내용은 스크래치패드에 정리돼 있다), 직전 단계만 관찰 전문 — 계획 프롬프트가 단계마다 커져 느려지는 것 방지
    for idx, h in enumerate(history):
        last = idx == len(history) - 1
        hist.append(f"## 단계 {h['step']} — {h.get('thought', '')}")
        for c in h["calls"]:
            obs = c['observation'] if last else str(c['observation'])[:160]
            hist.append(f"- {c['tool']}(\"{c['query']}\") → {obs}")
    hist_text = "\n".join(hist) if hist else "(아직 없음)"
    user = f"""사용자 질문에 답할 근거를 모으기 위해 검색을 단계별로 진행한다. 지금은 {step_no}/{max_steps} 단계다.

[사용자 질문]
{query}

[지식베이스 구조]
{kb_summary or '(구조 정보 없음 — 문서 검색 위주로)'}

[쓸 수 있는 도구]
{tool_lines}

[지금까지의 검색]
{hist_text}

[스크래치패드 — 직전 단계까지 정리한 메모. 이어서 고쳐 쓴다]
{scratchpad or '(비어 있음 — 처음 작성)'}

{'[지금은 정리 단계다 — 시간·단계가 다 되어 더 검색하지 않는다. action 은 finish, calls 는 빈 목록. 지금까지의 검색으로 스크래치패드를 최종 정리하라.]' if final else ''}
규칙:
1. 복합 질문은 나눠서 찾는다. 예: "X 한 것들의 공통 약점" → (1) X 인 대상 목록을 찾고 (2) 찾은 대상 각각의 약점을 찾는다.
2. 하위 질문은 도구가 한 번에 풀 수 있게 짧고 구체적으로. 앞 단계에서 찾은 대상 이름을 그대로 쓴다.
   지식베이스 구조의 속성 이름·값 표기를 쓰면 정확해진다. 질문의 표현이 여러 속성·값에 해당할 수 있으면
   해당되는 것을 모두 찾는다 (조건마다 별도 하위 질문). 예: '약점' 이 단점 목록 속성과 회피 조건 속성 둘 다에
   해당하면 둘 다 조회.
3. 한 단계에 서로 독립인 하위 질문을 최대 {MAX_CALLS_PER_STEP}개까지 동시에 보낼 수 있다 (예: 대상별 속성 조회).
4. 같은 질문을 반복하지 않는다. 질문에 답할 근거가 모이면 바로 finish 한다. 답변 작성은 하지 않는다.
5. 같은 사실을 표현만 바꿔 두 번 찾았는데도 근거가 없으면 더 찾지 말고 finish 한다 — 문서에 없는 사실일 수 있다.
6. 스크래치패드를 매 단계 갱신한다 (마크다운, 짧게):
   ## 질문에서 주어진 조건 — 사용자가 직접 말한 조건만 (예: 서비스 4종, 동시 접속 100명)
   ## 가정 — 질문에 없지만 판단에 쓰는 전제 (예: 팀 규모 작다고 가정). 답변에서 가정으로 밝혀야 한다
   ## 알게 된 것 — 검색으로 확인한 사실만 (출처 단계 번호)
   ## 후보 × 조건 — 조건이 둘 이상이면 표: | 후보 | 조건1 | 조건2 | 칸은 ✔(근거 있음) ✘(반대 근거) ?(미확인)
   ## 아직 모르는 것 — ? 칸과 빠진 정보
   ## 다음 — 다음 단계에서 확인할 것
7. 표에 ? 가 남아 있으면 finish 하지 말고 그 칸을 채우는 검색을 먼저 한다. 한 조건이 지식베이스 구조의
   여러 위치에 있을 수 있다 (예: 수정 용이성 = 적합 신호 속성과 품질 속성 목록 둘 다) — 한 곳에 없다고 ✘ 로 두지 말고 다른 위치도 확인.
   반대 근거(예: effect=negative)가 있으면 ✘.
8. 단계 수를 아껴라 — 한 후보에 필요한 여러 속성은 한 하위 질문으로 묶고("X 의 A, B, C"), 필요한 조회를 가능한 한 한 단계에 몰아라.
   단계마다 계획 시간이 든다.

JSON 만 출력:
{{"thought": "이번 단계에서 할 일과 이유 (한 문장)", "action": "search" | "finish",
  "calls": [{{"tool": "{tools[0]}", "query": "하위 질문"}}],
  "scratchpad": "갱신한 스크래치패드 전체",
  "note": "finish 일 때: 모은 근거로 답할 때 주의할 점 (예: 공통점만 추릴 것)"}}"""
    return [
        {"role": "system", "content": "You are a retrieval planner. Decide the next search step. Output JSON only."},
        {"role": "user", "content": user},
    ]


def parse_step(text: str, tools: List[str]) -> Dict[str, Any]:
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    # strict=False: GLM 이 스크래치패드 문자열 안에 줄바꿈을 그대로 넣는 경우 ("Invalid control character")
    try:
        d = json.loads(t, strict=False)
    except ValueError:
        s, e = t.find("{"), t.rfind("}")
        try:
            d = json.loads(t[s:e + 1], strict=False) if s != -1 and e > s else {}
        except ValueError:
            d = {}
    if not isinstance(d, dict):
        d = {}
    calls = []
    for c in d.get("calls") or []:
        if not isinstance(c, dict):
            continue
        tool, q = str(c.get("tool") or "").strip(), str(c.get("query") or "").strip()
        if tool not in tools:
            tool = tools[0]
        if q:
            calls.append({"tool": tool, "query": q[:300]})
    action = "finish" if d.get("action") == "finish" or not calls else "search"
    return {"thought": str(d.get("thought") or "")[:300], "action": action,
            "calls": calls[:MAX_CALLS_PER_STEP], "note": str(d.get("note") or "")[:500],
            "scratchpad": str(d.get("scratchpad") or "").strip()[:SCRATCHPAD_MAX]}


# ---------------------------------------------------------------------------
# 관찰 요약
# ---------------------------------------------------------------------------

def summarize_observation(results: List[Dict[str, Any]], meta: Optional[Dict[str, Any]]) -> str:
    meta = meta or {}
    parts = []
    mode = graph_mode(meta)
    if mode:
        parts.append(f"경로 {mode}")
    if meta.get("result_summary"):
        parts.append("계획 결과: " + str(meta["result_summary"]).replace("\n", " ")[:600])
    triples = [t for t in meta.get("triples") or [] if isinstance(t, dict)]
    if triples:
        tx = "; ".join(f"{t.get('subject')} {t.get('predicate')} {t.get('object')}" for t in triples[:25])
        parts.append(f"트리플 {len(triples)}건: {tx[:1500]}")
    real = [r for r in results or [] if r.get("chunk_id") != "GRAPH_METADATA_ONLY"]
    if real:
        snip = " | ".join((r.get("content") or "").replace("\n", " ")[:160] for r in real[:3])
        parts.append(f"청크 {len(real)}건: {snip}")
    if not triples and not real:
        parts.append("근거 없음")
    return " / ".join(parts)


def _triple_key(t: Dict[str, Any]) -> Tuple[str, str, str]:
    return (str(t.get("subject")), str(t.get("predicate")), str(t.get("object")))


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

async def run_agentic(
    ctx,
    params: Dict[str, Any],
    tool_stages: Dict[str, Tuple[str, Dict[str, Any]]],
    run_stage: Callable,
    planner_cfg: Dict[str, Any],
    first: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """단계 루프. tool_stages: {도구명: (스테이지 type, params)}. run_stage(type, params, query) → (results, meta).

    first: auto 사후 승격일 때 이미 실행한 단일 실행 결과 {"results","meta"} — 단계 0 으로 기록.
    반환: {"results", "graph_metadata", "steps", "stop_reason"}
    """
    from app.core.llm import achat, no_thinking_extra_body

    max_steps = int(params.get("max_steps") or DEFAULT_MAX_STEPS)
    if first is not None:
        max_steps = min(max_steps, int(params.get("escalated_max_steps") or ESCALATED_MAX_STEPS))
    budget = float(params.get("time_budget_s") or DEFAULT_TIME_BUDGET_S)
    # 예산은 파이프라인 시작 기준 (승격 전 단일 실행 시간 포함)
    t0 = float((getattr(ctx, "metadata", None) or {}).get("_started_at") or time.time())
    tools = list(tool_stages.keys())
    log = ctx.logs.append

    kb_summary = await describe_kb(ctx.kb_id, ctx.graph_backend, ctx.metadata.get("llm_model_config"))
    log(f"[Agentic] 도구: {', '.join(tools)} | 상한 {max_steps}단계·{budget:g}초 | KB 구조 {len(kb_summary)}자")

    history: List[Dict[str, Any]] = []
    gathered: List[Dict[str, Any]] = []   # 호출별 {"step","query","results","meta"}
    seen_calls = set()
    stop_reason, note = "단계 상한", ""

    if first is not None:
        obs = summarize_observation(first["results"], first["meta"])
        history.append({"step": 0, "thought": "단일 실행 결과 (근거 부족으로 단계 진행)",
                        "calls": [{"tool": tools[0], "query": ctx.query, "observation": obs, "sec": 0}]})
        gathered.append({"step": 0, "query": ctx.query, **first})
        seen_calls.add((tools[0], ctx.query))
        log(f"[Agentic] 단계 0 (단일 실행): {obs[:300]}")

    model = planner_cfg.get("model")
    scratchpad = ""   # 에이전트 메모 — 단계마다 갱신해 다음 단계로 넘기고, 마지막 것은 답변 모델에 전달
    finish_rejected = False
    for step_no in range(1, max_steps + 1):
        # 남은 예산이 계획 1회 + 검색 1회에 못 미치면 새 단계를 시작하지 않는다 (중간에 잘린 검색은 근거가 안 됨)
        if budget - (time.time() - t0) < MIN_STEP_S:
            stop_reason = "시간 상한"
            break
        ts = time.time()
        try:
            raw = await achat(planner_cfg, build_step_messages(ctx.query, kb_summary, tools, history, step_no, max_steps,
                                                               scratchpad=scratchpad),
                              model=model, temperature=0, response_format={"type": "json_object"},
                              extra_body=no_thinking_extra_body(model), timeout=60)
            plan = parse_step(raw, tools)
        except Exception as e:
            log(f"[Agentic] 단계 {step_no} 계획 실패: {str(e)[:200]}")
            stop_reason = "계획 실패"
            break
        plan_sec = time.time() - ts
        if plan.get("scratchpad"):
            scratchpad = plan["scratchpad"]
        if plan["action"] == "finish":
            unknown = count_unknown(scratchpad)
            # 표에 ? 가 남았는데 종료하려 하면 한 번은 되돌린다 (계획 LLM 이 규칙을 어기는 경우) — 시간·단계가 남아 있을 때만
            if unknown and not finish_rejected and step_no < max_steps and budget - (time.time() - t0) > 2 * MIN_STEP_S:
                finish_rejected = True
                history.append({"step": step_no, "thought": f"종료 보류 — 스크래치패드 표에 ? {unknown}칸이 남음. 그 칸을 채우는 검색을 먼저 할 것",
                                "calls": [], "scratchpad": scratchpad})
                log(f"[Agentic] 단계 {step_no}: 종료 보류 — 미확인(?) {unknown}칸 남음")
                continue
            note = plan["note"]
            stop_reason = "근거 충분" if not unknown else f"종료 (미확인 {unknown}칸 남음)"
            log(f"[Agentic] 단계 {step_no}: 종료 — {plan['thought']} ({plan_sec:.1f}초)")
            break
        calls = [c for c in plan["calls"] if (c["tool"], c["query"]) not in seen_calls]
        if not calls:
            stop_reason = "새 검색 없음 (반복)"
            log(f"[Agentic] 단계 {step_no}: 이미 한 검색만 제안 → 종료")
            break
        for c in calls:
            seen_calls.add((c["tool"], c["query"]))
        log(f"[Agentic] 단계 {step_no}: {plan['thought']} (계획 {plan_sec:.1f}초)")

        remaining = max(MIN_STEP_S / 2, budget - (time.time() - t0))
        call_timeout = min(float(params.get("call_timeout_s") or CALL_TIMEOUT_S), remaining)

        async def one(c):
            st_type, st_params = tool_stages[c["tool"]]
            tc = time.time()
            try:
                res, meta = await asyncio.wait_for(run_stage(st_type, st_params, c["query"]), timeout=call_timeout)
            except asyncio.TimeoutError:
                res, meta = [], {"error": f"{call_timeout:.0f}초 초과로 중단"}
            except Exception as e:
                res, meta = [], {"error": str(e)[:200]}
            return c, res, meta or {}, time.time() - tc

        outs = list(await asyncio.gather(*(one(c) for c in calls)))
        # 실패(시간 초과·오류)한 하위 검색은 남은 시간 안에서 하나씩 한 번 더 — 동시 실행이 공급자 한도에 걸렸을 수 있다
        for k, (c, res, meta, sec) in enumerate(outs):
            if meta.get("error") and budget - (time.time() - t0) > MIN_STEP_S:
                c2, res2, meta2, sec2 = await one(c)
                if not meta2.get("error"):
                    outs[k] = (c2, res2, meta2, sec + sec2)
                    log(f"[Agentic]   ↻ 재시도 성공: {c['query']}")
        rec = {"step": step_no, "thought": plan["thought"], "calls": [], "scratchpad": plan.get("scratchpad") or ""}
        for c, res, meta, sec in outs:
            obs = ("오류: " + meta["error"]) if meta.get("error") else summarize_observation(res, meta)
            rec["calls"].append({"tool": c["tool"], "query": c["query"], "observation": obs, "sec": round(sec, 1),
                                 "mode": graph_mode(meta)})
            gathered.append({"step": step_no, "query": c["query"], "results": res, "meta": meta})
            log(f"[Agentic]   └ {c['tool']}(\"{c['query']}\") {sec:.1f}초 → {obs[:300]}")
        history.append(rec)
        if rec["calls"] and all(str(c["observation"]).startswith("오류") for c in rec["calls"]):
            log(f"[Agentic] 단계 {step_no}: 하위 검색이 모두 실패")
    else:
        stop_reason = "단계 상한"

    # 근거 충분으로 끝나지 않았으면(시간·단계 상한, 반복) 지금까지의 관찰로 스크래치패드를 한 번 정리 — 검색은 하지 않는다
    if stop_reason in ("시간 상한", "단계 상한", "새 검색 없음 (반복)") and history:
        try:
            raw = await achat(planner_cfg, build_step_messages(ctx.query, kb_summary, tools, history, len(history) + 1,
                                                               max_steps, scratchpad=scratchpad, final=True),
                              model=model, temperature=0, response_format={"type": "json_object"},
                              extra_body=no_thinking_extra_body(model), timeout=25)
            fin = parse_step(raw, tools)
            if fin.get("scratchpad"):
                scratchpad = fin["scratchpad"]
            note = note or fin.get("note") or ""
        except Exception as e:
            log(f"[Agentic] 스크래치패드 정리 실패: {str(e)[:150]}")
    if scratchpad:
        log("[Agentic] 스크래치패드:\n" + scratchpad)

    merged = merge_evidence(gathered, note, query=ctx.query, history=history, scratchpad=scratchpad)
    total = time.time() - t0
    log(f"[Agentic] 종료: {stop_reason} | {len(history)}단계 {total:.1f}초 | 근거 청크 {len(merged['results'])}건 · "
        f"트리플 {len(merged['graph_metadata']['triples'])}건")
    merged["graph_metadata"]["reasoning"] = {
        "targeting": {"mode": "AG", "reason": f"에이전틱 {len(history)}단계 ({stop_reason})"},
        "agentic": {"steps": history, "stop_reason": stop_reason, "seconds": round(total, 1), "note": note,
                    "scratchpad": scratchpad},
    }
    merged.update({"steps": history, "stop_reason": stop_reason})
    return merged


def merge_evidence(gathered: List[Dict[str, Any]], note: str = "", query: str = "",
                   history: Optional[List[Dict[str, Any]]] = None, scratchpad: str = "") -> Dict[str, Any]:
    """호출별 근거 병합. 청크는 호출마다 돌아가며(라운드로빈) 넣어 대상별 근거가 모두 상위에 오게 한다."""
    triples, tseen = [], set()
    summaries = []
    for g in gathered:
        meta = g.get("meta") or {}
        for t in meta.get("triples") or []:
            if isinstance(t, dict):
                k = _triple_key(t)
                if k not in tseen and len(triples) < MAX_TRIPLES:
                    tseen.add(k)
                    triples.append(t)
        if meta.get("result_summary"):
            summaries.append(f"[단계 {g['step']}: {g['query']}]\n{meta['result_summary']}")
    queues = [[r for r in (g.get("results") or []) if r.get("chunk_id") != "GRAPH_METADATA_ONLY"] for g in gathered]
    results, cseen = [], set()
    while any(queues):
        for q in queues:
            if not q:
                continue
            r = q.pop(0)
            cid = r.get("chunk_id") or r.get("id") or (r.get("content") or "")[:80]
            if cid in cseen:
                continue
            cseen.add(cid)
            r = dict(r)
            r.pop("graph_metadata", None)
            results.append(r)
    for i, r in enumerate(results):
        r["score"] = 1.0 - i * 0.001  # 병합 순서 유지 (실행기가 점수로 재정렬한다)
    # 답변 모델이 일부 단계만 보고 답하지 않도록, 검색 과정과 "모든 단계를 종합" 지시를 맨 앞에 둔다
    head = []
    if history:
        head.append("에이전틱 검색 과정 (질문을 나눠 단계별로 찾음) — 아래 모든 단계의 결과를 합쳐서 원래 질문에 답할 것. "
                    "앞 단계에서 찾은 대상 전체를 빠짐없이 다룰 것.")
        if query:
            head.append(f"원래 질문: {query}")
        for h in history:
            qs = "; ".join(f"{c['query']}" + (" (실패)" if str(c.get("observation", "")).startswith("오류") else "")
                           for c in h["calls"])
            head.append(f"- 단계 {h['step']}: {h.get('thought', '')} → {qs}")
    if scratchpad:
        head.append("[에이전트 스크래치패드 — 단계별로 확인한 내용. 후보 × 조건 표의 ✔(근거 있음)/✘(반대 근거)/?(미확인)를 지켜 답하고, "
                    "? 는 '확인되지 않음' 으로 밝힐 것. '가정' 항목은 사용자가 말하지 않은 전제이므로 답변에서 가정이라고 밝힐 것]\n" + scratchpad)
    if note:
        head.append(f"[답변 시 유의] {note}")
    summary = "\n".join(head) + ("\n\n" if head and summaries else "") + "\n\n".join(summaries)
    meta = {"triples": triples, "result_summary": summary or None, "trace_logs": []}
    return {"results": results, "graph_metadata": meta}
