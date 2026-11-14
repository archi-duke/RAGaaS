"""스키마 기준 재추출 (승격 L2, 옵션) — docs/design-graph-promotion.md §3(c) L2

확정된 스키마로 저장된 청크를 다시 추출한다. LLM 비용이 들고 결과가 스키마 품질에 좌우되므로
사용자가 설명을 보고 선택해 실행하는 옵션이다 (UI: 문서 탭 "고급" → "스키마 기준 재추출").
- 전제: KB schema_status == "active" (승격 초안 검토·적용 후)
- 직전 추출 결과를 백업 → 되돌리기 가능
- 스키마 밖 사실은 버리지 않고 저장 → 완료 후 감지기가 새 속성 제안으로
"""

import asyncio
import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
REEXTRACT_DOC_CONCURRENCY = 2


def _is_text(filename: str) -> bool:
    return str(filename or "").lower().rsplit(".", 1)[-1] not in ("json", "yaml", "yml")


async def build_schema_spec(kb) -> Dict[str, Any]:
    """확정 스키마 명세: 클래스(설명·멤버), 속성(domain·별칭·관측 값 어휘)."""
    from app.core.fuseki import fuseki_client
    from app.services.schema_alignment.service import active_rules

    ind = (kb.promotion_metadata or {}).get("induction") or {}
    rules = await active_rules(str(kb.id))
    members: Dict[str, List[str]] = {}
    for r in rules:
        if r.rule_type == "class" and r.source_value and r.target_value:
            members.setdefault(r.target_value, []).append(r.source_value)
    classes = [{"name": c["name"], "description": c.get("description", ""), "members": members.get(c["name"], [])}
               for c in ind.get("classes", [])]
    props = []
    for p in ind.get("properties", []):
        q = f"""SELECT ?ol (COUNT(*) AS ?n) WHERE {{ GRAPH ?g {{ ?s <http://rag.local/rel/{p['name']}> ?o
              OPTIONAL {{ ?o <http://www.w3.org/2000/01/rdf-schema#label> ?l }} BIND(COALESCE(?l, STR(?o)) AS ?ol) }}
              FILTER(STRSTARTS(STR(?g), "urn:doc:")) }} GROUP BY ?ol ORDER BY DESC(?n) LIMIT 40"""
        vals = []
        try:
            for b in fuseki_client.query_sparql(str(kb.id), q).get("results", {}).get("bindings", []):
                v = b["ol"]["value"]
                if len(v) <= 25:
                    vals.append(v)
        except Exception:
            pass
        props.append({"name": p["name"], "domain": p.get("domain", ""), "aliases": p.get("members", []),
                      "values": vals[:15]})
    return {"classes": classes, "properties": props}


async def _model_options(kb) -> Dict[str, Dict[str, Any]]:
    """선택 가능한 추출 모델: KB 추출(인제스트) 모델, 그래프 검색 모델."""
    from app.api.document import _build_and_validate_upload_model_configs
    from app.core.models_resolver import resolve_model_config
    opts: Dict[str, Dict[str, Any]] = {}
    try:
        mc = await _build_and_validate_upload_model_configs(
            kb=kb, final_config=dict(kb.chunking_config or {}), chunking_cfg={"strategy": "fixed_size"},
            graph_config={"extractor_type": "simple"}, enable_subject_restoration=False,
            enable_entity_normalization=False)
        if mc.get("ingest_llm"):
            opts["ingest"] = mc["ingest_llm"]
    except Exception as e:
        logger.warning(f"[Reextract] ingest model unavailable: {e}")
    for st in (kb.pipeline_config or {}).get("stages") or []:
        if st.get("type") == "graph" and (st.get("params") or {}).get("llm_model"):
            try:
                opts["graph"] = await resolve_model_config(st["params"]["llm_model"])
            except Exception:
                pass
    return opts


async def estimate(kb_id: str) -> Dict[str, Any]:
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise ValueError("KB not found")
    docs = [d for d in await Document.find(Document.kb_id == kb_id).to_list() if _is_text(d.filename)]
    spec = await build_schema_spec(kb)
    opts = await _model_options(kb)
    meta = (kb.promotion_metadata or {}).get("reextract") or {}
    return {
        "eligible": kb.schema_status == "active" and bool(spec["properties"]),
        "reason": None if kb.schema_status == "active" else "승격 초안을 검토·적용(active)한 뒤에 실행할 수 있습니다.",
        "schema": {"classes": len(spec["classes"]), "properties": len(spec["properties"])},
        "documents": [{"id": str(d.id), "filename": d.filename, "chunks": d.chunk_count or 0,
                       "triples": d.triple_count or 0} for d in docs],
        "total_chunks": sum(d.chunk_count or 0 for d in docs),
        "models": {k: v.get("model") for k, v in opts.items()},
        "last_run": meta or None,
    }


async def _save_status(kb_id: str, patch: Dict[str, Any], doc_patch: Optional[Dict[str, Any]] = None) -> None:
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    meta = dict(kb.promotion_metadata or {})
    st = dict(meta.get("reextract") or {})
    st.update(patch)
    if doc_patch:
        docs = dict(st.get("docs") or {})
        for k, v in doc_patch.items():
            docs[k] = {**docs.get(k, {}), **v}
        st["docs"] = docs
    meta["reextract"] = st
    kb.promotion_metadata = meta
    await kb.save()


async def start(kb_id: str, doc_ids: Optional[List[str]], model_key: str = "ingest") -> Dict[str, Any]:
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase
    from app.services.ingestion.ingest_client import ingest_client
    from app.services.schema_alignment.service import rules_for_ingest, detect_proposals
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend

    kb = await KnowledgeBase.get(kb_id)
    if not kb or kb.schema_status != "active":
        raise ValueError("스키마가 적용(active)된 KB 에서만 재추출할 수 있습니다.")
    if ((kb.promotion_metadata or {}).get("reextract") or {}).get("status") == "running":
        raise ValueError("이미 재추출이 진행 중입니다.")
    opts = await _model_options(kb)
    llm = opts.get(model_key) or opts.get("ingest")
    if not llm:
        raise ValueError("재추출 모델을 확인할 수 없습니다 (KB 추출 모델 설정 필요).")
    docs = [d for d in await Document.find(Document.kb_id == kb_id).to_list() if _is_text(d.filename)]
    if doc_ids:
        docs = [d for d in docs if str(d.id) in set(doc_ids)]
    spec = await build_schema_spec(kb)
    rules = await rules_for_ingest(kb_id, include_graph_rules=True)
    store = "fuseki" if kb.graph_backend == "ontology" else "neo4j"
    await _save_status(kb_id, {"status": "running", "started_at": datetime.utcnow().isoformat(),
                               "model": llm.get("model"), "docs": {}},
                       {str(d.id): {"filename": d.filename, "state": "queued"} for d in docs})

    async def run_all():
        sem = asyncio.Semaphore(REEXTRACT_DOC_CONCURRENCY)

        async def one(d):
            async with sem:
                did = str(d.id)
                prev_status = d.pipeline_status
                d.pipeline_status = "REEXTRACTING"
                await d.save()
                await _save_status(kb_id, {}, {did: {"state": "running"}})
                try:
                    r = await ingest_client.reextract(kb_id, did, store, spec, llm, rules or None)
                    cur = await Document.get(did)
                    if cur:
                        cur.triple_count = r.get("after_rules", cur.triple_count)
                        cur.pipeline_status = prev_status or "COMPLETED"
                        await cur.save()
                    await _save_status(kb_id, {}, {did: {"state": "done", "triples_before": d.triple_count,
                                                         "triples": r.get("triples"),
                                                         "out_of_schema": r.get("out_of_schema"),
                                                         "chunk_failures": len(r.get("chunk_failures") or [])}})
                except Exception as e:
                    cur = await Document.get(did)
                    if cur:
                        cur.pipeline_status = prev_status or "COMPLETED"
                        await cur.save()
                    await _save_status(kb_id, {}, {did: {"state": "failed", "error": str(e)[:300]}})

        await asyncio.gather(*(one(d) for d in docs))
        FusekiBackend.invalidate_class_catalog(kb_id)
        try:
            await detect_proposals(kb_id)   # 스키마 밖 사실 → 새 속성·값 제안
        except Exception as e:
            logger.warning(f"[Reextract] proposal detection skipped: {e}")
        await _save_status(kb_id, {"status": "done", "finished_at": datetime.utcnow().isoformat()})
        try:
            from app.core.websocket_manager import manager
            await manager.broadcast(kb_id, {"type": "schema_reextract_done", "kb_id": kb_id})
        except Exception:
            pass

    asyncio.create_task(run_all())
    return {"queued": [str(d.id) for d in docs], "model": llm.get("model")}


async def status(kb_id: str) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    return ((kb.promotion_metadata or {}).get("reextract") or {}) if kb else {}


async def revert(kb_id: str, doc_ids: Optional[List[str]]) -> Dict[str, Any]:
    from app.models.knowledge_base import KnowledgeBase
    from app.services.ingestion.ingest_client import ingest_client
    from app.services.schema_alignment.service import rules_for_ingest
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    kb = await KnowledgeBase.get(kb_id)
    st = (kb.promotion_metadata or {}).get("reextract") or {}
    ids = doc_ids or [k for k, v in (st.get("docs") or {}).items() if v.get("state") == "done"]
    rules = await rules_for_ingest(kb_id, include_graph_rules=True)
    out = []
    for did in ids:
        try:
            r = await ingest_client.reextract_revert(kb_id, did, "fuseki" if kb.graph_backend == "ontology" else "neo4j",
                                                      rules or None)
            out.append({"doc_id": did, "output": r.get("output")})
            from app.models.document import Document
            doc = await Document.get(did)
            if doc and r.get("output") is not None:
                doc.triple_count = r["output"]   # 되돌린 그래프 기준으로 표시 갱신
                await doc.save()
            await _save_status(kb_id, {}, {did: {"state": "reverted"}})
        except Exception as e:
            out.append({"doc_id": did, "error": str(e)[:200]})
    FusekiBackend.invalidate_class_catalog(kb_id)
    return {"reverted": out}
