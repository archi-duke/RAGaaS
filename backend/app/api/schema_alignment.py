"""KB 스키마 매핑 제안·규칙 API (docs/design/schema/design-schema-mismatch.md §5)."""
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
# 스키마 편집기 (사람 검수 1단계, docs/design/schema/design-schema-editor.md)
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
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.preview(kb_id, body.model_dump())
    except se.SchemaEditError as e:
        _edit_error(e)


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



class MembersBody(BaseModel):
    class_name: str
    entities: List[str]


class MergeBody(BaseModel):
    canonical: str
    aliases: List[str]


@router.post("/{kb_id}/schema/spec/members")
async def assign_schema_members(kb_id: str, body: MembersBody):
    """멤버 누락 후보를 클래스 멤버로 지정 (class 규칙 + 리플레이)."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.assign_members(kb_id, body.class_name, body.entities)
    except se.SchemaEditError as e:
        _edit_error(e)


@router.get("/{kb_id}/schema/spec/merge-candidates")
async def schema_merge_candidates(kb_id: str, class_name: str):
    """한 클래스 범위의 같은 개념 다른 표기 후보 (LLM, 제안만)."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.merge_candidates(kb_id, class_name)
    except se.SchemaEditError as e:
        _edit_error(e)


class MergeBatchBody(BaseModel):
    merges: List[dict]          # [{canonical, aliases: [...]}]
    origin: Optional[str] = None


@router.post("/{kb_id}/schema/spec/merge/batch")
async def merge_schema_entities_batch(kb_id: str, body: MergeBatchBody):
    """여러 표기 병합을 규칙으로 넣고 리플레이 한 번."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.merge_entities_batch(kb_id, body.merges, body.origin or "schema_editor:merge")
    except se.SchemaEditError as e:
        _edit_error(e)


@router.post("/{kb_id}/schema/spec/merge")
async def merge_schema_entities(kb_id: str, body: MergeBody):
    """표기 병합 (entity 규칙 + 리플레이)."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.merge_entities(kb_id, body.canonical, body.aliases)
    except se.SchemaEditError as e:
        _edit_error(e)


class InduceDryRunBody(BaseModel):
    llm_model: Optional[dict] = None


@router.post("/{kb_id}/schema/induce/dry-run")
async def induce_dry_run(kb_id: str, body: InduceDryRunBody):
    """스키마 재유도 미리보기 — 저장·제안 없이 결과와 현재 스키마의 차이 (평가용 KB 보호)."""
    from app.models.knowledge_base import KnowledgeBase
    from app.services.schema_alignment.induction import run_induction
    from app.services.schema_alignment.service import _graph_llm_config
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="KB 없음")
    cfg = body.llm_model or await _graph_llm_config(kb)
    try:
        return await run_induction(kb_id, cfg, dry_run=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{kb_id}/schema/spec/triples")
async def schema_property_triples(kb_id: str, property: str, limit: int = 200):
    """속성 하나의 트리플 목록 + range 기준 상태 (편집기: 트리플 수 클릭)."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.property_triples(kb_id, property, limit)
    except se.SchemaEditError as e:
        _edit_error(e)


class TripleEditBody(BaseModel):
    action: str                       # move | delete | flip | add (add 는 triples 에 source·doc_id 필수, year 선택)
    triples: List[dict]               # [{subject, predicate, object}]
    target_property: Optional[str] = None
    new_property: Optional[dict] = None   # {name, domain, range, description} — 새 관계를 만들어 이동


class NewClassBody(BaseModel):
    name: str
    description: str = ""
    members: List[str] = []


@router.post("/{kb_id}/schema/spec/triples/edit")
async def edit_schema_triples(kb_id: str, body: TripleEditBody):
    """트리플 이동·삭제 (triple 규칙 + 리플레이) — 리플레이·재추출 뒤에도 유지된다."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.edit_triples(kb_id, body.action, body.triples, body.target_property, body.new_property)
    except se.SchemaEditError as e:
        _edit_error(e)


# ---------------------------------------------------------------------------
# 관계 방향 검증 (데이터 품질 D1) — 판정만 저장, 적용은 triples/edit(action=flip|delete) 로 사람이
# ---------------------------------------------------------------------------

_AUDIT_STATE: dict = {}


class DirectionAuditBody(BaseModel):
    properties: Optional[List[str]] = None


@router.post("/{kb_id}/schema/direction-audit")
async def start_direction_audit(kb_id: str, body: DirectionAuditBody):
    """같은 클래스끼리 잇는 관계의 트리플 방향을 원문으로 검증 (백그라운드, LLM). 결과는 GET 으로."""
    import asyncio as _aio
    from app.services.schema_alignment import direction_audit as da
    if _AUDIT_STATE.get(kb_id, {}).get("state") == "running":
        return _AUDIT_STATE[kb_id]

    async def _run():
        try:
            r = await da.run_audit(kb_id, body.properties)
            _AUDIT_STATE[kb_id] = {"state": "done", **r}
        except Exception as e:      # noqa: BLE001
            _AUDIT_STATE[kb_id] = {"state": "error", "error": str(e)[:300]}

    _AUDIT_STATE[kb_id] = {"state": "running"}
    _aio.create_task(_run())
    return _AUDIT_STATE[kb_id]


@router.get("/{kb_id}/schema/direction-audit")
async def get_direction_audit(kb_id: str):
    """마지막 방향 검증 결과 (판정·근거 문장 포함) + 실행 상태."""
    from app.services.schema_alignment import direction_audit as da
    out = await da.get_audit(kb_id)
    return {**out, "run": _AUDIT_STATE.get(kb_id, {"state": "idle"})}


@router.post("/{kb_id}/schema/spec/classes")
async def create_schema_class(kb_id: str, body: NewClassBody):
    """새 클래스 추가 + 멤버 지정."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.create_class_with_members(kb_id, body.name, body.description, body.members)
    except se.SchemaEditError as e:
        _edit_error(e)



class ReextractPreviewBody(BaseModel):
    classes: List[dict] = []
    properties: List[dict] = []
    triples: List[dict] = []          # [{subject, predicate, object, source, doc_id, doc}]


@router.post("/{kb_id}/schema/spec/reextract-preview")
async def schema_reextract_preview(kb_id: str, body: ReextractPreviewBody):
    """편집 중인(저장 전) 스키마로 선택 트리플의 근거 청크만 재추출해 사라지는지 비교 — 저장 없음, 청크당 LLM 1회."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.reextract_preview(kb_id, {"classes": body.classes, "properties": body.properties}, body.triples)
    except se.SchemaEditError as e:
        _edit_error(e)


# ---------------------------------------------------------------------------
# AI 추천 (docs/design/schema/design-schema-editor.md §14) — 추천 → 체크 → 효과 미리보기 → 승인 반영
# ---------------------------------------------------------------------------

class RecommendBody(BaseModel):
    triples: Optional[List[dict]] = None      # 트리플 창에서 호출하면 그 트리플만 대상으로
    gaps: Optional[dict] = None               # {클래스: [이름]} — 재추출 뒤 새 멤버 누락만 정리 ({} 면 누락 전체)


class RecommendActionsBody(BaseModel):
    actions: List[dict]
    problems: List[dict] = []
    base_version: Optional[int] = None
    rec_id: Optional[str] = None            # 추천 id — 수용 기록용
    outcome: Optional[dict] = None          # {proposed, rejected, preview}


@router.post("/{kb_id}/schema/recommend")
async def schema_recommend(kb_id: str, body: RecommendBody):
    from app.services.schema_alignment import recommend as rc
    from app.services.schema_alignment.schema_editor import SchemaEditError
    try:
        scope = {"triples": body.triples} if body.triples else ({"gaps": body.gaps} if body.gaps is not None else None)
        return await rc.recommend(kb_id, scope)
    except SchemaEditError as e:
        _edit_error(e)


@router.post("/{kb_id}/schema/recommend/preview")
async def schema_recommend_preview(kb_id: str, body: RecommendActionsBody):
    """체크한 처리안을 가상 적용해 문제 청크를 재추출 — 저장 없음."""
    from app.services.schema_alignment import recommend as rc
    from app.services.schema_alignment.schema_editor import SchemaEditError
    try:
        return await rc.preview(kb_id, body.actions, body.problems)
    except SchemaEditError as e:
        _edit_error(e)


@router.post("/{kb_id}/schema/recommend/apply")
async def schema_recommend_apply(kb_id: str, body: RecommendActionsBody):
    """승인한 처리안 반영: 스키마 저장 + 규칙 + 리플레이."""
    from app.services.schema_alignment import recommend as rc
    from app.services.schema_alignment.schema_editor import SchemaEditError
    try:
        return await rc.apply(kb_id, body.actions, body.base_version, body.rec_id, body.outcome)
    except SchemaEditError as e:
        _edit_error(e)



@router.get("/{kb_id}/schema/recommend/log")
async def schema_recommend_log(kb_id: str):
    """AI 추천 수용 기록 — 제안 수·종류, 승인·수정·거절 수, 미리보기 결과."""
    from app.models.knowledge_base import KnowledgeBase
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="KB 없음")
    return list(reversed((kb.promotion_metadata or {}).get("ai_recommend_log") or []))



class RecommendRejectBody(BaseModel):
    rec_id: Optional[str] = None
    rejected_actions: List[dict] = []
    proposed: Optional[int] = None


class ForgetBody(BaseModel):
    sig: Optional[str] = None
    decided_key: Optional[str] = None


@router.post("/{kb_id}/schema/recommend/reject")
async def schema_recommend_reject(kb_id: str, body: RecommendRejectBody):
    """반영 없이 거절만 기록 — 다음 추천에서 같은 안이 나오지 않게."""
    from app.services.schema_alignment import recommend as rc
    return await rc.reject(kb_id, body.rec_id, body.rejected_actions, body.proposed)


@router.get("/{kb_id}/schema/recommend/memory")
async def schema_recommend_memory(kb_id: str):
    """추천 기억: 거절한 안·확정한 결정."""
    from app.services.schema_alignment import recommend as rc
    return await rc.get_memory(kb_id)


@router.post("/{kb_id}/schema/recommend/memory/forget")
async def schema_recommend_forget(kb_id: str, body: ForgetBody):
    from app.services.schema_alignment import recommend as rc
    return await rc.forget(kb_id, body.sig, body.decided_key)


@router.get("/{kb_id}/schema/spec/mismatches")
async def schema_mismatches(kb_id: str, status: str = "violation", class_name: Optional[str] = None):
    """일치하지 않는 트리플 모음 — range 위반·멤버 누락 (모든 관계, 또는 range 클래스별)."""
    from app.services.schema_alignment import schema_editor as se
    try:
        return await se.mismatch_triples(kb_id, status, class_name)
    except se.SchemaEditError as e:
        _edit_error(e)
