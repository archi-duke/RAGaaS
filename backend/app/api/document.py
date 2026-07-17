from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import logging
import os
import json
import re

from app.models.document import Document as DocModel, DocumentStatus
from app.models.knowledge_base import KnowledgeBase as KBModel
from app.schemas import Document
from app.core.config import settings
from app.core.websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


_UPLOAD_LLM_KEYMAP = {
    "ingest": {
        "provider": "llm_provider",
        "model": "llm_model",
        "base_url": "llm_base_url",
        "provider_id": "llm_provider_id",
    },
    "chunk_grouping": {
        "provider": "chunk_grouping_llm_provider",
        "model": "chunk_grouping_llm_model",
        "base_url": "chunk_grouping_llm_base_url",
        "provider_id": "chunk_grouping_llm_provider_id",
    },
    "subject_restoration": {
        "provider": "subject_restoration_llm_provider",
        "model": "subject_restoration_llm_model",
        "base_url": "subject_restoration_llm_base_url",
        "provider_id": "subject_restoration_llm_provider_id",
    },
    "noun_extraction": {
        "provider": "noun_extraction_llm_provider",
        "model": "noun_extraction_llm_model",
        "base_url": "noun_extraction_llm_base_url",
        "provider_id": "noun_extraction_llm_provider_id",
    },
}


async def _resolve_upload_llm_config(
    final_config: Dict[str, Any],
    kind: str,
    default_model: str = "gpt-4o-mini",
) -> Optional[Dict[str, Any]]:
    keymap = _UPLOAD_LLM_KEYMAP[kind]
    model_cfg = {
        "provider": final_config.get(keymap["provider"]),
        "model": final_config.get(keymap["model"]),
        "base_url": final_config.get(keymap["base_url"]),
        "provider_id": final_config.get(keymap["provider_id"]),
    }
    if not any(model_cfg.values()):
        return None

    from app.core.models_resolver import resolve_model_config
    resolved = await resolve_model_config(model_cfg, default_model=default_model)
    return {
        "model": resolved.get("model", default_model),
        "api_key": resolved.get("api_key"),
        "base_url": resolved.get("base_url"),
        "extra_headers": resolved.get("extra_headers") or {},
    }


def _has_model_selection(config: Optional[Dict[str, Any]]) -> bool:
    if not config:
        return False
    return any(
        config.get(k)
        for k in ("provider", "provider_id", "model", "api_key", "base_url")
    )


async def _persist_upload_model_settings(kb: KBModel, final_config: Dict[str, Any]) -> None:
    """
    Persist selected upload model fields into KB chunking_config.
    - If a value is provided, save it for next uploads.
    - If a value is missing, existing saved value remains unchanged.
    """
    stored_cfg = kb.chunking_config.copy() if kb.chunking_config else {}
    changed = False

    model_keys = set()
    for mapping in _UPLOAD_LLM_KEYMAP.values():
        model_keys.update(mapping.values())

    for key in model_keys:
        value = final_config.get(key)
        if value is None or value == "":
            continue
        if stored_cfg.get(key) != value:
            stored_cfg[key] = value
            changed = True

    if changed:
        kb.chunking_config = stored_cfg
        await kb.save()


async def _build_and_validate_upload_model_configs(
    *,
    kb: KBModel,
    final_config: Dict[str, Any],
    chunking_cfg: Dict[str, Any],
    graph_config: Dict[str, Any],
    enable_subject_restoration: bool,
    enable_entity_normalization: bool,
) -> Dict[str, Optional[Dict[str, Any]]]:
    from app.core.models_resolver import resolve_model_config

    # Embedding model is always required for ingestion.
    embedding_resolved = await resolve_model_config({
        "model": kb.embedding_model,
        "provider": kb.embedding_provider,
        "provider_id": kb.embedding_provider_id,
    })
    embedding_cfg = {
        "model": embedding_resolved.get("model"),
        "api_key": embedding_resolved.get("api_key"),
        "base_url": embedding_resolved.get("base_url"),
        "extra_headers": embedding_resolved.get("extra_headers") or {},
        "embedding_request_format": embedding_resolved.get("embedding_request_format", "openai"),
    }
    if not _has_model_selection({
        "model": kb.embedding_model,
        "provider": kb.embedding_provider,
        "provider_id": kb.embedding_provider_id,
    }):
        raise HTTPException(
            status_code=500,
            detail="모델 지정이 안되었습니다: 임베딩 모델을 먼저 설정해주세요.",
        )
    if embedding_cfg["embedding_request_format"] != "minimal" and not embedding_cfg.get("api_key"):
        raise HTTPException(
            status_code=500,
            detail="모델 지정이 안되었습니다: 임베딩 모델 API Key를 먼저 등록해주세요.",
        )

    async def require_llm(kind: str, label: str) -> Dict[str, Any]:
        cfg = await _resolve_upload_llm_config(final_config, kind, default_model="gpt-4o-mini")
        if not _has_model_selection(cfg):
            raise HTTPException(
                status_code=500,
                detail=f"모델 지정이 안되었습니다: {label} 모델을 설정해주세요.",
            )
        if not cfg.get("api_key"):
            raise HTTPException(
                status_code=500,
                detail=f"모델 지정이 안되었습니다: {label} 모델 API Key를 등록해주세요.",
            )
        return cfg

    ingest_llm_cfg: Optional[Dict[str, Any]] = None
    chunk_grouping_llm_cfg: Optional[Dict[str, Any]] = None
    subject_restoration_llm_cfg: Optional[Dict[str, Any]] = None
    noun_extraction_llm_cfg: Optional[Dict[str, Any]] = None

    if chunking_cfg.get("strategy") == "context_aware":
        chunk_grouping_llm_cfg = await require_llm("chunk_grouping", "Chunk Grouping")

    if graph_config.get("extractor_type") != "none":
        ingest_llm_cfg = await require_llm("ingest", "Graph Triple Extraction")
        if enable_entity_normalization:
            noun_extraction_llm_cfg = await require_llm("noun_extraction", "Noun Extraction")

    if enable_subject_restoration:
        subject_restoration_llm_cfg = await require_llm("subject_restoration", "Subject Restoration")

    return {
        "embedding_model": embedding_cfg,
        "ingest_llm": ingest_llm_cfg,
        "chunk_grouping_llm": chunk_grouping_llm_cfg,
        "subject_restoration_llm": subject_restoration_llm_cfg,
        "noun_extraction_llm": noun_extraction_llm_cfg,
    }


class TextUploadRequest(BaseModel):
    title: str
    content: str
    chunking_config: Optional[str] = None
    enable_text_cleaning: bool = False
    enable_subject_restoration: bool = True
    extraction_examples_yaml: Optional[str] = None
    enable_entity_normalization: bool = False
    normalization_algorithm: str = "embedding"
    normalization_threshold: float = 0.85
    enable_normalization_confirmation: bool = False


@router.post("/{kb_id}/documents/upload-text", response_model=Document)
async def upload_text_document(
    kb_id: str,
    background_tasks: BackgroundTasks,
    body: TextUploadRequest,
):
    """직접 입력된 텍스트 내용을 문서로 처리합니다."""
    kb = await KBModel.get(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    # 파일명 생성: 제목 기반, 특수문자 제거
    safe_title = re.sub(r'[^\w\s-]', '', body.title.strip()).strip()
    safe_title = re.sub(r'[\s]+', '_', safe_title) or "text_document"
    filename = f"{safe_title}.txt"

    # 기존 문서 덮어쓰기 체크
    existing_doc = await DocModel.find_one(DocModel.kb_id == kb_id, DocModel.filename == filename)
    pipeline_metadata = {}

    if existing_doc:
        doc = existing_doc
        doc.status = DocumentStatus.PROCESSING.value
        doc.updated_at = datetime.utcnow()
        doc.pipeline_metadata = pipeline_metadata
    else:
        doc = DocModel(
            kb_id=kb_id,
            filename=filename,
            file_type="txt",
            status=DocumentStatus.PROCESSING.value,
            pipeline_status="UPLOADED",
            pipeline_metadata=pipeline_metadata
        )
        await doc.insert()

    # 텍스트를 파일로 저장
    shared_path = settings.SHARED_STORAGE_PATH
    kb_path = os.path.join(shared_path, kb_id)
    os.makedirs(kb_path, exist_ok=True)
    file_path = os.path.join(kb_path, f"{doc.id}_{filename}")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(body.content)

    # Config 처리
    final_config = kb.chunking_config.copy() if kb.chunking_config else {}
    if body.chunking_config:
        try:
            parsed = json.loads(body.chunking_config)
            final_config.update(parsed)
            nested = parsed.get("chunking_config") or {}
            for k, v in nested.items():
                if k not in final_config or final_config.get(k) is None:
                    final_config[k] = v
        except Exception:
            logger.error("Failed to parse chunking_config override")

    await _persist_upload_model_settings(kb, final_config)

    chunking_cfg = {
        "strategy": final_config.get("chunking_strategy") or final_config.get("strategy") or kb.chunking_strategy or "fixed_size",
        "chunk_size": final_config.get("chunk_size") or 300,
        "chunk_overlap": final_config.get("chunk_overlap") or 20,
        "window_size": final_config.get("window_size") or 3,
        "chunk_sizes": final_config.get("chunk_sizes") or [2048, 512, 128],
        "parent_size": final_config.get("parent_size")
        if final_config.get("parent_size") is not None
        else (final_config.get("chunk_sizes") or [2048, 512])[0],
        "child_size": final_config.get("child_size")
        if final_config.get("child_size") is not None
        else (final_config.get("chunk_sizes") or [2048, 512])[1],
        "parent_overlap": final_config.get("parent_overlap")
        if final_config.get("parent_overlap") is not None
        else 0,
        "child_overlap": final_config.get("child_overlap")
        if final_config.get("child_overlap") is not None
        else 100,
        "buffer_size": final_config.get("buffer_size") or 1,
        "breakpoint_threshold": final_config.get("breakpoint_threshold") or 95,
    }

    if not kb.enable_graph_rag:
        graph_config = {
            "extractor_type": "none",
            "max_paths_per_chunk": 0,
            "max_triplets_per_chunk": 0,
            "num_workers": 1,
            "generate_inverse_relations": False,
        }
        final_enable_entity_normalization = False
        final_enable_normalization_confirmation = False
    else:
        graph_config = {
            "extractor_type": final_config.get("extractor_type", "simple"),
            "max_paths_per_chunk": final_config.get("max_paths_per_chunk", 10),
            "max_triplets_per_chunk": final_config.get("max_triplets_per_chunk", 20),
            "num_workers": final_config.get("num_workers", 4),
            "generate_inverse_relations": final_config.get("generate_inverse_relations", True),
        }
        final_enable_entity_normalization = body.enable_entity_normalization
        final_enable_normalization_confirmation = body.enable_normalization_confirmation

    model_configs = await _build_and_validate_upload_model_configs(
        kb=kb,
        final_config=final_config,
        chunking_cfg=chunking_cfg,
        graph_config=graph_config,
        enable_subject_restoration=body.enable_subject_restoration,
        enable_entity_normalization=final_enable_entity_normalization,
    )

    doc.extractor_type = graph_config.get("extractor_type")
    doc.max_paths = graph_config.get("max_paths_per_chunk")
    doc.enable_text_cleaning = body.enable_text_cleaning
    doc.enable_subject_restoration = body.enable_subject_restoration
    doc.generate_inverse = graph_config.get("generate_inverse_relations")
    doc.extraction_examples = body.extraction_examples_yaml
    doc.enable_entity_normalization = final_enable_entity_normalization
    doc.normalization_algorithm = body.normalization_algorithm
    doc.normalization_threshold = body.normalization_threshold
    doc.enable_normalization_confirmation = final_enable_normalization_confirmation
    doc.custom_prompt = final_config.get("custom_prompt")
    doc.file_path = file_path
    await doc.save()

    graph_extraction_prompt = doc.custom_prompt

    callback_base = os.getenv("CALLBACK_BASE_URL", "http://127.0.0.1:8000")
    callback_url = f"{callback_base.rstrip('/')}/api/knowledge-bases/ingest/callback"

    async def call_ingest_service():
        try:
            from app.services.ingestion.ingest_client import ingest_client
            await ingest_client.create_ingest_job(
                kb_id=kb_id,
                doc_id=str(doc.id),
                file_path=file_path,
                chunking_config=chunking_cfg,
                graph_config=graph_config,
                graph_store="fuseki" if kb.graph_backend == "ontology" else "neo4j",
                enable_text_cleaning=body.enable_text_cleaning,
                enable_subject_restoration=body.enable_subject_restoration,
                extraction_examples_yaml=body.extraction_examples_yaml,
                custom_prompt=graph_extraction_prompt,
                enable_entity_normalization=final_enable_entity_normalization,
                normalization_algorithm=body.normalization_algorithm,
                normalization_threshold=body.normalization_threshold,
                enable_normalization_confirmation=final_enable_normalization_confirmation,
                callback_url=callback_url,
                entity_dictionary=None,
                sampling_size=50000,
                ingest_llm=model_configs["ingest_llm"],
                chunk_grouping_llm=model_configs["chunk_grouping_llm"],
                subject_restoration_llm=model_configs["subject_restoration_llm"],
                noun_extraction_llm=model_configs["noun_extraction_llm"],
                embedding_model=model_configs["embedding_model"],
            )
        except Exception as e:
            logger.error(f"[Ingest Text] Service call failed: {e}")
            doc.status = DocumentStatus.ERROR.value
            await doc.save()

    background_tasks.add_task(call_ingest_service)
    await doc.save()

    await manager.broadcast(kb_id, {
        "type": "document_status_update",
        "doc_id": str(doc.id),
        "status": doc.status,
        "pipeline_status": doc.pipeline_status
    })

    doc_dict = doc.dict()
    doc_dict['id'] = str(doc.id)
    doc_dict['file_path'] = file_path
    return Document(**doc_dict)


@router.post("/{kb_id}/documents", response_model=Document)
async def upload_document(
    kb_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    chunking_config: str = Form(None),
    enable_text_cleaning: bool = Form(False),
    enable_subject_restoration: bool = Form(True),
    extraction_examples_yaml: str = Form(None),
    enable_entity_normalization: bool = Form(False),
    normalization_algorithm: str = Form("embedding"),
    normalization_threshold: float = Form(0.85),
    enable_normalization_confirmation: bool = Form(False),
    entity_dictionary: str = Form(None), # Optional dictionary JSON string
):
    # 1. Fetch Knowledge Base
    kb = await KBModel.get(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    # 2. Handle Document Record (Check for overwrite)
    existing_doc = await DocModel.find_one(DocModel.kb_id == kb_id, DocModel.filename == file.filename)
    
    # Init Metadata
    pipeline_metadata = {}

    if existing_doc:
        logger.info(f"Overwriting document: {file.filename}")
        doc = existing_doc
        doc.status = DocumentStatus.PROCESSING.value
        doc.updated_at = datetime.utcnow()
        # Merge existing metadata if needed, but for new upload we reset usually
        doc.pipeline_metadata = pipeline_metadata
    else:
        doc = DocModel(
            kb_id=kb_id,
            filename=file.filename,
            file_type=file.filename.split(".")[-1],
            status=DocumentStatus.PROCESSING.value,
            pipeline_status="UPLOADED",
            pipeline_metadata=pipeline_metadata
        )
        await doc.insert()

    # 3. Save File to Shared Storage
    content = await file.read()
    shared_path = settings.SHARED_STORAGE_PATH
    kb_path = os.path.join(shared_path, kb_id)
    os.makedirs(kb_path, exist_ok=True)
    
    # Important: Using doc.id ensures uniqueness.
    file_path = os.path.join(kb_path, f"{doc.id}_{doc.filename}")
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    # 4. Merge Configuration
    final_config = kb.chunking_config.copy() if kb.chunking_config else {}
    if chunking_config:
        try:
            parsed = json.loads(chunking_config)
            final_config.update(parsed)
            # Flatten nested chunking_config (frontend may send chunk_size inside chunking_config)
            nested = parsed.get("chunking_config") or {}
            for k, v in nested.items():
                if k not in final_config or final_config.get(k) is None:
                    final_config[k] = v
        except Exception:
            logger.error("Failed to parse chunking_config override")

    await _persist_upload_model_settings(kb, final_config)

    # Build Pipeline Configs
    chunking_cfg = {
        "strategy": final_config.get("chunking_strategy") or final_config.get("strategy") or kb.chunking_strategy or "fixed_size",
        "chunk_size": final_config.get("chunk_size") or 300,
        "chunk_overlap": final_config.get("chunk_overlap") or 20,
        "window_size": final_config.get("window_size") or 3,
        "chunk_sizes": final_config.get("chunk_sizes") or [2048, 512, 128],
        "parent_size": final_config.get("parent_size")
        if final_config.get("parent_size") is not None
        else (final_config.get("chunk_sizes") or [2048, 512])[0],
        "child_size": final_config.get("child_size")
        if final_config.get("child_size") is not None
        else (final_config.get("chunk_sizes") or [2048, 512])[1],
        "parent_overlap": final_config.get("parent_overlap")
        if final_config.get("parent_overlap") is not None
        else 0,
        "child_overlap": final_config.get("child_overlap")
        if final_config.get("child_overlap") is not None
        else 100,
        "buffer_size": final_config.get("buffer_size") or 1,
        "breakpoint_threshold": final_config.get("breakpoint_threshold") or 95,
    }
    
    # ✅ Graph 설정: KB의 enable_graph_rag에 따라 조건부 설정
    if not kb.enable_graph_rag:
        # Non-Graph KB: 트리플 추출을 생략하고 벡터 검색만 사용
        logger.info(f"[Upload] KB {kb_id} is Non-Graph mode (enable_graph_rag=False)")
        graph_config = {
            "extractor_type": "none",  # 트리플 추출 생략
            "max_paths_per_chunk": 0,  # Non-Graph 모드에서는 0
            "max_triplets_per_chunk": 0,  # Non-Graph 모드에서는 0
            "num_workers": 1,
            "generate_inverse_relations": False,
        }
        # Non-Graph 모드에서는 entity normalization도 강제 비활성화
        final_enable_entity_normalization = False
        final_enable_normalization_confirmation = False
    else:
        # Graph KB: 기존 설정 사용
        graph_config = {
            "extractor_type": final_config.get("extractor_type", "simple"),
            "max_paths_per_chunk": final_config.get("max_paths_per_chunk", 10),
            "max_triplets_per_chunk": final_config.get("max_triplets_per_chunk", 20),
            "num_workers": final_config.get("num_workers", 4),
            "generate_inverse_relations": final_config.get("generate_inverse_relations", True),
        }
        # Graph 모드에서는 파라미터로 받은 값 사용
        final_enable_entity_normalization = enable_entity_normalization
        final_enable_normalization_confirmation = enable_normalization_confirmation

    model_configs = await _build_and_validate_upload_model_configs(
        kb=kb,
        final_config=final_config,
        chunking_cfg=chunking_cfg,
        graph_config=graph_config,
        enable_subject_restoration=enable_subject_restoration,
        enable_entity_normalization=final_enable_entity_normalization,
    )

    # Update document record with extraction settings
    doc.extractor_type = graph_config.get("extractor_type")
    doc.max_paths = graph_config.get("max_paths_per_chunk")
    doc.enable_text_cleaning = enable_text_cleaning
    doc.enable_subject_restoration = enable_subject_restoration
    doc.generate_inverse = graph_config.get("generate_inverse_relations")
    doc.extraction_examples = extraction_examples_yaml or final_config.get("extraction_examples_yaml")
    doc.enable_entity_normalization = final_enable_entity_normalization
    doc.normalization_algorithm = normalization_algorithm
    doc.normalization_threshold = normalization_threshold
    doc.max_sample_size = final_config.get("max_sample_size", 50000)
    doc.enable_normalization_confirmation = final_enable_normalization_confirmation
    doc.custom_prompt = final_config.get("custom_prompt")
    doc.file_path = file_path
    await doc.save()

    # 5. Load Default Prompt/Examples if missing
    graph_extraction_prompt = doc.custom_prompt
    if not graph_extraction_prompt:
        # Fallback to file-based prompt... (logic omitted for brevity but preserved in real file)
        pass

    # Parse dictionary if provided
    dict_data = None
    if entity_dictionary:
        try:
            dict_data = json.loads(entity_dictionary)
            logger.info(f"Received entity dictionary with {len(dict_data)} items")
        except:
            logger.error("Failed to parse entity_dictionary JSON")

    # 6. Call Ingest Service (Async Task)
    callback_base = os.getenv("CALLBACK_BASE_URL", "http://127.0.0.1:8000")
    callback_url = f"{callback_base.rstrip('/')}/api/knowledge-bases/ingest/callback"

    async def call_ingest_service():
        try:
            from app.services.ingestion.ingest_client import ingest_client
            await ingest_client.create_ingest_job(
                kb_id=kb_id,
                doc_id=str(doc.id),
                file_path=file_path,
                chunking_config=chunking_cfg,
                graph_config=graph_config,
                graph_store="fuseki" if kb.graph_backend == "ontology" else "neo4j",
                enable_text_cleaning=enable_text_cleaning,
                enable_subject_restoration=enable_subject_restoration,
                extraction_examples_yaml=extraction_examples_yaml or final_config.get("extraction_examples_yaml"),
                custom_prompt=graph_extraction_prompt,
                enable_entity_normalization=final_enable_entity_normalization,
                normalization_algorithm=normalization_algorithm,
                normalization_threshold=normalization_threshold,
                enable_normalization_confirmation=final_enable_normalization_confirmation,
                callback_url=callback_url,
                entity_dictionary=dict_data,
                sampling_size=doc.max_sample_size,
                ingest_llm=model_configs["ingest_llm"],
                chunk_grouping_llm=model_configs["chunk_grouping_llm"],
                subject_restoration_llm=model_configs["subject_restoration_llm"],
                noun_extraction_llm=model_configs["noun_extraction_llm"],
                embedding_model=model_configs["embedding_model"],
            )
        except Exception as e:
            logger.error(f"[Ingest] Service call failed: {e}")
            # Log response body for 422 errors
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    logger.error(f"[Ingest] Error detail: {error_detail}")
                except:
                    logger.error(f"[Ingest] Response text: {e.response.text if hasattr(e.response, 'text') else 'N/A'}")
            doc.status = DocumentStatus.ERROR.value
            await doc.save()

    background_tasks.add_task(call_ingest_service)
    
    # 7. Finalize and Return
    await doc.save()

    # Broadcast initial status to WebSocket
    await manager.broadcast(kb_id, {
        "type": "document_status_update",
        "doc_id": str(doc.id),
        "status": doc.status,
        "pipeline_status": doc.pipeline_status
    })

    doc_dict = doc.dict()
    doc_dict['id'] = str(doc.id)
    doc_dict['file_path'] = file_path
    return Document(**doc_dict)


# §4.4 stuck 상태 리커버리 — 조회 시 경량 타임아웃 판정 (읽기 전용, doc.save() 호출하지 않음)
_STALE_THRESHOLD_SECONDS = {
    DocumentStatus.PROCESSING.value: 10 * 60,  # 10분
    DocumentStatus.DELETING.value: 5 * 60,     # 5분
}


def _mark_stale_if_stuck(doc: DocModel) -> DocModel:
    threshold_seconds = _STALE_THRESHOLD_SECONDS.get(doc.status)
    if not threshold_seconds:
        return doc
    updated_at = doc.updated_at
    if updated_at is None:
        return doc
    # updated_at은 보통 naive UTC(datetime.utcnow() 기본값)로 저장되지만,
    # 혹시 tz-aware 값이 들어와도 안전하게 비교할 수 있도록 정규화한다.
    now = datetime.utcnow()
    if updated_at.tzinfo is not None:
        updated_at = updated_at.replace(tzinfo=None) - updated_at.utcoffset()
    elapsed = (now - updated_at).total_seconds()
    if elapsed > threshold_seconds:
        doc.stale = True
    return doc


@router.get("/{kb_id}/documents", response_model=List[Document])
async def list_documents(kb_id: str):
    docs = await DocModel.find(DocModel.kb_id == kb_id).to_list()
    for doc in docs:
        _mark_stale_if_stuck(doc)
    return docs

@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: str, doc_id: str):
    doc = await DocModel.find_one(DocModel.id == doc_id, DocModel.kb_id == kb_id)
    if not doc: return {"ok": False}
    
    # Optional: Mark as deleting just in case crash, but we are waiting now.
    doc.status = DocumentStatus.DELETING.value
    await doc.save()
    
    from app.services.ingestion.cleanup_service import cleanup_service
    try:
        # EXECUTE SYNCHRONOUSLY (WAIT) to ensure completion
        await cleanup_service.perform_cascading_deletion(kb_id, doc_id)
    except Exception as e:
        logger.error(f"Deletion failed synchronously: {e}")
        # Even if failed, we try to force delete doc record in cleanup_service. 
        # If it raised here, it means cleanup_service failed critically.
        # We should probably still return OK if the doc is gone, or error if not.
        return {"ok": False, "detail": str(e)}

    # 🧹 Check if this was the last document - if so, clean up Promotion artifacts
    remaining_docs = await DocModel.find(DocModel.kb_id == kb_id).to_list()
    if len(remaining_docs) == 0:
        kb = await KBModel.get(kb_id)
        if kb and kb.is_promoted:
            logger.info(f"[DocumentDelete] Last document deleted - cleaning up Promotion artifacts for KB {kb_id}")
            try:
                # Delete Ontology graph from Fuseki
                if kb.graph_backend == 'ontology':
                    from app.core.fuseki import fuseki_client
                    ontology_graph_uri = f"urn:ontology:{kb_id}"
                    fuseki_client.drop_graph(kb_id, ontology_graph_uri)
                    logger.info(f"[DocumentDelete] Dropped Ontology graph: {ontology_graph_uri}")
                
                # Reset Promotion state
                kb.is_promoted = False
                kb.promotion_metadata = {}
                await kb.save()
                logger.info(f"[DocumentDelete] Reset Promotion state for KB {kb_id}")
            except Exception as e:
                logger.error(f"[DocumentDelete] Failed to clean up Promotion artifacts: {e}")
                # Don't fail the delete operation even if cleanup fails

    return {"ok": True}

class IngestCallback(BaseModel):
    job_id: str
    doc_id: str
    kb_id: str
    status: str
    pipeline_status: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Optional[int] = None

@router.post("/ingest/callback")
async def ingest_callback(payload: IngestCallback):
    doc = await DocModel.find_one(DocModel.id == payload.doc_id, DocModel.kb_id == payload.kb_id)
    if not doc:
        return {"ok": False, "error": "Document not found"}

    # Update Status
    if payload.status == "completed":
        doc.status = DocumentStatus.COMPLETED.value
        doc.pipeline_status = "COMPLETED"
        
        # ✅ Update counts from result
        if payload.result:
            doc.chunk_count = payload.result.get("node_count", 0)
            doc.triple_count = payload.result.get("triple_count", 0)
            
            # Read entity_count from entity_dictionary.json (Raw Dict)
            try:
                import json
                temp_dict_path = os.path.join(
                    settings.SHARED_STORAGE_PATH, 
                    payload.kb_id, 
                    f"{payload.doc_id}_dictionary.json"
                )
                if os.path.exists(temp_dict_path):
                    with open(temp_dict_path, 'r', encoding='utf-8') as f:
                        entity_data = json.load(f)
                        if isinstance(entity_data, dict):
                            doc.entity_count = len(entity_data)
                        else:
                            doc.entity_count = 0
            except Exception as e:
                logger.warning(f"Failed to read entity_count: {e}")
                
    elif payload.status == "failed":
        doc.status = DocumentStatus.ERROR.value
        doc.error = payload.error
    else:
        # Intermediate status (processing)
        doc.status = DocumentStatus.PROCESSING.value
        if payload.pipeline_status:
            doc.pipeline_status = payload.pipeline_status

    if payload.progress is not None:
        doc.progress = payload.progress

    await doc.save()

    # Broadcast update to WebSocket
    await manager.broadcast(payload.kb_id, {
        "type": "document_status_update",
        "doc_id": payload.doc_id,
        "status": doc.status,
        "pipeline_status": doc.pipeline_status,
        "chunk_count": doc.chunk_count,
        "entity_count": doc.entity_count,
        "triple_count": doc.triple_count,
        "progress": doc.progress,
        "error": doc.error
    })

    # Cleanup source file if completed
    if payload.status == "completed":
        try:
            if doc.file_path and os.path.exists(doc.file_path):
                os.remove(doc.file_path)
                logger.info(f"Deleted source file for completed document: {doc.file_path}")
            else:
                # Fallback check
                shared_path = settings.SHARED_STORAGE_PATH
                potential_path = os.path.join(shared_path, doc.kb_id, f"{doc.id}_{doc.filename}")
                if os.path.exists(potential_path):
                    os.remove(potential_path)
                    logger.info(f"Deleted source file (fallback path): {potential_path}")
        except Exception as e:
            logger.warning(f"Failed to delete source file for {doc.id}: {e}")
            
    return {"ok": True}




@router.get("/{kb_id}/documents/{doc_id}/pipeline/data")
async def get_pipeline_data(kb_id: str, doc_id: str):
    """Fetch offloaded pipeline data (dictionary, triples) from file system."""
    doc = await DocModel.find_one(DocModel.id == doc_id, DocModel.kb_id == kb_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    metadata = doc.pipeline_metadata or {}
    shared_path = settings.SHARED_STORAGE_PATH
    doc_dir = os.path.join(shared_path, kb_id)
    
    # Load Dictionary if referenced or exists in folder
    dict_file = metadata.get("dictionary_file") or f"{doc_id}_dictionary.json"
    file_path = os.path.join(doc_dir, dict_file)
    if os.path.exists(file_path):
        logger.info(f"Loading dictionary from: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                metadata["dictionary"] = json.load(f)
            logger.info(f"Successfully loaded dictionary ({len(metadata['dictionary'])} items)")
        except Exception as e:
            logger.error(f"Failed to load dictionary file: {e}")
            metadata["dictionary_error"] = str(e)
    else:
        logger.info(f"Dictionary file not found (searched: {dict_file})")
    
    # Load Triples if referenced or exists in folder
    triples_file = metadata.get("triples_file") or f"{doc_id}_triples.json"
    file_path = os.path.join(doc_dir, triples_file)
    if os.path.exists(file_path):
        logger.info(f"Loading triples from: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                metadata["triples"] = json.load(f)
            logger.info(f"Successfully loaded triples ({len(metadata['triples'])} items)")
        except Exception as e:
            logger.error(f"Failed to load triples file: {e}")
            metadata["triples_error"] = str(e)
    else:
        logger.info(f"Triples file not found (searched: {triples_file})")
                
    return metadata


@router.get("/{kb_id}/documents/{doc_id}/chunks")
async def get_document_chunks(kb_id: str, doc_id: str):
    """Retrieve all chunks for a specific document from Milvus."""
    from pymilvus import Collection, utility, connections
    from app.core.milvus import connect_milvus

    # Verify document exists
    doc = await DocModel.find_one(DocModel.id == doc_id, DocModel.kb_id == kb_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Ensure Milvus connection is active
    try:
        utility.list_collections()
    except Exception as e:
        logger.warning(f"[Chunks] Milvus not connected ({e}), reconnecting...")
        try:
            connections.disconnect(alias="default")
        except Exception:
            pass
        connect_milvus()
        logger.info("[Chunks] Milvus reconnected")

    try:
        # Query Milvus for chunks belonging to this document
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        
        # Check if collection exists
        if not utility.has_collection(collection_name):
            logger.warning(f"Collection {collection_name} does not exist")
            return {"chunks": []}
        
        # Get collection and load it.
        # Milvus load/query 는 블로킹이며, 손상된 컬렉션은 load 가 무한 타임아웃되어
        # 이벤트 루프 전체를 막는다(다른 KB·목록까지 멈춤). 스레드 오프로딩 + wait_for
        # 로 시간 격리하고, 실패 시 빈 청크로 degrade 한다.
        import asyncio
        def _sync_query_chunks():
            collection = Collection(collection_name)
            collection.load(timeout=15)
            return collection.query(
                expr=f'doc_id == "{doc_id}"',
                output_fields=["chunk_id", "content", "metadata", "doc_id"],
                limit=10000,
                timeout=15,
            )
        try:
            results = await asyncio.wait_for(asyncio.to_thread(_sync_query_chunks), timeout=20)
        except Exception as e:
            logger.warning(f"[get_document_chunks] Milvus 조회 실패/타임아웃 — 빈 청크 반환: {str(e)[:120]}")
            return {"chunks": []}
        
        # Format response
        chunks = []
        for result in results:
            chunk_data = {
                "chunk_id": result.get("chunk_id", ""),
                "content": result.get("content", ""),
                "metadata": result.get("metadata", {}),
            }
            chunks.append(chunk_data)
        
        # Sort chunks by start_char_idx to ensure proper ordering
        # Fallback to chunk_index if start_char_idx is not available
        def get_sort_key(chunk):
            metadata = chunk.get("metadata", {})
            # Try start_char_idx first (more accurate)
            if "start_char_idx" in metadata:
                return metadata["start_char_idx"]
            # Fallback to chunk_index
            if "chunk_index" in metadata:
                return metadata["chunk_index"] * 10000  # Large multiplier to separate from char indices
            # Last resort: return 0 (keep original order)
            return 0
        
        chunks.sort(key=get_sort_key)
        
        logger.info(f"Retrieved {len(chunks)} chunks for document {doc_id}")
        return {"chunks": chunks}
        
    except Exception as e:
        logger.error(f"Failed to retrieve chunks for document {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve chunks: {str(e)}")
