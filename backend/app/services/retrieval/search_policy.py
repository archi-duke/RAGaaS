"""KB 검색 정책 — 파이프라인 구성을 해석해 채팅·API·MCP 가 같은 기준으로 동작하게 한다.

설계: docs/design/agent/design-search-entry-and-pipeline-versions.md

- 파이프라인 설정 = 그 KB 의 검색 정책 (운영 = kb.pipeline_config, 테스트 = kb.pipeline_draft).
- 검색 필터(graph·ann·bm25·brute_force)가 있어야 그 검색을 한다. 하나도 없으면 "검색 필터 없음".
- 옵션은 켜져 있으면 실행, 꺼져 있으면 그 단계만 건너뛴다 (건너뛴 사실을 applied_policy 로 알린다).
- MCP 는 에이전틱 스테이지를 건너뛴다 (외부 에이전트가 이미 에이전틱 역할).
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

SEARCH_STAGES = ("graph", "ann", "bm25", "brute_force")   # 결과를 만드는 검색 필터
POST_STAGES = ("rerank", "ner_filter")                     # 결과를 다듬는 후처리 필터
GATE_STAGE = "smalltalk"
AGENTIC_STAGE = "agentic"


def stages_of(pipeline: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in ((pipeline or {}).get("stages") or []) if isinstance(s, dict) and s.get("type")]


async def resolve_pipeline(kb, config: Optional[str] = "live",
                           inline: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """실행할 구성과 그 출처. inline(편집 중인 구성) > draft(테스트) > live(운영)."""
    live = kb.pipeline_config if (kb.pipeline_config or {}).get("stages") is not None else {"stages": []}
    if inline and inline.get("stages") is not None:
        return inline, {"kind": "inline"}
    if (config or "live") == "draft":
        draft = getattr(kb, "pipeline_draft", None)
        if draft and draft.get("stages") is not None:
            return draft, {"kind": "draft", "base": getattr(kb, "pipeline_draft_base", None)}
        return live, {"kind": "draft", "note": "테스트 구성 없음 — 운영 구성으로 실행"}
    return live, {"kind": "live", "ref": getattr(kb, "pipeline_live_ref", None)}


def without_agentic(pipeline: Dict[str, Any]) -> Dict[str, Any]:
    p = copy.deepcopy(pipeline or {})
    p["stages"] = [s for s in stages_of(p) if s.get("type") != AGENTIC_STAGE]
    return p


def graph_options(params: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.retrieval.chain_query import resolve_max_hops
    return {
        "max_hops": resolve_max_hops(params or {}),
        "typo_synonym": bool((params or {}).get("resolve_terms", True)),
        "list_supplement": bool((params or {}).get("list_supplement", True)),
        "graph_fallback": (params or {}).get("graph_fallback") or "vector",
    }


def summarize(pipeline: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """구성 → 정책 요약 (describe_kb 의 policy, 응답의 applied_policy)."""
    st = stages_of(pipeline)
    types = [s["type"] for s in st]
    graph = next((s for s in st if s["type"] == "graph"), None)
    return {
        "search_filters": [t for t in types if t in SEARCH_STAGES],
        "post_filters": [t for t in types if t in POST_STAGES],
        "gate": GATE_STAGE in types,
        "agentic": AGENTIC_STAGE in types,
        "answer_check": "answer_check" in types,      # 답변 근거 검사 카드 (답변 뒤)
        "graph": graph_options(graph.get("params") or {}) if graph else None,
    }


async def kb_policy(kb_id: str, config: str = "live") -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        return {"exists": False}
    p, meta = await resolve_pipeline(kb, config)
    return {"exists": True, "config": meta, **summarize(p)}


def disabled(reason: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "disabled", "reason": reason,
            "policy": {k: v for k, v in policy.items() if k != "exists"}}


async def guard(kb_id: str, need: str) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """MCP·조회 API 용: 운영 구성에 필요한 검색 필터가 없으면 disabled 응답을 돌려준다.

    need = "graph" (그래프 조회 도구) | "search" (아무 검색 필터나 — 근거 청크 조회)
    """
    pol = await kb_policy(kb_id, "live")
    if not pol.get("exists"):
        return pol, None          # KB 없음은 각 도구가 원래대로 404 처리
    if need == "graph" and "graph" not in pol["search_filters"]:
        return pol, disabled("이 KB 의 운영 파이프라인에 Graph 필터가 없어 그래프 검색을 하지 않습니다.", pol)
    if need == "search" and not pol["search_filters"]:
        return pol, disabled("이 KB 의 운영 파이프라인에 검색 필터가 없습니다 — 검색 결과 없음.", pol)
    return pol, None


def policy_view(pol: Dict[str, Any]) -> Dict[str, Any]:
    """describe_kb 응답의 policy — 클라이언트가 어떤 도구가 쓸모 있는지·Max Hop 을 알게 한다."""
    g = pol.get("graph") or {}
    return {"search_filters": pol.get("search_filters"), "post_filters": pol.get("post_filters"),
            "max_hops": g.get("max_hops"), "typo_synonym": g.get("typo_synonym"),
            "graph_fallback": g.get("graph_fallback"),
            "note": "max_hops 는 연쇄 조회 깊이의 상한 — 클라이언트가 지킨다. "
                    "graph_fallback=none 이면 그래프로 못 찾은 것을 문서 검색(search)으로 메우지 않는다."}
