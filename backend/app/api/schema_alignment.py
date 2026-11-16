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


class ReextractBody(BaseModel):
    doc_ids: Optional[List[str]] = None
    model: str = "ingest"      # ingest(KB 추출 모델) | graph(그래프 검색 모델)


@router.get("/{kb_id}/schema/reextract/estimate")
async def reextract_estimate(kb_id: str):
    """스키마 기준 재추출(옵션) 실행 전 예상: 대상 문서·청크 수, 모델, 스키마 규모, 마지막 실행."""
    from app.services.schema_alignment import reextract as rx
    try:
        return await rx.estimate(kb_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{kb_id}/schema/reextract")
async def reextract_start(kb_id: str, body: ReextractBody = ReextractBody()):
    from app.services.schema_alignment import reextract as rx
    try:
        return await rx.start(kb_id, body.doc_ids, body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{kb_id}/schema/reextract/status")
async def reextract_status(kb_id: str):
    from app.services.schema_alignment import reextract as rx
    return await rx.status(kb_id)


@router.post("/{kb_id}/schema/reextract/revert")
async def reextract_revert(kb_id: str, body: RenormalizeBody = RenormalizeBody()):
    from app.services.schema_alignment import reextract as rx
    return await rx.revert(kb_id, body.doc_ids)


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


# ---------------------------------------------------------------------------
# 스키마 편집기 (사람 검수 1단계, docs/design-schema-editor.md)
# ---------------------------------------------------------------------------

class SchemaSpecBody(BaseModel):
    classes: List[dict] = []
    properties: List[dict] = []
    base_version: Optional[int] = None
    replay: bool = True
    note: str = ""


class SchemaRevertBody(BaseModel):
    version: int


def _edit_error(e):
    raise HTTPException(status_code=e.status, detail={"errors": e.errors})


@router.get("/{kb_id}/schema/spec")
async def get_schema_spec(kb_id: str):
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.get_spec(kb_id)
    except se.SchemaEditError as e:
        _edit_error(e)


@router.post("/{kb_id}/schema/spec/validate")
async def validate_schema_spec(kb_id: str, body: SchemaSpecBody):
    """저장 전 미리보기: 오류·경고·변경 요약."""
    from app.models.knowledge_base import KnowledgeBase
    from app.services.schema_alignment import schema_editor as se
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="KB 없음")
    spec = se._norm_spec(body.model_dump())
    errors, warnings = se.validate_spec(spec)
    ind = (kb.promotion_metadata or {}).get("induction") or {}
    diff = se.diff_spec({"classes": ind.get("classes") or [], "properties": ind.get("properties") or []}, spec)
    return {"errors": errors, "warnings": warnings, "diff": diff, "summary": se._summary_text(diff)}


@router.put("/{kb_id}/schema/spec")
async def save_schema_spec(kb_id: str, body: SchemaSpecBody):
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.save_spec(kb_id, {"classes": body.classes, "properties": body.properties},
                                  base_version=body.base_version, replay=body.replay, note=body.note)
    except se.SchemaEditError as e:
        _edit_error(e)


@router.post("/{kb_id}/schema/spec/revert")
async def revert_schema_spec(kb_id: str, body: SchemaRevertBody):
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.revert_to(kb_id, body.version)
    except se.SchemaEditError as e:
        _edit_error(e)
