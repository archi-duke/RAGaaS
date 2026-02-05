from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import logging
import os
import json

from app.models.document import Document as DocModel, DocumentStatus
from app.models.knowledge_base import KnowledgeBase as KBModel
from app.schemas import Document
from app.core.config import settings
from app.core.websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

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

    # Build Pipeline Configs
    chunking_cfg = {
        "strategy": final_config.get("chunking_strategy") or final_config.get("strategy") or kb.chunking_strategy or "fixed_size",
        "chunk_size": final_config.get("chunk_size") or 300,
        "chunk_overlap": final_config.get("chunk_overlap") or 20,
        "window_size": final_config.get("window_size") or 3,
        "chunk_sizes": final_config.get("chunk_sizes") or [2048, 512, 128],
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

@router.get("/{kb_id}/documents", response_model=List[Document])
async def list_documents(kb_id: str):
    return await DocModel.find(DocModel.kb_id == kb_id).to_list()

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
    else:
        # Intermediate status (processing)
        doc.status = DocumentStatus.PROCESSING.value
        if payload.pipeline_status:
            doc.pipeline_status = payload.pipeline_status

    await doc.save()

    # Broadcast update to WebSocket
    await manager.broadcast(payload.kb_id, {
        "type": "document_status_update",
        "doc_id": payload.doc_id,
        "status": doc.status,
        "pipeline_status": doc.pipeline_status,
        "chunk_count": doc.chunk_count,
        "entity_count": doc.entity_count,
        "triple_count": doc.triple_count
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
    from pymilvus import Collection, utility
    
    # Verify document exists
    doc = await DocModel.find_one(DocModel.id == doc_id, DocModel.kb_id == kb_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    try:
        # Query Milvus for chunks belonging to this document
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        
        # Check if collection exists
        if not utility.has_collection(collection_name):
            logger.warning(f"Collection {collection_name} does not exist")
            return {"chunks": []}
        
        # Get collection and load it
        collection = Collection(collection_name)
        collection.load()
        
        # Query for chunks with this doc_id
        results = collection.query(
            expr=f'doc_id == "{doc_id}"',
            output_fields=["chunk_id", "content", "metadata", "doc_id"],
            limit=10000  # Large limit to get all chunks
        )
        
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
