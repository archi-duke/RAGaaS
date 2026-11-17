"""파이프라인 운영/테스트 분리 + 버전 이력 (공용 Gitea 커밋).

설계: docs/design/agent/design-search-entry-and-pipeline-versions.md §5

- 운영 구성: kb.pipeline_config (검색은 이것만 읽는다 — Gitea 가 멈춰도 검색은 된다)
- 테스트 구성: kb.pipeline_draft (자동 저장, Git 에 넣지 않음)
- 운영 반영 한 번 = 커밋 하나: {GITEA_ORG}/{GITEA_PIPELINE_REPO} 의 kb/<kb_id>/pipeline.json
- 반영 순서: Gitea 커밋 성공 → Mongo 갱신. Gitea 가 안 되면 반영 실패, 운영은 그대로.

환경 변수: GITEA_SERVER(host:port), GITEA_TOKEN, GITEA_ORG(기본 ragaas), GITEA_PIPELINE_REPO(기본 ragaas-pipelines)
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

SCHEMA = "ragaas.pipeline/v1"
TIMEOUT = 8.0
KNOWN_STAGES = {"smalltalk", "agentic", "graph", "ann", "bm25", "brute_force", "rerank", "ner_filter"}


class GitUnavailable(RuntimeError):
    """이력 저장소(Gitea)에 닿지 못함 — 반영·이력 조회만 실패한다."""


# ---------------------------------------------------------------------------
# 구성 JSON
# ---------------------------------------------------------------------------

def normalize(config: Dict[str, Any]) -> Dict[str, Any]:
    """저장 형식으로: schema 머리 + stages. 모르는 키는 보존한다 (옛 버전을 불러올 때 깨지지 않게)."""
    if not isinstance(config, dict) or not isinstance(config.get("stages"), list):
        raise ValueError("구성에 'stages' 배열이 없습니다")
    out = {k: v for k, v in config.items() if not k.startswith("_")}
    out["schema"] = SCHEMA
    out["stages"] = [{"type": s.get("type"), "params": s.get("params") or {},
                      **({"id": s["id"]} if s.get("id") else {})}
                     for s in config["stages"] if isinstance(s, dict) and s.get("type")]
    return out


def warnings_of(config: Dict[str, Any]) -> List[str]:
    unknown = [s["type"] for s in config.get("stages") or [] if s.get("type") not in KNOWN_STAGES]
    return [f"지금 없는 스테이지: {', '.join(unknown)} (실행 때 건너뜀)"] if unknown else []


def dumps(config: Dict[str, Any]) -> str:
    return json.dumps(normalize(config), ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def config_hash(config: Optional[Dict[str, Any]]) -> str:
    if not config:
        return ""
    body = {"stages": normalize(config)["stages"]}
    return hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def diff(old: Optional[Dict[str, Any]], new: Optional[Dict[str, Any]]) -> List[str]:
    """사람이 읽는 차이 목록: 'graph.max_hops 6 → 8', '스테이지 추가: rerank'."""
    def flat(cfg):
        rows: Dict[str, Any] = {}
        order: List[str] = []
        for s in (cfg or {}).get("stages") or []:
            t = s.get("type")
            order.append(t)
            for k, v in (s.get("params") or {}).items():
                rows[f"{t}.{k}"] = v
        return order, rows
    o_ord, o = flat(old)
    n_ord, n = flat(new)
    out: List[str] = []
    for t in n_ord:
        if t not in o_ord:
            out.append(f"스테이지 추가: {t}")
    for t in o_ord:
        if t not in n_ord:
            out.append(f"스테이지 제거: {t}")
    if [t for t in o_ord if t in n_ord] != [t for t in n_ord if t in o_ord]:
        out.append(f"스테이지 순서: {' → '.join(o_ord)}  ⇒  {' → '.join(n_ord)}")
    for k in list(dict.fromkeys(list(o) + list(n))):
        if k.split(".")[0] not in o_ord or k.split(".")[0] not in n_ord:
            continue
        if o.get(k) != n.get(k):
            fmt = lambda v: "없음" if v is None else json.dumps(v, ensure_ascii=False)[:60]
            out.append(f"{k} {fmt(o.get(k))} → {fmt(n.get(k))}")
    return out


# ---------------------------------------------------------------------------
# Gitea (REST, 작업 사본 없음)
# ---------------------------------------------------------------------------

def _cfg() -> Tuple[str, str, str, str]:
    server = (os.getenv("GITEA_SERVER") or "").strip().rstrip("/")
    token = (os.getenv("GITEA_TOKEN") or "").strip()
    if not server or not token:
        raise GitUnavailable("이력 저장소(Gitea)가 설정되지 않았습니다 — GITEA_SERVER·GITEA_TOKEN")
    if not server.startswith("http"):
        server = "http://" + server
    return server, token, os.getenv("GITEA_ORG", "ragaas"), os.getenv("GITEA_PIPELINE_REPO", "ragaas-pipelines")


async def _req(method: str, path: str, **kw) -> httpx.Response:
    server, token, _, _ = _cfg()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.request(method, f"{server}/api/v1{path}",
                                headers={"Authorization": f"token {token}"}, **kw)
    except httpx.HTTPError as e:
        raise GitUnavailable(f"이력 저장소(Gitea)에 연결할 수 없습니다: {type(e).__name__}") from e
    if r.status_code in (401, 403):
        raise GitUnavailable(f"이력 저장소 권한 없음 ({r.status_code}) — GITEA_TOKEN 확인")
    if r.status_code >= 500:
        raise GitUnavailable(f"이력 저장소 오류 ({r.status_code})")
    return r


def _file(kb_id: str) -> str:
    return f"kb/{kb_id}/pipeline.json"


async def ensure_repo() -> None:
    _, _, org, repo = _cfg()
    r = await _req("GET", f"/repos/{org}/{repo}")
    if r.status_code == 200:
        return
    r = await _req("POST", f"/orgs/{org}/repos", json={
        "name": repo, "private": True, "auto_init": True, "default_branch": "main",
        "description": "RAGaaS KB 파이프라인 구성 이력 (반영 = 커밋)"})
    if r.status_code not in (201, 409):
        raise GitUnavailable(f"저장소를 만들 수 없습니다 ({r.status_code}): {r.text[:200]}")


async def read_file(kb_id: str, ref: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(구성, 파일 blob sha). 파일이 없으면 (None, None)."""
    _, _, org, repo = _cfg()
    r = await _req("GET", f"/repos/{org}/{repo}/contents/{_file(kb_id)}", params={"ref": ref} if ref else None)
    if r.status_code == 404:
        return None, None
    d = r.json()
    return json.loads(base64.b64decode(d["content"]).decode("utf-8")), d.get("sha")


async def commit_file(kb_id: str, config: Dict[str, Any], message: str) -> str:
    """kb/<kb_id>/pipeline.json 을 커밋하고 커밋 SHA 를 돌려준다."""
    _, _, org, repo = _cfg()
    await ensure_repo()
    _, blob = await read_file(kb_id)
    body = {"content": base64.b64encode(dumps(config).encode("utf-8")).decode(), "message": message,
            "branch": "main"}
    if blob:
        body["sha"] = blob
    r = await _req("PUT" if blob else "POST", f"/repos/{org}/{repo}/contents/{_file(kb_id)}", json=body)
    if r.status_code not in (200, 201):
        raise GitUnavailable(f"커밋 실패 ({r.status_code}): {r.text[:200]}")
    return r.json()["commit"]["sha"]


async def list_commits(kb_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """이 KB 파일의 커밋 (최신 먼저) + 순번(v1 = 첫 커밋)."""
    _, _, org, repo = _cfg()
    r = await _req("GET", f"/repos/{org}/{repo}/commits",
                   params={"path": _file(kb_id), "limit": max(1, min(limit, 100)), "stat": "false",
                           "files": "false", "verification": "false", "sha": "main"})
    if r.status_code == 404:
        return []
    rows = r.json() or []
    total = int(r.headers.get("X-Total-Count") or len(rows))
    out = []
    for i, c in enumerate(rows):
        msg = (c.get("commit") or {}).get("message") or ""
        out.append({"version": total - i, "ref": c.get("sha"), "created_at": (c.get("commit") or {}).get("author", {}).get("date"),
                    "note": msg.split("\n", 1)[0], "message": msg})
    return out


# ---------------------------------------------------------------------------
# 운영/테스트 동작
# ---------------------------------------------------------------------------

async def _kb(kb_id: str):
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise LookupError("Knowledge Base not found")
    return kb


def live_of(kb) -> Dict[str, Any]:
    return kb.pipeline_config if isinstance(kb.pipeline_config, dict) and kb.pipeline_config.get("stages") is not None \
        else {"stages": []}


def state(kb) -> Dict[str, Any]:
    live = live_of(kb)
    draft = kb.pipeline_draft if kb.pipeline_draft is not None else copy.deepcopy(live)
    changes = diff(live, draft)
    return {"stages": live.get("stages") or [],            # 하위 호환 (옛 화면)
            "live": {"ref": kb.pipeline_live_ref, "config": live},
            "draft": draft, "draft_base": kb.pipeline_draft_base or kb.pipeline_live_ref,
            "dirty": bool(changes), "changes": changes}


async def save_draft(kb_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    kb = await _kb(kb_id)
    kb.pipeline_draft = normalize(config)
    if not kb.pipeline_draft_base:
        kb.pipeline_draft_base = kb.pipeline_live_ref
    kb.updated_at = datetime.utcnow()
    await kb.save()
    return state(kb)


async def _set_live(kb, config: Dict[str, Any], ref: str) -> None:
    kb.pipeline_config = normalize(config)
    kb.pipeline_live_ref = ref
    kb.updated_at = datetime.utcnow()
    await kb.save()


async def publish(kb_id: str, note: str = "") -> Dict[str, Any]:
    """테스트 구성 → Gitea 커밋 → 운영 지정. 변경이 없으면 커밋하지 않는다."""
    kb = await _kb(kb_id)
    live = live_of(kb)
    draft = kb.pipeline_draft if kb.pipeline_draft is not None else live
    changes = diff(live, draft)
    if not changes and kb.pipeline_live_ref:
        return {"ok": True, "unchanged": True, "message": "반영할 변경 없음", **state(kb)}
    msg = (note.strip() or "운영 반영") + "\n\n" + ("\n".join(f"- {c}" for c in changes) or "- 첫 커밋")
    ref = await commit_file(kb_id, draft, msg)          # 실패하면 GitUnavailable — 운영은 그대로
    await _set_live(kb, draft, ref)
    kb.pipeline_draft_base = ref
    await kb.save()
    return {"ok": True, "ref": ref, "changes": changes, **state(kb)}


async def load_version(kb_id: str, ref: str) -> Dict[str, Any]:
    """그 버전을 테스트 구성으로 불러온다 (운영은 그대로)."""
    kb = await _kb(kb_id)
    cfg, _ = await read_file(kb_id, ref)
    if cfg is None:
        raise LookupError("그 버전에 이 KB 의 구성이 없습니다")
    kb.pipeline_draft = normalize(cfg)
    kb.pipeline_draft_base = ref
    await kb.save()
    return {**state(kb), "warnings": warnings_of(cfg)}


async def activate_version(kb_id: str, ref: str, version: Optional[int] = None) -> Dict[str, Any]:
    """그 버전의 내용을 새 커밋('되돌림: vN')으로 올리고 운영 지정 — 이력은 한 줄로만 쌓인다."""
    kb = await _kb(kb_id)
    cfg, _ = await read_file(kb_id, ref)
    if cfg is None:
        raise LookupError("그 버전에 이 KB 의 구성이 없습니다")
    changes = diff(live_of(kb), cfg)
    label = f"v{version}" if version else ref[:8]
    new_ref = await commit_file(kb_id, cfg, f"되돌림: {label} ({ref[:8]})\n\n" + "\n".join(f"- {c}" for c in changes))
    await _set_live(kb, cfg, new_ref)
    return {"ok": True, "ref": new_ref, "changes": changes, **state(kb)}


async def bootstrap(kb_id: str) -> Dict[str, Any]:
    """이관: 지금 운영 구성을 첫 커밋('초기 구성')으로 올린다. 이미 있으면 그대로."""
    kb = await _kb(kb_id)
    if kb.pipeline_live_ref:
        return {"ok": True, "skipped": "이미 이력 있음", "ref": kb.pipeline_live_ref}
    existing, _ = await read_file(kb_id)
    live = live_of(kb)
    if existing is not None and config_hash(existing) == config_hash(live):
        commits = await list_commits(kb_id, 1)
        ref = commits[0]["ref"] if commits else None
    else:
        ref = await commit_file(kb_id, live, f"초기 구성 — {kb.name}\n\n기존 운영 구성을 이력으로 옮김")
    kb.pipeline_live_ref = ref
    if kb.pipeline_draft is None:
        kb.pipeline_draft = normalize(live)
        kb.pipeline_draft_base = ref
    await kb.save()
    return {"ok": True, "ref": ref}
