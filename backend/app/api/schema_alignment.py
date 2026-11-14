"""KB 스키마 매핑 제안·규칙 API (docs/design-schema-mismatch.md §5)."""
import os
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter()


class AcceptBody(BaseModel):
    swap: bool = False
    target: Optional[str] = None
    renormalize: bool = True


class RuleBody(BaseModel):
    rule_type: str
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    source_value: Optional[str] = None
    target_value: Optional[str] = None
    scope_paths: Optional[List[str]] = None
    pair: Optional[List[str]] = None


class RulePatch(BaseModel):
    status: Optional[str] = None
    target_path: Optional[str] = None
    target_value: Optional[str] = None
    scope_paths: Optional[List[str]] = None


class RenormalizeBody(BaseModel):
    doc_ids: Optional[List[str]] = None


def _dump(obj) -> dict:
    d = obj.model_dump() if hasattr(obj, "model_dump") else obj.dict()
    d["id"] = str(obj.id)
    return d


async def _bump_and_invalidate(kb_id: str) -> None:
    from app.models.knowledge_base import KnowledgeBase
    from app.services.retrieval.graph_backends.fuseki import FusekiBackend
    kb = await KnowledgeBase.get(kb_id)
    if kb:
        kb.schema_rules_version += 1
        await kb.save()
    FusekiBackend.invalidate_class_catalog(kb_id)


@router.get("/{kb_id}/schema/proposals")
async def list_proposals(kb_id: str, status: Optional[str] = "pending"):
    from app.models.schema_mapping import SchemaMappingProposal
    q = SchemaMappingProposal.find(SchemaMappingProposal.kb_id == kb_id)
    if status:
        q = SchemaMappingProposal.find(SchemaMappingProposal.kb_id == kb_id, SchemaMappingProposal.status == status)
    return [_dump(p) for p in await q.to_list()]


@router.post("/{kb_id}/schema/proposals/{proposal_id}/accept")
async def accept(kb_id: str, proposal_id: str, body: AcceptBody = AcceptBody()):
    from app.services.schema_alignment.service import accept_proposal
    try:
        return await accept_proposal(kb_id, proposal_id, body.swap, body.target, body.renormalize)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{kb_id}/schema/proposals/{proposal_id}/reject")
async def reject(kb_id: str, proposal_id: str):
    from app.services.schema_alignment.service import reject_proposal
    try:
        return await reject_proposal(kb_id, proposal_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{kb_id}/schema/rules")
async def list_rules(kb_id: str):
    from app.models.schema_mapping import SchemaMappingRule
    return [_dump(r) for r in await SchemaMappingRule.find(SchemaMappingRule.kb_id == kb_id).to_list()]


@router.post("/{kb_id}/schema/rules")
async def create_rule(kb_id: str, body: RuleBody):
    from app.models.schema_mapping import SchemaMappingRule
    if body.rule_type not in ("key", "value", "ignore", "entity", "class"):
        raise HTTPException(status_code=400, detail="rule_type 은 key|value|ignore|entity|class")
    if body.rule_type in ("entity", "class") and not (body.source_value and body.target_value):
        raise HTTPException(status_code=400, detail="entity/class 규칙은 source_value/target_value 필요")
    if body.rule_type == "key" and not (body.source_path and body.target_path):
        raise HTTPException(status_code=400, detail="key 규칙은 source_path/target_path 필요")
    if body.rule_type == "value" and not (body.source_value and body.target_value):
        raise HTTPException(status_code=400, detail="value 규칙은 source_value/target_value 필요")
    if body.rule_type == "ignore" and not (body.pair and len(body.pair) == 2):
        raise HTTPException(status_code=400, detail="ignore 규칙은 pair 2개 필요")
    rule = SchemaMappingRule(kb_id=kb_id, origin="user", **{k: v for k, v in body.model_dump().items()
                                                            if v is not None})
    await rule.insert()
    await _bump_and_invalidate(kb_id)
    return _dump(rule)


@router.patch("/{kb_id}/schema/rules/{rule_id}")
async def patch_rule(kb_id: str, rule_id: str, body: RulePatch):
    from app.models.schema_mapping import SchemaMappingRule
    rule = await SchemaMappingRule.get(rule_id)
    if not rule or rule.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="rule not found")
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(rule, k, v)
    await rule.save()
    await _bump_and_invalidate(kb_id)
    return _dump(rule)


@router.delete("/{kb_id}/schema/rules/{rule_id}")
async def delete_rule(kb_id: str, rule_id: str):
    from app.models.schema_mapping import SchemaMappingRule
    rule = await SchemaMappingRule.get(rule_id)
    if not rule or rule.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="rule not found")
    await rule.delete()
    await _bump_and_invalidate(kb_id)
    return {"ok": True}


@router.post("/{kb_id}/schema/detect")
async def detect(kb_id: str):
    from app.services.schema_alignment.service import detect_proposals
    return await detect_proposals(kb_id)


@router.post("/{kb_id}/schema/renormalize")
async def renormalize(kb_id: str, body: RenormalizeBody = RenormalizeBody()):
    from app.services.schema_alignment.service import renormalize_documents
    try:
        return await renormalize_documents(kb_id, body.doc_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{kb_id}/schema/replay")
async def replay(kb_id: str, body: RenormalizeBody = RenormalizeBody()):
    """텍스트 문서 트리플 리플레이 (doc_ids 없으면 KB 의 모든 텍스트 문서)."""
    from app.models.document import Document
    from app.services.schema_alignment.service import _is_structured_name, replay_documents
    ids = body.doc_ids or [str(d.id) for d in await Document.find(Document.kb_id == kb_id).to_list()
                           if not _is_structured_name(d.filename)]
    return await replay_documents(kb_id, ids)


@router.post("/{kb_id}/documents/{doc_id}/reingest")
async def reingest(kb_id: str, doc_id: str, file: UploadFile = File(...)):
    """원본이 없는 기존 구조화 문서에 원본을 다시 올려 재정규화(재인제스트)."""
    from app.core.config import settings
    from app.models.document import Document
    from app.services.schema_alignment.service import renormalize_documents
    doc = await Document.get(doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="document not found")
    kb_path = os.path.join(settings.SHARED_STORAGE_PATH, kb_id)
    os.makedirs(kb_path, exist_ok=True)
    path = os.path.join(kb_path, f"{doc.id}_{doc.filename}")
    with open(path, "wb") as f:
        f.write(await file.read())
    doc.file_path = path
    doc.source_retained = True
    await doc.save()
    return await renormalize_documents(kb_id, [doc_id])
