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


# In-memory job storage (실제 운영에서는 Redis 또는 DB 사용)
jobs: Dict[str, Dict[str, Any]] = {}


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChunkingConfig(BaseModel):
    """청킹 설정"""
    strategy: ChunkingStrategy = ChunkingStrategy.FIXED_SIZE
    chunk_size: int = Field(default=1024, ge=100, le=10000)
    chunk_overlap: int = Field(default=20, ge=0, le=1000)
    window_size: int = Field(default=3, ge=1, le=10)
    chunk_sizes: List[int] = Field(default=[2048, 512, 128])
    buffer_size: int = Field(default=1, ge=1, le=5)
    breakpoint_threshold: int = Field(default=95, ge=50, le=99)


class GraphConfig(BaseModel):
    """그래프 추출 설정"""
    extractor_type: GraphExtractorType = GraphExtractorType.NONE
    max_paths_per_chunk: int = Field(default=10, ge=1, le=50)
    max_triplets_per_chunk: int = Field(default=20, ge=1, le=100)
    num_workers: int = Field(default=4, ge=1, le=16)
    allowed_entity_types: Optional[List[str]] = None
    allowed_relation_types: Optional[List[str]] = None
    generate_inverse_relations: bool = True


class IngestRequest(BaseModel):
    """인제스션 요청"""
    kb_id: str
    doc_id: str
    file_path: str
    chunking: ChunkingConfig = ChunkingConfig()
    graph: GraphConfig = GraphConfig()
    graph_store: str = "neo4j"  # "neo4j" or "fuseki"
    enable_text_cleaning: bool = False  # 번호/불릿 등 형식 문자 제거
    enable_inference: bool = False  # 규칙 기반 관계 추론
    callback_url: Optional[str] = None


class IngestResponse(BaseModel):
    """인제스션 응답"""
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    """작업 상태 응답"""
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
    """백그라운드 인제스션 작업 처리"""
    try:
        print(f"[IngestJob] Starting job {job_id} for doc {request.doc_id}")
        jobs[job_id]["status"] = JobStatus.PROCESSING
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
        
        # 1. 파일 읽기 (PDF 또는 텍스트)
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
        
        jobs[job_id]["progress"] = 10

        
        # 2. 청킹 설정 변환
        chunking_config = {
            "chunk_size": request.chunking.chunk_size,
            "chunk_overlap": request.chunking.chunk_overlap,
            "window_size": request.chunking.window_size,
            "chunk_sizes": request.chunking.chunk_sizes,
            "buffer_size": request.chunking.buffer_size,
            "breakpoint_threshold": request.chunking.breakpoint_threshold,
        }
        
        # 3. 그래프 설정 변환
        graph_config = {
            "max_paths_per_chunk": request.graph.max_paths_per_chunk,
            "max_triplets_per_chunk": request.graph.max_triplets_per_chunk,
            "num_workers": request.graph.num_workers,
            "allowed_entity_types": request.graph.allowed_entity_types,
            "allowed_relation_types": request.graph.allowed_relation_types,
        }
        
        jobs[job_id]["progress"] = 20
        
        # 4. 파이프라인 실행
        result = await ingest_pipeline.process(
            text=text,
            chunking_strategy=request.chunking.strategy,
            chunking_config=chunking_config,
            graph_extractor_type=request.graph.extractor_type,
            graph_config=graph_config,
            enable_text_cleaning=request.enable_text_cleaning,
        )
        
        jobs[job_id]["progress"] = 80
        
        # 5. 저장 (Milvus, Neo4j/Fuseki)
        print(f"[IngestJob] Saving to databases for doc {request.doc_id}...")
        
        # Milvus: 벡터 저장
        print(f"[IngestJob] Calling Milvus connector.insert_chunks...")


        
        # Milvus: 벡터 저장
        print(f"[IngestJob] Calling Milvus connector.insert_chunks...")
        chunks_data = [{"content": node.get_content(), "metadata": node.metadata} for node in result["nodes"]]
        print(f"[IngestJob] Prepared {len(chunks_data)} chunks for Milvus")


        await milvus_connector.insert_chunks(
            request.kb_id,
            request.doc_id,
            chunks_data,
            result["embeddings"]
        )
        
        jobs[job_id]["progress"] = 90
        
        # Graph: 트리플 저장 (Neo4j 또는 Fuseki) - 선택적 저장
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
        
        # 추론 관계 생성 (적재 이후, Neo4j만 지원)
        inference_count = 0
        if request.enable_inference and request.graph_store == "neo4j" and result["triples"]:
            print(f"[IngestJob] Running inference engine for KB {request.kb_id}...")
            try:
                from app.core.inference_engine import inference_engine
                inference_count = await inference_engine.run_inference(
                    kb_id=request.kb_id,
                    doc_id=request.doc_id
                )
                print(f"[IngestJob] Inference created {inference_count} new relations")
            except Exception as e:
                print(f"[IngestJob] Inference error: {e}")
        
        jobs[job_id]["result"] = {
            "node_count": result["node_count"],
            "triple_count": result["triple_count"],
            "inference_count": inference_count,
        }
        jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
        print(f"[IngestJob] ✅ Job {job_id} COMPLETED for doc {request.doc_id}")


        
        # 6. 콜백 호출 (선택사항)
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
    """인제스션 작업 생성"""
    job_id = str(uuid.uuid4())
    
    # 작업 등록
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
    
    # 백그라운드 작업 추가
    background_tasks.add_task(process_ingest_job, job_id, request)
    
    return IngestResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message="Ingest job created successfully",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """작업 상태 조회"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    return JobStatusResponse(**job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """작업 취소"""
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
    """작업 목록 조회"""
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
