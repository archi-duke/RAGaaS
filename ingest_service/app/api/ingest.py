"""
Ingest API Router
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid
from datetime import datetime

from app.core.pipeline import (
    ingest_pipeline,
    ChunkingStrategy,
    GraphExtractorType,
)
from app.core.milvus_connector import milvus_connector
from app.core.neo4j_connector import neo4j_connector
from app.core.fuseki_connector import fuseki_connector



router = APIRouter()


# In-memory job storage (In production, use Redis or a Database)
jobs: Dict[str, Dict[str, Any]] = {}

# Preview cache: stores extraction results before user confirms
preview_cache: Dict[str, Dict[str, Any]] = {}



class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _format_model_error_message(error_text: str) -> str:
    if "not configured" in error_text.lower():
        return f"모델 지정이 안되었습니다: {error_text}"
    return error_text


def _is_model_configured(config: Optional[Dict[str, Any]]) -> bool:
    if not config:
        return False
    return any(config.get(k) for k in ("provider", "provider_id", "model", "api_key", "base_url"))


class ChunkingConfig(BaseModel):
    """Chunking Configuration"""
    strategy: ChunkingStrategy = ChunkingStrategy.FIXED_SIZE
    chunk_size: int = Field(default=1024, ge=100, le=10000)
    chunk_overlap: int = Field(default=20, ge=0, le=1000)
    window_size: int = Field(default=3, ge=1, le=10)
    chunk_sizes: List[int] = Field(default=[2048, 512, 128])
    buffer_size: int = Field(default=1, ge=1, le=5)
    breakpoint_threshold: int = Field(default=95, ge=50, le=99)


class GraphConfig(BaseModel):
    """Graph Extraction Configuration"""
    extractor_type: GraphExtractorType = GraphExtractorType.NONE
    max_paths_per_chunk: int = Field(default=10, ge=0, le=50)  # ge=0으로 변경
    max_triplets_per_chunk: int = Field(default=20, ge=0, le=100)  # ge=0으로 변경
    num_workers: int = Field(default=4, ge=1, le=16)
    allowed_entity_types: Optional[List[str]] = None
    allowed_relation_types: Optional[List[str]] = None
    generate_inverse_relations: bool = True
    
    @field_validator('max_paths_per_chunk', 'max_triplets_per_chunk')
    @classmethod
    def validate_graph_limits(cls, v, info):
        """extractor_type이 NONE이 아닐 때는 최소값 1 이상 요구"""
        # info.data에서 extractor_type 확인
        extractor_type = info.data.get('extractor_type')
        if extractor_type and extractor_type != GraphExtractorType.NONE and v < 1:
            raise ValueError(f'must be at least 1 when extractor_type is not NONE')
        return v


class IngestRequest(BaseModel):
    """Ingestion Request"""
    kb_id: str
    doc_id: str
    file_path: str
    chunking: ChunkingConfig = ChunkingConfig()
    graph: GraphConfig = GraphConfig()
    graph_store: str = "neo4j"  # "neo4j" or "fuseki"
    enable_text_cleaning: bool = False  # Remove bullets, numbers, etc.
    enable_subject_restoration: bool = True  # Restore omitted subjects in Korean text
    enable_inference: bool = False  # Rule-based relationship inference
    extraction_examples_yaml: Optional[str] = None
    custom_prompt: Optional[str] = None
    enable_entity_normalization: bool = False  # Merge similar entities
    normalization_algorithm: str = "embedding"  # embedding | string | llm
    normalization_threshold: float = 0.85
    enable_normalization_confirmation: bool = False  # User review before applying
    callback_url: Optional[str] = None
    sampling_size: Optional[int] = None # For Doc2Graph Dictionary (Phase 1)
    entity_dictionary: Optional[Dict[str, Any]] = None # Pre-computed dictionary
    # Model configurations
    ingest_llm: Optional[Dict[str, Any]] = None
    chunk_grouping_llm: Optional[Dict[str, Any]] = None
    subject_restoration_llm: Optional[Dict[str, Any]] = None
    noun_extraction_llm: Optional[Dict[str, Any]] = None
    embedding_model: Optional[Dict[str, Any]] = None


class IngestResponse(BaseModel):
    """Ingestion Response"""
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    """Job Status Response"""
    job_id: str
    status: JobStatus
    kb_id: str
    doc_id: str
    created_at: str
    updated_at: str
    progress: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


async def send_pipeline_status(callback_url: str, job_id: str, doc_id: str, kb_id: str, status: str):
    """Helper to send granular pipeline status to backend"""
    if not callback_url: return
    import httpx
    try:
        # ✅ COMPLETED 상태일 때는 status를 'completed'로 전송
        overall_status = "completed" if status == "COMPLETED" else "processing"
        
        async with httpx.AsyncClient() as client:
            await client.post(callback_url, json={
                "job_id": job_id,
                "doc_id": doc_id,
                "kb_id": kb_id,
                "status": overall_status,
                "pipeline_status": status
            })
    except Exception as e:
        print(f"[Callback] Failed to send status {status}: {e}")


async def process_ingest_job(job_id: str, request: IngestRequest):
    """Process ingestion job in background"""
    try:
        print(f"[IngestJob] Starting job {job_id} for doc {request.doc_id}")
        jobs[job_id]["status"] = JobStatus.PROCESSING
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
        
        # 1. Read file (PDF or Text)
        from app.utils.file_utils import read_text_file
        text = await read_text_file(request.file_path)
        
        if not text:
            raise ValueError(f"Could not read content from {request.file_path}")
        
        print(f"[IngestJob] Read file: {len(text)} chars")

        # Validate required model settings before running pipeline steps.
        if not _is_model_configured(request.embedding_model):
            raise ValueError("Embedding model is not configured.")
        if request.chunking.strategy == ChunkingStrategy.CONTEXT_AWARE and not _is_model_configured(request.chunk_grouping_llm):
            raise ValueError("Chunk Grouping model is not configured for context-aware chunking.")
        if request.graph.extractor_type != GraphExtractorType.NONE and not _is_model_configured(request.ingest_llm):
            raise ValueError("Graph Triple Extraction model is not configured.")
        if request.enable_subject_restoration and not _is_model_configured(request.subject_restoration_llm):
            raise ValueError("Subject Restoration model is not configured.")
        if request.enable_entity_normalization and request.graph.extractor_type != GraphExtractorType.NONE and not _is_model_configured(request.noun_extraction_llm):
            raise ValueError("Noun Extraction model is not configured.")
        
        # 1.5 Subject Restoration (Optional)
        if request.enable_subject_restoration:
            from app.core.subject_restoration import restore_subjects
            text = await restore_subjects(text, llm_config=request.subject_restoration_llm)
            print(f"[IngestJob] Subject restoration applied: {len(text)} chars")
        
        jobs[job_id]["progress"] = 10

        
        # 2. Prepare configs
        chunking_config = {
            "chunk_size": request.chunking.chunk_size,
            "chunk_overlap": request.chunking.chunk_overlap,
            "window_size": request.chunking.window_size,
            "chunk_sizes": request.chunking.chunk_sizes,
            "buffer_size": request.chunking.buffer_size,
            "breakpoint_threshold": request.chunking.breakpoint_threshold,
        }
        
        graph_config = {
            "max_paths_per_chunk": request.graph.max_paths_per_chunk,
            "max_triplets_per_chunk": request.graph.max_triplets_per_chunk,
            "num_workers": request.graph.num_workers,
            "allowed_entity_types": request.graph.allowed_entity_types,
            "allowed_relation_types": request.graph.allowed_relation_types,
        }
        
        # 3. Process with IngestPipeline (Now handles dictionary + chunks + triples in order)
        async def pipeline_callback(status):
            await send_pipeline_status(request.callback_url, job_id, request.doc_id, request.kb_id, status)

        result = await ingest_pipeline.process(
            text=text,
            chunking_strategy=request.chunking.strategy,
            chunking_config=chunking_config,
            graph_extractor_type=request.graph.extractor_type,
            graph_config=graph_config,
            enable_text_cleaning=request.enable_text_cleaning,
            extraction_examples_yaml=request.extraction_examples_yaml,
            custom_prompt=request.custom_prompt,
            enable_entity_normalization=request.enable_entity_normalization,
            normalization_algorithm=request.normalization_algorithm,
            normalization_threshold=request.normalization_threshold,
            entity_dictionary=request.entity_dictionary,
            sampling_size=request.sampling_size,
            kb_id=request.kb_id,  # ✅ 추가
            doc_id=request.doc_id,  # ✅ 추가
            job_id=job_id,
            status_callback=pipeline_callback,
            # Model configurations
            ingest_llm=request.ingest_llm,
            chunk_grouping_llm=request.chunk_grouping_llm,
            noun_extraction_llm=request.noun_extraction_llm,
            embedding_model=request.embedding_model
        )
        
        if not result or jobs.get(job_id, {}).get("status") == JobStatus.CANCELLED:
            return
        
        # ✅ 임시 파일 저장: 메타데이터 (통계 정보)
        from app.utils.temp_storage import temp_storage
        await temp_storage.save_metadata(request.kb_id, request.doc_id, {
            "node_count": result["node_count"],
            "triple_count": result["triple_count"],
            "stats": result.get("stats", [])
        })
        
        jobs[job_id]["progress"] = 80
        if jobs[job_id]["status"] == JobStatus.CANCELLED:
             print(f"[IngestJob] Job {job_id} cancelled before saving.")
             return
        
        # ✅ STORING 상태 전송 (DB 저장 시작)
        await send_pipeline_status(request.callback_url, job_id, request.doc_id, request.kb_id, "STORING")
        
        # 5. Save (Milvus, Neo4j/Fuseki)
        print(f"[IngestJob] Saving to databases for doc {request.doc_id}...")
        
        # Milvus: 벡터 저장
        print(f"[IngestJob] Calling Milvus connector.insert_chunks...")


        
        # Milvus: 벡터 저장
        print(f"[IngestJob] Calling Milvus connector.insert_chunks...")
        # node_id를 포함하여 Fuseki의 source_node_id와 일치시킴
        chunks_data = [{
            "content": node.get_content(), 
            "metadata": node.metadata,
            "node_id": node.node_id  # LlamaIndex node_id 포함
        } for node in result["nodes"]]
        print(f"[IngestJob] Prepared {len(chunks_data)} chunks for Milvus")


        await milvus_connector.insert_chunks(
            request.kb_id,
            request.doc_id,
            chunks_data,
            result["embeddings"]
        )
        
        jobs[job_id]["progress"] = 90
        
        # Graph: Save triples (Neo4j or Fuseki) - Optional storage
        if result["triples"]:
            # ✅ Save to File System for Frontend / Backend access
            from app.utils.temp_storage import temp_storage
            await temp_storage.save_triples(request.kb_id, request.doc_id, result["triples"])
            print(f"[IngestJob] Saved {len(result['triples'])} triples to file system.")

            if request.graph_store == "fuseki":
                print(f"[IngestJob] Saving to Fuseki for doc {request.doc_id}...")
                await fuseki_connector.insert_triples(
                    request.kb_id,
                    request.doc_id,
                    result["triples"],
                    generate_inverse=request.graph.generate_inverse_relations
                )
            else:
                # Default to Neo4j
                print(f"[IngestJob] Saving to Neo4j for doc {request.doc_id}...")
                await neo4j_connector.insert_triples(
                    request.kb_id,
                    request.doc_id,
                    result["triples"],
                    generate_inverse=request.graph.generate_inverse_relations
                )
        
        jobs[job_id]["progress"] = 100
        jobs[job_id]["status"] = JobStatus.COMPLETED
        
        # Generate inferred relations (Post-loading)
        inference_count = 0
        if request.enable_inference and result["triples"]:
            if request.graph_store == "neo4j":
                print(f"[IngestJob] Running Neo4j inference engine for KB {request.kb_id}...")
                try:
                    from app.core.inference_engine import inference_engine
                    inference_count = await inference_engine.run_inference(
                        kb_id=request.kb_id,
                        doc_id=request.doc_id
                    )
                    print(f"[IngestJob] Neo4j Inference created {inference_count} new relations")
                except Exception as e:
                    print(f"[IngestJob] Neo4j Inference error: {e}")
            elif request.graph_store == "fuseki":
                print(f"[IngestJob] Running Fuseki inference engine for KB {request.kb_id}...")
                try:
                    from app.core.fuseki_inference_engine import fuseki_inference_engine
                    inference_count = await fuseki_inference_engine.run_inference(
                        kb_id=request.kb_id,
                        doc_id=request.doc_id
                    )
                    print(f"[IngestJob] Fuseki Inference applied {inference_count} rules")
                except Exception as e:
                    print(f"[IngestJob] Fuseki Inference error: {e}")

        
        jobs[job_id]["result"] = {
            "node_count": result["node_count"],
            "triple_count": result["triple_count"],
            "inference_count": inference_count,
        }
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
        print(f"[IngestJob] ✅ Job {job_id} COMPLETED for doc {request.doc_id}")
        
        # ✅ COMPLETED 상태 전송 (완료)
        await send_pipeline_status(request.callback_url, job_id, request.doc_id, request.kb_id, "COMPLETED")


        
        # 6. Call callback (Optional)
        if request.callback_url:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(request.callback_url, json={
                    "job_id": job_id,
                    "doc_id": request.doc_id,
                    "kb_id": request.kb_id,
                    "status": "completed",
                    "result": jobs[job_id]["result"],
                })
        
    except Exception as e:
        import traceback
        print(f"[IngestJob] ❌ Job {job_id} FAILED: {e}")
        traceback.print_exc()
        jobs[job_id]["status"] = JobStatus.FAILED
        jobs[job_id]["error"] = _format_model_error_message(str(e))
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()



@router.post("/ingest", response_model=IngestResponse)
async def create_ingest_job(
    request: IngestRequest,
    background_tasks: BackgroundTasks
):
    """Create an ingestion job"""
    job_id = str(uuid.uuid4())
    
    # Register job
    jobs[job_id] = {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "kb_id": request.kb_id,
        "doc_id": request.doc_id,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "progress": 0,
        "result": None,
        "error": None,
    }
    
    # Add background task
    background_tasks.add_task(process_ingest_job, job_id, request)
    
    return IngestResponse(
        job_id=job_id,
        status=jobs[job_id]["status"],
        message="Ingest job created successfully",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Get job status"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    return JobStatusResponse(**job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel job. Supports both official job_id and doc_id (for cleanup flows)."""
    target_job_id = None
    
    if job_id in jobs:
        target_job_id = job_id
    else:
        # Try to find by doc_id
        for jid, job in jobs.items():
            if job.get("doc_id") == job_id:
                target_job_id = jid
                break
    
    if not target_job_id:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[target_job_id]
    
    if job["status"] in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
         # Already finished, just return ok
         return {"message": f"Job already in state: {job['status']}", "job_id": target_job_id}
    
    jobs[target_job_id]["status"] = JobStatus.CANCELLED
    jobs[target_job_id]["updated_at"] = datetime.utcnow().isoformat()
    print(f"[Ingest] Job {target_job_id} (doc {job.get('doc_id')}) marked as CANCELLED")
    
    return {"message": "Job cancelled", "job_id": target_job_id}


@router.get("/jobs")
async def list_jobs(
    kb_id: Optional[str] = None,
    status: Optional[JobStatus] = None,
    limit: int = 50
):
    """List jobs"""
    result = []
    
    for job in jobs.values():
        if kb_id and job["kb_id"] != kb_id:
            continue
        if status and job["status"] != status:
            continue
        result.append(job)
        
        if len(result) >= limit:
            break
    
    return {"jobs": result, "total": len(result)}


# ============================================================
# Preview Endpoints (Two-Stage Ingestion)
# ============================================================

class PreviewRequest(BaseModel):
    """Preview Request - Extract only, no persistence"""
    kb_id: str
    doc_id: str
    file_path: str
    chunking: ChunkingConfig = ChunkingConfig()
    graph: GraphConfig = GraphConfig()
    graph_store: str = "neo4j"
    enable_text_cleaning: bool = False
    enable_subject_restoration: bool = True  # Restore omitted subjects in Korean text
    extraction_examples_yaml: Optional[str] = None
    custom_prompt: Optional[str] = None
    enable_entity_normalization: bool = False
    normalization_algorithm: str = "embedding"
    normalization_threshold: float = 0.85
    enable_normalization_confirmation: bool = False
    sampling_size: Optional[int] = None  # For Doc2Graph Dictionary (Phase 1)
    entity_dictionary: Optional[Dict[str, Any]] = None # Pre-computed dictionary
    callback_url: Optional[str] = None # For granular status updates
    # Model configurations
    ingest_llm: Optional[Dict[str, Any]] = None
    chunk_grouping_llm: Optional[Dict[str, Any]] = None
    subject_restoration_llm: Optional[Dict[str, Any]] = None
    noun_extraction_llm: Optional[Dict[str, Any]] = None
    embedding_model: Optional[Dict[str, Any]] = None


class PreviewResponse(BaseModel):
    """Preview Response"""
    preview_id: str
    kb_id: str
    doc_id: str
    node_count: int
    triples: List[Dict[str, Any]]
    stats: Optional[List[Dict[str, Any]]] = None
    message: str


class ConfirmRequest(BaseModel):
    """Confirm Request - Save previewed data"""
    enable_inference: bool = False
    callback_url: Optional[str] = None
    # For crash recovery:
    kb_id: Optional[str] = None
    doc_id: Optional[str] = None


@router.post("/preview", response_model=PreviewResponse)
async def create_preview(request: PreviewRequest):
    """Extract triples from document without saving to database.
    Returns preview_id and extracted triples for user review.
    """
    preview_id = str(uuid.uuid4())
    
    try:
        print(f"[Preview] Starting preview {preview_id} for doc {request.doc_id}")
        
        # 1. Read file
        from app.utils.file_utils import read_text_file
        text = await read_text_file(request.file_path)
        
        if not text:
            raise ValueError(f"Original file not found at {request.file_path}")
        
        print(f"[Preview] Read file: {len(text)} chars")
        
        # 1.5 Subject Restoration (Optional)
        if request.enable_subject_restoration:
            from app.core.subject_restoration import restore_subjects
            text = await restore_subjects(text, llm_config=request.subject_restoration_llm)
            print(f"[Preview] Subject restoration applied: {len(text)} chars")
        
        # 2. Prepare configs
        chunking_config = {
            "chunk_size": request.chunking.chunk_size,
            "chunk_overlap": request.chunking.chunk_overlap,
            "window_size": request.chunking.window_size,
            "chunk_sizes": request.chunking.chunk_sizes,
            "buffer_size": request.chunking.buffer_size,
            "breakpoint_threshold": request.chunking.breakpoint_threshold,
        }
        
        graph_config = {
            "max_paths_per_chunk": request.graph.max_paths_per_chunk,
            "max_triplets_per_chunk": request.graph.max_triplets_per_chunk,
            "num_workers": request.graph.num_workers,
            "allowed_entity_types": request.graph.allowed_entity_types,
            "allowed_relation_types": request.graph.allowed_relation_types,
        }

        # 3. Process with IngestPipeline (Multi-phase: Dictionary -> Chunks -> Triples)
        async def pipeline_callback(status):
            await send_pipeline_status(request.callback_url, preview_id, request.doc_id, request.kb_id, status)

        result = await ingest_pipeline.process(
            text=text,
            chunking_strategy=request.chunking.strategy,
            chunking_config=chunking_config,
            graph_extractor_type=request.graph.extractor_type,
            graph_config=graph_config,
            enable_text_cleaning=request.enable_text_cleaning,
            extraction_examples_yaml=request.extraction_examples_yaml,
            custom_prompt=request.custom_prompt,
            enable_entity_normalization=request.enable_entity_normalization,
            normalization_algorithm=request.normalization_algorithm,
            normalization_threshold=request.normalization_threshold,
            entity_dictionary=request.entity_dictionary,
            sampling_size=request.sampling_size,
            kb_id=request.kb_id,  # ✅ 추가
            doc_id=request.doc_id,  # ✅ 추가
            status_callback=pipeline_callback,
            # Model configurations
            ingest_llm=request.ingest_llm,
            chunk_grouping_llm=request.chunk_grouping_llm,
            noun_extraction_llm=request.noun_extraction_llm,
            embedding_model=request.embedding_model
        )
        
        print(f"[Preview] Extracted {len(result['triples'])} triples, {result['node_count']} nodes")
        
        # 4. Cache result (NO persistence yet)
        preview_cache[preview_id] = {
            "preview_id": preview_id,
            "kb_id": request.kb_id,
            "doc_id": request.doc_id,
            "graph_store": request.graph_store,
            "generate_inverse_relations": request.graph.generate_inverse_relations,
            "nodes": result["nodes"],
            "embeddings": result["embeddings"],
            "triples": result["triples"],
            "node_count": result["node_count"],
            "triple_count": result["triple_count"],
            "created_at": datetime.utcnow().isoformat(),
            "normalization_suggestions": result.get("normalization_suggestions"),
            "enable_entity_normalization": request.enable_entity_normalization,
            "enable_normalization_confirmation": request.enable_normalization_confirmation,
            "stats": result.get("stats"),
        }
        
        # ✅ Save to Temp Storage (Persistence for Recovery)
        from app.utils.temp_storage import temp_storage
        
        # Convert nodes to dicts for saving
        chunks_dict = [
            {
                "content": node.get_content(),
                "metadata": node.metadata, 
                "node_id": node.node_id
            } 
            for node in result["nodes"]
        ]
        
        await temp_storage.save_chunks(request.kb_id, request.doc_id, chunks_dict)
        await temp_storage.save_triples(request.kb_id, request.doc_id, result["triples"])
        await temp_storage.save_embeddings(request.kb_id, request.doc_id, result["embeddings"])
        # Save metadata including preview_id and graph_store settings for recovery
        await temp_storage.save_metadata(request.kb_id, request.doc_id, {
             "preview_id": preview_id,
             "node_count": result["node_count"],
             "triple_count": result["triple_count"],
             "graph_store": request.graph_store,
             "generate_inverse_relations": request.graph.generate_inverse_relations
        })
        
        return PreviewResponse(
            preview_id=preview_id,
            kb_id=request.kb_id,
            doc_id=request.doc_id,
            node_count=result["node_count"],
            triples=result["triples"],
            stats=result.get("stats"),
            message=f"Preview generated. {result['node_count']} nodes, {len(result['triples'])} triples extracted.",
        )
        
    except Exception as e:
        import traceback
        print(f"[Preview] ❌ Preview failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_format_model_error_message(str(e)))


@router.post("/confirm/{preview_id}")
async def confirm_preview(
    preview_id: str,
    request: ConfirmRequest,
    background_tasks: BackgroundTasks
):
    """Confirm and save previewed data to database."""
    
    # [Recovery Logic] If cache missed (e.g. restart), try to load from temp storage
    if preview_id not in preview_cache:
        if request.kb_id and request.doc_id:
            print(f"[Confirm] Cache miss for {preview_id}. Attempting recovery from disk for doc {request.doc_id}...")
            try:
                from app.utils.temp_storage import temp_storage
                from llama_index.core.schema import TextNode
                
                # Check if files exist
                triples_path = temp_storage.get_file_path(request.kb_id, request.doc_id, "triples.json")
                chunks_path = temp_storage.get_file_path(request.kb_id, request.doc_id, "chunks.json")
                embeddings_path = temp_storage.get_file_path(request.kb_id, request.doc_id, "embeddings.json")
                
                if triples_path.exists() and chunks_path.exists():
                    # Load all data using new methods
                    triples_data = await temp_storage.load_triples(request.kb_id, request.doc_id)
                    chunks_raw = await temp_storage.load_chunks(request.kb_id, request.doc_id)
                    embeddings_data = await temp_storage.load_embeddings(request.kb_id, request.doc_id)
                    metadata = await temp_storage.load_metadata(request.kb_id, request.doc_id)
                    
                    if not triples_data or not chunks_raw:
                        raise ValueError("Failed to load triples or chunks")
                    
                    # Reconstruct nodes
                    nodes = []
                    embeddings = embeddings_data or {}
                    
                    for c in chunks_raw:
                        # Reconstruct TextNode
                        node = TextNode(
                            text=c.get("content", ""),
                            id_=c.get("node_id") or c.get("id"),
                            metadata=c.get("metadata", {})
                        )
                        # Attach embedding if available
                        if node.node_id in embeddings:
                            node.embedding = embeddings[node.node_id]
                        nodes.append(node)
                    
                    # Get graph_store settings from metadata (with fallback)
                    graph_store = metadata.get("graph_store", "neo4j") if metadata else "neo4j"
                    generate_inverse = metadata.get("generate_inverse_relations", True) if metadata else True
                            
                    # Reconstruct Cache
                    preview_cache[preview_id] = {
                        "preview_id": preview_id,
                        "kb_id": request.kb_id,
                        "doc_id": request.doc_id,
                        "graph_store": graph_store,
                        "generate_inverse_relations": generate_inverse,
                        "nodes": nodes,
                        "embeddings": embeddings, 
                        "triples": triples_data,
                        "node_count": len(nodes),
                        "triple_count": len(triples_data),
                        "created_at": datetime.utcnow().isoformat(),
                        "normalization_suggestions": None,
                        "enable_entity_normalization": False,
                        "enable_normalization_confirmation": False,
                        "stats": None
                    }
                    print(f"[Confirm] ✅ Successfully recovered preview data from disk ({len(nodes)} nodes, {len(triples_data)} triples, {len(embeddings)} embeddings).")
                else:
                    print(f"[Confirm] ❌ Recovery failed: Temp files not found (triples: {triples_path.exists()}, chunks: {chunks_path.exists()}).")
            except Exception as e:
                import traceback
                print(f"[Confirm] ❌ Recovery error: {e}")
                traceback.print_exc()
        
    if preview_id not in preview_cache:
        raise HTTPException(status_code=404, detail="Preview not found or expired (Logic: Server Restarted?)")
    
    cached = preview_cache[preview_id]
    
    # Create job for tracking
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "kb_id": cached["kb_id"],
        "doc_id": cached["doc_id"],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "progress": 0,
        "result": None,
        "error": None,
    }
    
    # Run save in background
    background_tasks.add_task(
        _save_preview_data,
        job_id,
        preview_id,
        request.enable_inference,
        request.callback_url
    )
    
    return {
        "job_id": job_id,
        "preview_id": preview_id,
        "status": "saving",
        "message": "Preview data is being saved to database.",
    }


async def _save_preview_data(
    job_id: str,
    preview_id: str,
    enable_inference: bool,
    callback_url: Optional[str]
):
    """Background task to save preview data"""
    try:
        jobs[job_id]["status"] = JobStatus.PROCESSING
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
        
        cached = preview_cache.get(preview_id)
        if not cached:
            raise ValueError("Preview data not found")
        
        kb_id = cached["kb_id"]
        doc_id = cached["doc_id"]
        
        # [New] Send STORING status
        await send_pipeline_status(callback_url, job_id, doc_id, kb_id, "STORING")
        
        # 1. Save to Milvus
        print(f"[Confirm] Saving {cached['node_count']} chunks to Milvus...")
        chunks_data = [{"content": node.get_content(), "metadata": node.metadata} for node in cached["nodes"]]
        await milvus_connector.insert_chunks(
            kb_id,
            doc_id,
            chunks_data,
            cached["embeddings"]
        )
        jobs[job_id]["progress"] = 50
        
        # 2. Save to Graph Store
        if cached["triples"]:
            if cached["graph_store"] == "fuseki":
                print(f"[Confirm] Saving {len(cached['triples'])} triples to Fuseki...")
                await fuseki_connector.insert_triples(
                    kb_id,
                    doc_id,
                    cached["triples"],
                    generate_inverse=cached["generate_inverse_relations"]
                )
            else:
                print(f"[Confirm] Saving {len(cached['triples'])} triples to Neo4j...")
                await neo4j_connector.insert_triples(
                    kb_id,
                    doc_id,
                    cached["triples"],
                    generate_inverse=cached["generate_inverse_relations"]
                )
        
        jobs[job_id]["progress"] = 90
        
        # 3. Run inference if enabled
        inference_count = 0
        if enable_inference and cached["triples"]:
            if cached["graph_store"] == "neo4j":
                from app.core.inference_engine import inference_engine
                inference_count = await inference_engine.run_inference(kb_id, doc_id)
            elif cached["graph_store"] == "fuseki":
                from app.core.fuseki_inference_engine import fuseki_inference_engine
                inference_count = await fuseki_inference_engine.run_inference(kb_id, doc_id)
        
        jobs[job_id]["progress"] = 100
        jobs[job_id]["status"] = JobStatus.COMPLETED
        jobs[job_id]["result"] = {
            "node_count": cached["node_count"],
            "triple_count": cached["triple_count"],
            "inference_count": inference_count,
        }
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
        
        # Cleanup preview cache
        del preview_cache[preview_id]
        
        print(f"[Confirm] ✅ Preview {preview_id} saved successfully")
        
        # ✅ COMPLETED 상태 전송 (완료)
        await send_pipeline_status(callback_url, job_id, doc_id, kb_id, "COMPLETED")
        
        # Callback
        if callback_url:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(callback_url, json={
                    "job_id": job_id,
                    "doc_id": doc_id,
                    "kb_id": kb_id,
                    "status": "completed",
                    "result": jobs[job_id]["result"],
                })
        
    except Exception as e:
        import traceback
        print(f"[Confirm] ❌ Save failed: {e}")
        traceback.print_exc()
        jobs[job_id]["status"] = JobStatus.FAILED
        jobs[job_id]["error"] = _format_model_error_message(str(e))
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()


@router.delete("/preview/{preview_id}")
async def discard_preview(preview_id: str):
    """Discard preview data without saving."""
    if preview_id not in preview_cache:
        raise HTTPException(status_code=404, detail="Preview not found or already discarded")
    
    cached = preview_cache[preview_id]
    del preview_cache[preview_id]
    
    print(f"[Discard] Preview {preview_id} discarded")
    
    return {
        "preview_id": preview_id,
        "kb_id": cached["kb_id"],
        "doc_id": cached["doc_id"],
        "message": "Preview discarded successfully.",
    }



# ============================================================
# Chunk Extract Endpoint (Extract Test Feature)
# ============================================================

class ChunkExtractRequest(BaseModel):
    """Chunk Extract Request - Extract triples from chunk text directly"""
    chunk_text: str
    extractor_type: str = "simple"  # simple | dynamic | schema
    max_paths_per_chunk: int = Field(default=10, ge=1, le=50)
    max_triplets_per_chunk: int = Field(default=20, ge=1, le=100)
    num_workers: int = Field(default=4, ge=1, le=16)
    generate_inverse_relations: bool = True
    extraction_examples_yaml: Optional[str] = None
    custom_prompt: Optional[str] = None


class ChunkExtractResponse(BaseModel):
    """Chunk Extract Response"""
    triples: List[Dict[str, Any]]
    triple_count: int
    message: str


@router.post("/extract-chunk", response_model=ChunkExtractResponse)
async def extract_from_chunk(request: ChunkExtractRequest):
    """Extract triples from a single chunk text without saving.
    
    This endpoint is used for testing extraction settings on a single chunk
    before applying them to full document ingestion.
    """
    try:
        print(f"[ExtractChunk] Starting extraction for chunk ({len(request.chunk_text)} chars)")
        
        # Map string extractor_type to enum
        extractor_type_map = {
            "simple": GraphExtractorType.SIMPLE,
            "dynamic": GraphExtractorType.DYNAMIC,
            "schema": GraphExtractorType.SCHEMA,
            "none": GraphExtractorType.NONE,
        }
        extractor_type = extractor_type_map.get(request.extractor_type, GraphExtractorType.SIMPLE)
        
        if extractor_type == GraphExtractorType.NONE:
            return ChunkExtractResponse(
                triples=[],
                triple_count=0,
                message="Extractor type is 'none', no extraction performed."
            )
        
        # Create a temporary node from chunk text
        from llama_index.core.schema import TextNode
        temp_node = TextNode(text=request.chunk_text, id_="temp_chunk")
        
        # Prepare graph config
        graph_config = {
            "max_paths_per_chunk": request.max_paths_per_chunk,
            "max_triplets_per_chunk": request.max_triplets_per_chunk,
            "num_workers": request.num_workers,
        }
        
        # Extract triples using pipeline
        triples = await ingest_pipeline.extract_graph(
            nodes=[temp_node],
            extractor_type=extractor_type,
            config=graph_config,
            examples=request.extraction_examples_yaml,
            custom_prompt=request.custom_prompt
        )
        
        # Generate inverse relations if requested
        if request.generate_inverse_relations and triples:
            inverse_triples = []
            inverse_mapping = {
                "스승": "제자", "제자": "스승",
                "부모": "자녀", "자녀": "부모",
                "선생": "학생", "학생": "선생",
                "상사": "부하", "부하": "상사",
            }
            for t in triples:
                pred = t.get("predicate", "")
                if pred in inverse_mapping:
                    inverse_triples.append({
                        "subject": t["object"],
                        "predicate": inverse_mapping[pred],
                        "object": t["subject"],
                        "source_node_id": t.get("source_node_id"),
                        "confidence": t.get("confidence", 0.7),
                        "is_inverse": True,
                    })
            triples.extend(inverse_triples)
        
        print(f"[ExtractChunk] Extracted {len(triples)} triples")
        
        return ChunkExtractResponse(
            triples=triples,
            triple_count=len(triples),
            message=f"Successfully extracted {len(triples)} triples from chunk."
        )
        
    except Exception as e:
        import traceback
        print(f"[ExtractChunk] ❌ Extraction failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_format_model_error_message(str(e)))


# ============================================================
# Save Chunk Triples Endpoint
# ============================================================

class SaveChunkTriplesRequest(BaseModel):
    """Save Chunk Triples Request"""
    kb_id: str
    chunk_id: str
    triples: List[Dict[str, Any]]


class SaveChunkTriplesResponse(BaseModel):
    """Save Chunk Triples Response"""
    kb_id: str
    chunk_id: str
    triple_count: int
    message: str


@router.post("/save-chunk-triples", response_model=SaveChunkTriplesResponse)
async def save_chunk_triples(request: SaveChunkTriplesRequest):
    """Save selected triples from chunk extraction to the triple store.
    
    This endpoint allows users to selectively save triples that were extracted
    from a single chunk during the Extract Test feature.
    """
    try:
        print(f"[SaveChunkTriples] Saving {len(request.triples)} triples for chunk {request.chunk_id} in KB {request.kb_id}")
        
        # Format triples with chunk_id as source_node_id
        formatted_triples = []
        for triple in request.triples:
            formatted_triple = {
                "subject": triple.get("subject"),
                "predicate": triple.get("predicate"),
                "object": triple.get("object"),
                "source_node_id": request.chunk_id,  # Link triple to chunk
                "confidence": triple.get("confidence", 0.8),
            }
            formatted_triples.append(formatted_triple)
        
        # Try to save to Fuseki (default)
        try:
            # We need to query which graph backend the KB uses
            # For now, we'll try Fuseki first, then fall back to Neo4j
            print(f"[SaveChunkTriples] Attempting to save to Fuseki...")
            await fuseki_connector.insert_triples(
                kb_id=request.kb_id,
                doc_id=f"manual_{request.chunk_id}",  # Create a pseudo doc_id
                triples=formatted_triples,
                generate_inverse=False  # User already selected the triples they want
            )
            print(f"[SaveChunkTriples] ✅ Saved {len(formatted_triples)} triples to Fuseki")
            
        except Exception as fuseki_error:
            print(f"[SaveChunkTriples] Fuseki failed: {fuseki_error}, trying Neo4j...")
            try:
                await neo4j_connector.insert_triples(
                    kb_id=request.kb_id,
                    doc_id=f"manual_{request.chunk_id}",
                    triples=formatted_triples,
                    generate_inverse=False
                )
                print(f"[SaveChunkTriples] ✅ Saved {len(formatted_triples)} triples to Neo4j")
            except Exception as neo4j_error:
                print(f"[SaveChunkTriples] Both Fuseki and Neo4j failed")
                raise Exception(f"Failed to save to both backends. Fuseki: {fuseki_error}, Neo4j: {neo4j_error}")
        
        return SaveChunkTriplesResponse(
            kb_id=request.kb_id,
            chunk_id=request.chunk_id,
            triple_count=len(formatted_triples),
            message=f"Successfully saved {len(formatted_triples)} triples for chunk {request.chunk_id}"
        )
        
    except Exception as e:
        import traceback
        print(f"[SaveChunkTriples] ❌ Save failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_format_model_error_message(str(e)))
