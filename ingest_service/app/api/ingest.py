"""
Ingest API Router
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
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
    max_paths_per_chunk: int = Field(default=10, ge=1, le=50)
    max_triplets_per_chunk: int = Field(default=20, ge=1, le=100)
    num_workers: int = Field(default=4, ge=1, le=16)
    allowed_entity_types: Optional[List[str]] = None
    allowed_relation_types: Optional[List[str]] = None
    generate_inverse_relations: bool = True


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
    callback_url: Optional[str] = None


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


async def process_ingest_job(job_id: str, request: IngestRequest):
    """Process ingestion job in background"""
    try:
        print(f"[IngestJob] Starting job {job_id} for doc {request.doc_id}")
        jobs[job_id]["status"] = JobStatus.PROCESSING
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
        
        # 1. Read file (PDF or Text)
        file_path = request.file_path
        if file_path.lower().endswith('.pdf'):
            from pypdf import PdfReader
            import io
            with open(file_path, "rb") as f:
                pdf = PdfReader(io.BytesIO(f.read()))
                text = ""
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
            print(f"[IngestJob] Read PDF: {len(text)} chars")
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            print(f"[IngestJob] Read text file: {len(text)} chars")
        
        # 1.5 Subject Restoration (Optional)
        if request.enable_subject_restoration:
            from app.core.subject_restoration import restore_subjects
            text = await restore_subjects(text)
            print(f"[IngestJob] Subject restoration applied: {len(text)} chars")
        
        jobs[job_id]["progress"] = 10

        
        # 2. Convert chunking config
        chunking_config = {
            "chunk_size": request.chunking.chunk_size,
            "chunk_overlap": request.chunking.chunk_overlap,
            "window_size": request.chunking.window_size,
            "chunk_sizes": request.chunking.chunk_sizes,
            "buffer_size": request.chunking.buffer_size,
            "breakpoint_threshold": request.chunking.breakpoint_threshold,
        }
        
        # 3. Convert graph config
        graph_config = {
            "max_paths_per_chunk": request.graph.max_paths_per_chunk,
            "max_triplets_per_chunk": request.graph.max_triplets_per_chunk,
            "num_workers": request.graph.num_workers,
            "allowed_entity_types": request.graph.allowed_entity_types,
            "allowed_relation_types": request.graph.allowed_relation_types,
        }
        
        jobs[job_id]["progress"] = 20
        
        # 4. Run pipeline
        result = await ingest_pipeline.process(
            text=text,
            chunking_strategy=request.chunking.strategy,
            chunking_config=chunking_config,
            graph_extractor_type=request.graph.extractor_type,
            graph_config=graph_config,
            enable_text_cleaning=request.enable_text_cleaning,
            extraction_examples_yaml=request.extraction_examples_yaml,
            custom_prompt=request.custom_prompt
        )
        
        jobs[job_id]["progress"] = 80
        
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
        jobs[job_id]["error"] = str(e)
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
        status=JobStatus.PENDING,
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
    """Cancel job"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    if job["status"] in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status: {job['status']}"
        )
    
    jobs[job_id]["status"] = JobStatus.CANCELLED
    jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
    
    return {"message": "Job cancelled", "job_id": job_id}


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


class PreviewResponse(BaseModel):
    """Preview Response"""
    preview_id: str
    kb_id: str
    doc_id: str
    node_count: int
    triples: List[Dict[str, Any]]
    message: str


class ConfirmRequest(BaseModel):
    """Confirm Request - Save previewed data"""
    enable_inference: bool = False
    callback_url: Optional[str] = None


@router.post("/preview", response_model=PreviewResponse)
async def create_preview(request: PreviewRequest):
    """Extract triples from document without saving to database.
    Returns preview_id and extracted triples for user review.
    """
    preview_id = str(uuid.uuid4())
    
    try:
        print(f"[Preview] Starting preview {preview_id} for doc {request.doc_id}")
        
        # 1. Read file
        file_path = request.file_path
        if file_path.lower().endswith('.pdf'):
            from pypdf import PdfReader
            import io
            with open(file_path, "rb") as f:
                pdf = PdfReader(io.BytesIO(f.read()))
                text = ""
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
            print(f"[Preview] Read PDF: {len(text)} chars")
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            print(f"[Preview] Read text file: {len(text)} chars")
        
        # 1.5 Subject Restoration (Optional)
        if request.enable_subject_restoration:
            from app.core.subject_restoration import restore_subjects
            text = await restore_subjects(text)
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
        
        # 3. Run pipeline (same as regular ingest)
        result = await ingest_pipeline.process(
            text=text,
            chunking_strategy=request.chunking.strategy,
            chunking_config=chunking_config,
            graph_extractor_type=request.graph.extractor_type,
            graph_config=graph_config,
            enable_text_cleaning=request.enable_text_cleaning,
            extraction_examples_yaml=request.extraction_examples_yaml,
            custom_prompt=request.custom_prompt
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
        }
        
        return PreviewResponse(
            preview_id=preview_id,
            kb_id=request.kb_id,
            doc_id=request.doc_id,
            node_count=result["node_count"],
            triples=result["triples"],
            message=f"Preview generated. {result['node_count']} nodes, {len(result['triples'])} triples extracted.",
        )
        
    except Exception as e:
        import traceback
        print(f"[Preview] ❌ Preview failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/confirm/{preview_id}")
async def confirm_preview(
    preview_id: str,
    request: ConfirmRequest,
    background_tasks: BackgroundTasks
):
    """Confirm and save previewed data to database."""
    if preview_id not in preview_cache:
        raise HTTPException(status_code=404, detail="Preview not found or expired")
    
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
        jobs[job_id]["error"] = str(e)
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
        triples = ingest_pipeline.extract_graph(
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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))
