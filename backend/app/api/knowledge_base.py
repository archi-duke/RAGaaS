from fastapi import APIRouter, Depends, HTTPException, Body
from dataclasses import asdict
from pymilvus import Collection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from app.core.database import get_db
from app.models.knowledge_base import KnowledgeBase as KBModel
from app.schemas import KnowledgeBaseCreate, KnowledgeBase
from app.core.milvus import create_collection, utility, connect_milvus
from app.models.document import Document as DocModel
from sqlalchemy import delete

import yaml
import os
from pathlib import Path
from app.core.config import settings
import requests
import json

from app.core.fuseki import fuseki_client

router = APIRouter()

@router.post("/", response_model=KnowledgeBase)
async def create_knowledge_base(kb: KnowledgeBaseCreate, db: AsyncSession = Depends(get_db)):
    # Auto-set enable_graph_rag if graph_backend is specified (not 'none')
    enable_graph = kb.enable_graph_rag
    if kb.graph_backend and kb.graph_backend != 'none':
        enable_graph = True
    
    db_kb = KBModel(
        name=kb.name, 
        description=kb.description,
        chunking_strategy=kb.chunking_strategy,
        chunking_config=kb.chunking_config,
        metric_type='COSINE',  # Always use COSINE
        enable_graph_rag=enable_graph,
        graph_backend=kb.graph_backend
    )
    db.add(db_kb)
    await db.commit()
    await db.refresh(db_kb)
    
    # Create Milvus collection
    try:
        create_collection(db_kb.id, metric_type=db_kb.metric_type)
    except Exception as e:
        print(f"Failed to create Milvus collection: {e}")

    # Create Fuseki dataset if Graph RAG is enabled
    if db_kb.enable_graph_rag:
        try:
            fuseki_client.create_dataset(db_kb.id)
        except Exception as e:
            print(f"Failed to create Fuseki dataset: {e}")
        
    return db_kb

@router.get("/", response_model=List[KnowledgeBase])
async def list_knowledge_bases(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func
    
    # Get KBs with document count
    result = await db.execute(
        select(
            KBModel,
            func.count(DocModel.id).label('document_count')
        )
        .outerjoin(DocModel, KBModel.id == DocModel.kb_id)
        .group_by(KBModel.id)
        .offset(skip)
        .limit(limit)
    )
    
    kbs_with_stats = []
    for row in result:
        kb = row[0]
        
        # Performance optimization: Skip querying Milvus for updated collection stats per KB
        collection_size = 0
        
        # Convert to dict and add stats
        kb_dict = {
            "id": kb.id,
            "name": kb.name,
            "description": kb.description,
            "created_at": kb.created_at,
            "updated_at": kb.updated_at,
            "chunking_strategy": kb.chunking_strategy,
            "chunking_config": kb.chunking_config,
            "metric_type": kb.metric_type,
            "enable_graph_rag": kb.enable_graph_rag,
            "graph_backend": kb.graph_backend,
            "is_promoted": kb.is_promoted,
            "promotion_metadata": kb.promotion_metadata,
            "document_count": row[1],
            "total_size": collection_size
        }
        kbs_with_stats.append(kb_dict)
    
    return kbs_with_stats

@router.get("/{kb_id}", response_model=KnowledgeBase)
async def get_knowledge_base(kb_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KBModel).filter(KBModel.id == kb_id))
    kb = result.scalars().first()
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return kb

@router.post("/{kb_id}/promote")
async def promote_knowledge_base(
    kb_id: str, 
    payload: dict = Body(default={}), 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.id == kb_id))
    kb = result.scalars().first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    
    # If payload has 'action' == 'revert', demote
    if payload.get("action") == "revert":
        kb.is_promoted = False
    else:
        kb.is_promoted = True
        
        # Update metadata
        # Support flat params or {config: ...}
        params = payload.get("config", payload)
        
        # Add timestamp
        from datetime import datetime
        params["promoted_at"] = datetime.now().isoformat()
        
        # Store in DB
        # Note: SQLAlchemy JSON type change detection can be tricky.
        # Assigning a new dict works best.
        kb.promotion_metadata = params

    await db.commit()
    await db.refresh(kb)
    return {"id": kb.id, "is_promoted": kb.is_promoted, "promotion_metadata": kb.promotion_metadata}

@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KBModel).filter(KBModel.id == kb_id))
    kb = result.scalars().first()
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    
    # Delete all associated documents
    await db.execute(delete(DocModel).where(DocModel.kb_id == kb_id))
    
    await db.delete(kb)
    await db.commit()
    
    # Drop Milvus collection
    try:
        connect_milvus()
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        try:
            if utility.has_collection(collection_name):
                col = Collection(collection_name)
                col.drop()
        except Exception:
            pass
            
    except Exception as e:
        print(f"Error during Milvus cleanup: {e}")

    # Delete Fuseki dataset
    try:
        fuseki_client.delete_dataset(kb_id)
    except Exception as e:
        print(f"Error deleting Fuseki dataset: {e}")
        
    return {"ok": True}

    return {"ok": True}
@router.get("/extraction-rules/content")
async def get_extraction_rules():
    file_path = Path("extraction_examples.yaml")
    if not file_path.exists():
        return {"content": ""}
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return {"content": content}

@router.post("/extraction-rules/validate")
async def validate_extraction_rules(data: dict = Body(...)):
    content = data.get("content", "")
    if not content:
        return {"valid": True, "message": "Content is empty"}
    
    # 1. YAML Syntax Check
    try:
        rules = yaml.safe_load(content)
        if not isinstance(rules, list):
            return {"valid": False, "message": "Rules must be a list of examples."}
    except Exception as e:
        return {"valid": False, "message": f"YAML Syntax Error: {str(e)}"}
    
    # 2. LLM Semantic Check
    try:
        prompt = f"""You are a Knowledge Graph Extraction expert. 
Review the following extraction rules (few-shot examples) provided in YAML format.
Check if:
1. Each example has 'text' and 'triples'.
2. The 'triples' follow the structure (subject, predicate, object).
3. The extraction logic is consistent and makes sense.

Rules:
{content}

If there are any issues, point them out clearly in Korean.
If everything is perfect, respond with "OK".
"""
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that validates YAML extraction rules."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        llm_reply = response.json()["choices"][0]["message"]["content"]
        
        if llm_reply.strip().upper() == "OK":
            return {"valid": True, "message": "Validation Successful"}
        else:
            return {"valid": False, "message": f"LLM Feedback: {llm_reply}"}
            
    except Exception as e:
        return {"valid": False, "message": f"LLM Validation Failed: {str(e)}"}

@router.post("/extraction-rules/save")
async def save_extraction_rules(data: dict = Body(...)):
    content = data.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")
        
    try:
        # Final safety check
        yaml.safe_load(content)
        
        file_path = Path("extraction_examples.yaml")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save: {str(e)}")

@router.get("/query-prompt/content")
async def get_query_prompt_content(type: str = "ontology"):
    try:
        if type == "neo4j":
            file_path = Path("data/prompts/cypher_generation_prompt.txt")
            if file_path.exists():
                return {"content": file_path.read_text(encoding="utf-8")}
            from app.services.retrieval.cypher_generator import CypherGenerator
            return {"content": CypherGenerator.DEFAULT_SYSTEM_PROMPT}
        else:
            file_path = Path("data/prompts/sparql_generation_prompt.txt")
            if file_path.exists():
                return {"content": file_path.read_text(encoding="utf-8")}
            from app.doc2onto.qa.sparql_generator import SPARQLGenerator
            return {"content": SPARQLGenerator.DEFAULT_SYSTEM_PROMPT} 
    except Exception as e:
         return {"content": f"Error: {e}"}

@router.post("/query-prompt/save")
async def save_query_prompt(data: dict = Body(...)):
    content = data.get("content", "")
    p_type = data.get("type", "ontology")
    
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")
        
    if p_type == "neo4j":
        file_path = Path("data/prompts/cypher_generation_prompt.txt")
    else:
        file_path = Path("data/prompts/sparql_generation_prompt.txt")
        
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save: {str(e)}")

@router.get("/extraction-prompt/content")
async def get_extraction_prompt():
    file_path = Path("data/prompts/graph_extraction_prompt.txt")
    if file_path.exists():
        return {"content": file_path.read_text(encoding="utf-8")}
    
    # Fallback to hardcoded default if file missing
    from app.services.ingestion.graph import GraphProcessor
    # We temporarily use a dummy processor to get its default
    return {"content": "Prompt file not found. Please contact admin."}

@router.post("/extraction-prompt/save")
async def save_extraction_prompt(data: dict = Body(...)):
    content = data.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")
        
    # Same logic to find path
    paths = [
        Path("data/prompts/graph_extraction_prompt.txt"),
        Path("backend/data/prompts/graph_extraction_prompt.txt"),
        Path("/app/data/prompts/graph_extraction_prompt.txt")
    ]
    
    file_path = paths[0] # Default
    for p in paths:
        if p.exists():
            file_path = p
            break
    
    try:
        # Create directory if it doesn't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save: {str(e)}")
