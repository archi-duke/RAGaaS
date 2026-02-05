"""
Dictionary Preview API Router

문서의 엔티티 사전을 미리 추출하여 확인할 수 있는 API
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Dict, Any, List
import io

router = APIRouter()


class DictionaryPreviewResponse(BaseModel):
    """Dictionary Preview Response"""
    entities: Dict[str, Dict[str, Any]]
    entity_count: int
    message: str


@router.post("/preview-dictionary", response_model=DictionaryPreviewResponse)
async def preview_entity_dictionary(
    file: UploadFile = File(...),
    sampling_size: int = Form(5000)
):
    """
    문서에서 엔티티 사전만 추출하여 미리보기를 제공합니다.
    전체 인제스션 없이 DictionaryBuilder만 실행합니다.
    """
    try:
        print(f"[DictionaryPreview] Starting preview for file: {file.filename}")
        
        # 1. Read file
        content = await file.read()
        
        if file.filename.lower().endswith('.pdf'):
            from pypdf import PdfReader
            pdf = PdfReader(io.BytesIO(content))
            text = ""
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
            print(f"[DictionaryPreview] Read PDF: {len(text)} chars")
        else:
            text = content.decode("utf-8")
            print(f"[DictionaryPreview] Read text file: {len(text)} chars")
        
        if len(text.strip()) < 100:
            raise ValueError("Document is too short to extract meaningful entities.")
        
        # 2. Chunk the text (DictionaryBuilder now requires chunks)
        from app.core.pipeline import ingest_pipeline, ChunkingStrategy
        
        # Use default chunking config
        chunking_config = {
            "chunk_size": 512,
            "chunk_overlap": 50
        }
        
        # Dictionary Preview는 속도를 위해 FIXED_SIZE 사용
        chunks = ingest_pipeline.chunk_document(
            text, 
            ChunkingStrategy.FIXED_SIZE,
            chunking_config
        )
        print(f"[DictionaryPreview] Created {len(chunks)} chunks")
        
        # 3. Build dictionary using DictionaryBuilder
        from app.core.dictionary_builder import DictionaryBuilder
        
        dict_builder = DictionaryBuilder(ingest_pipeline.llm)
        entity_dict = await dict_builder.build(chunks, sampling_size=sampling_size)  # ← chunks 및 sampling_size 전달
        
        print(f"[DictionaryPreview] Built dictionary with {len(entity_dict)} entities")
        
        return DictionaryPreviewResponse(
            entities=entity_dict,
            entity_count=len(entity_dict),
            message=f"Successfully extracted {len(entity_dict)} entities from document."
        )
        
    except Exception as e:
        import traceback
        print(f"[DictionaryPreview] ❌ Preview failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
