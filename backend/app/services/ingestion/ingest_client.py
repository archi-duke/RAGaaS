"""
Ingest Service Client

메인 백엔드에서 Ingest Service API를 호출하기 위한 클라이언트.
"""
import httpx
from typing import Dict, Any, Optional
import os

# Ingest Service URL (docker-compose 환경변수 또는 기본값)
INGEST_SERVICE_URL = os.getenv("INGEST_SERVICE_URL", "http://127.0.0.1:8001")


class IngestServiceClient:
    """Ingest Service API 클라이언트"""
    
    def __init__(self, base_url: str = INGEST_SERVICE_URL):
        self.base_url = base_url.rstrip("/")
    
    async def create_ingest_job(
        self,
        kb_id: str,
        doc_id: str,
        file_path: str,
        chunking_config: Dict[str, Any],
        graph_config: Dict[str, Any],
        graph_store: str = "neo4j",
        enable_text_cleaning: bool = False,
        enable_subject_restoration: bool = True,
        extraction_examples_yaml: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        enable_entity_normalization: bool = False,
        normalization_algorithm: str = "embedding",
        normalization_threshold: float = 0.85,
        enable_normalization_confirmation: bool = False,
        callback_url: Optional[str] = None,
        entity_dictionary: Optional[Dict[str, Any]] = None,
        sampling_size: Optional[int] = None,
        ingest_llm: Optional[Dict[str, Any]] = None,
        chunk_grouping_llm: Optional[Dict[str, Any]] = None,
        embedding_model: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """인제스션 작업 생성"""
        payload = {
            "kb_id": kb_id,
            "doc_id": doc_id,
            "file_path": file_path,
            "chunking": chunking_config,
            "graph": graph_config,
            "graph_store": graph_store,
            "enable_text_cleaning": enable_text_cleaning,
            "enable_subject_restoration": enable_subject_restoration,
            "extraction_examples_yaml": extraction_examples_yaml,
            "custom_prompt": custom_prompt,
            "enable_entity_normalization": enable_entity_normalization,
            "normalization_algorithm": normalization_algorithm,
            "normalization_threshold": normalization_threshold,
            "enable_normalization_confirmation": enable_normalization_confirmation,
            "callback_url": callback_url,
            "entity_dictionary": entity_dictionary,
            "sampling_size": sampling_size,
            "ingest_llm": ingest_llm,
            "chunk_grouping_llm": chunk_grouping_llm,
            "embedding_model": embedding_model,
        }

        
        async with httpx.AsyncClient(timeout=3600.0) as client:
            response = await client.post(
                f"{self.base_url}/api/ingest",
                json=payload
            )
            response.raise_for_status()
            return response.json()
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """작업 상태 조회"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/api/jobs/{job_id}"
            )
            response.raise_for_status()
            return response.json()
    
    async def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """작업 취소"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.base_url}/api/jobs/{job_id}/cancel"
            )
            response.raise_for_status()
            return response.json()
    
    async def health_check(self) -> bool:
        """Health check"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False


# Singleton instance
ingest_client = IngestServiceClient()
