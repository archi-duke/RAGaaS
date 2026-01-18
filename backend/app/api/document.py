from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from typing import List
from app.models.document import Document as DocModel, DocumentStatus
from app.models.knowledge_base import KnowledgeBase as KBModel
from app.schemas import Document
from app.services.ingestion import ingestion_service
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/{kb_id}/documents", response_model=Document)
async def upload_document(
    kb_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    chunking_config: str = Form(None)
):
    # Fetch Knowledge Base
    kb = await KBModel.get(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    # Check for duplicate filename
    existing_doc = await DocModel.find_one(DocModel.kb_id == kb_id, DocModel.filename == file.filename)
    
    if existing_doc:
        logger.info(f"Overwriting existing document: {file.filename}")
        
        # 1. Clear existing vectors from Milvus to prevent duplicates
        try:
            from app.core.milvus import create_collection
            collection = create_collection(kb_id)
            collection.load()
            
            # Delete by doc_id
            expr = f'doc_id == "{existing_doc.id}"'
            collection.delete(expr)
            collection.flush()
            logger.info(f"Deleted old chunks for doc {existing_doc.id} from Milvus")
        except Exception as e:
            logger.warning(f"Failed to clear old chunks from Milvus during overwrite: {e}")
            
        # 2. Update existing DB record
        existing_doc.status = DocumentStatus.PROCESSING.value
        from datetime import datetime
        existing_doc.updated_at = datetime.utcnow()
        await existing_doc.save()
        
        doc = existing_doc
    else:
        # Create new Document record
        doc = DocModel(
            kb_id=kb_id,
            filename=file.filename,
            file_type=file.filename.split(".")[-1],
            status=DocumentStatus.PROCESSING.value 
        )
        await doc.insert()

    # Read file content
    content = await file.read()
    
    # Merge chunking config
    final_config = kb.chunking_config.copy() if kb.chunking_config else {}
    if chunking_config:
        try:
            import json
            override = json.loads(chunking_config)
            final_config.update(override)
        except Exception as e:
            logger.error(f"Failed to parse chunking_config override: {e}")

    # Feature flag: Use new Ingest Service or legacy processing
    from app.core.config import settings
    
    if settings.USE_INGEST_SERVICE:
        # New LlamaIndex-based Ingest Service
        import os
        import json as json_lib
        from app.services.ingestion.ingest_client import ingest_client
        
        # Save file to shared storage
        shared_path = settings.SHARED_STORAGE_PATH
        os.makedirs(shared_path, exist_ok=True)
        file_path = os.path.join(shared_path, f"{doc.id}_{doc.filename}")
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        logger.info(f"[IngestService] File saved to {file_path}")
        
        # Build graph config from frontend params
        graph_config = {
            "extractor_type": final_config.get("extractor_type", "simple"),
            "max_paths_per_chunk": final_config.get("max_paths_per_chunk", 10),
            "max_triplets_per_chunk": final_config.get("max_triplets_per_chunk", 20),
            "num_workers": final_config.get("num_workers", 4),
            "generate_inverse_relations": final_config.get("generate_inverse_relations", True),
        }
        
        # Build chunking config for LlamaIndex
        chunking_cfg = {
            "strategy": kb.chunking_strategy or "fixed_size",
            "chunk_size": final_config.get("chunk_size", 500),
            "chunk_overlap": final_config.get("chunk_overlap", 100),
            "window_size": final_config.get("window_size", 3),
            "chunk_sizes": final_config.get("chunk_sizes", [2048, 512, 128]),
            "breakpoint_threshold": final_config.get("breakpoint_threshold", 0.5),
        }
        
        # Call Ingest Service asynchronously
        async def call_ingest_service():
            try:
                result = await ingest_client.create_ingest_job(
                    kb_id=kb_id,
                    doc_id=doc.id,
                    file_path=file_path,
                    chunking_config=chunking_cfg,
                    graph_config=graph_config if kb.enable_graph_rag else {},
                    callback_url=None  # TODO: Implement callback endpoint
                )
                logger.info(f"[IngestService] Job created: {result}")
            except Exception as e:
                logger.error(f"[IngestService] Failed to create job: {e}")
                # Update document status to ERROR
                doc_obj = await DocModel.get(doc.id)
                if doc_obj:
                    doc_obj.status = DocumentStatus.ERROR.value
                    await doc_obj.save()
        
        background_tasks.add_task(call_ingest_service)
    else:
        # Legacy Doc2Onto-based processing
        background_tasks.add_task(
            ingestion_service.process_document,
            kb_id,
            doc.id,
            doc.filename,
            content,
            kb.chunking_strategy,
            final_config
        )
    
    return doc


@router.get("/{kb_id}/documents", response_model=List[Document])
async def list_documents(kb_id: str):
    docs = await DocModel.find(DocModel.kb_id == kb_id).to_list()
    return docs

@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(
    kb_id: str, 
    doc_id: str, 
    background_tasks: BackgroundTasks
):
    doc = await DocModel.find_one(DocModel.id == doc_id, DocModel.kb_id == kb_id)
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Transactional Deletion: Mark as DELETING and run background task
    try:
        doc.status = DocumentStatus.DELETING.value
        await doc.save()
        
        from app.services.ingestion.cleanup_service import cleanup_service
        background_tasks.add_task(cleanup_service.perform_cascading_deletion, kb_id, doc_id)
        
        return {"ok": True, "message": "Deletion started in background"}
        
    except Exception as e:
        logger.error(f"Failed to initiate deletion for doc {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{kb_id}/documents/{doc_id}/chunks")
async def get_document_chunks(kb_id: str, doc_id: str):
    from app.core.milvus import create_collection
    
    # Verify document exists
    doc = await DocModel.find_one(DocModel.id == doc_id, DocModel.kb_id == kb_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Query Milvus for chunks
    collection = create_collection(kb_id)
    collection.load()
    
    # Query by doc_id
    expr = f'doc_id == "{doc_id}"'
    try:
        results = collection.query(
            expr=expr,
            output_fields=["chunk_id", "content", "doc_id", "metadata"],
            limit=1000  # Adjust as needed
        )
    except Exception as e:
        # Fallback for legacy collections without metadata field
        print(f"Error querying with metadata: {str(e)}. Falling back to legacy query.")
        results = collection.query(
            expr=expr,
            output_fields=["chunk_id", "content", "doc_id"],
            limit=1000
        )
    
    return {
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "status": doc.status
        },
        "chunks": results
    }

@router.put("/{kb_id}/documents/{doc_id}/chunks/{chunk_id}")
async def update_chunk(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    content: str = Form(...)
):
    """Update chunk content and re-generate embedding"""
    try:
        from app.core.milvus import create_collection
        from app.services.embedding import embedding_service
        from datetime import datetime
        
        # Verify document exists
        doc = await DocModel.find_one(DocModel.id == doc_id, DocModel.kb_id == kb_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Get collection
        collection = create_collection(kb_id)
        collection.load()
        
        # Verify chunk exists
        expr = f'chunk_id == "{chunk_id}"'
        try:
            existing_chunks = collection.query(
                expr=expr,
                output_fields=["chunk_id", "content", "doc_id", "metadata"],
                limit=1
            )
        except Exception as e:
            # Fallback for collections without metadata field
            print(f"Error querying with metadata: {e}")
            existing_chunks = collection.query(
                expr=expr,
                output_fields=["chunk_id", "content", "doc_id"],
                limit=1
            )
        
        if not existing_chunks:
            raise HTTPException(status_code=404, detail="Chunk not found")
        
        # Get existing metadata if any
        existing_metadata = existing_chunks[0].get('metadata', {}) if len(existing_chunks) > 0 else {}
        
        # Generate new embedding
        embeddings = await embedding_service.get_embeddings([content])
        new_embedding = embeddings[0]
        
        # Delete old chunk
        collection.delete(expr)
        collection.flush()
        
        # Insert updated chunk using entity format
        entities = [{
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "content": content,
            "metadata": existing_metadata,
            "vector": new_embedding
        }]
        
        collection.insert(entities)
        collection.flush()
        
        # Update Graph RAG if enabled
        kb = await KBModel.get(kb_id)
        
        if kb and kb.enable_graph_rag:
            try:
                from app.core.fuseki import fuseki_client
                from app.services.ingestion.graph import graph_processor
                
                logger.info(f"Updating Graph RAG for chunk {chunk_id}")
                
                 # Ensure dataset exists
                try:
                    fuseki_client.create_dataset(kb_id)
                except Exception as e:
                    logger.warning(f"Could not create/verify dataset: {e}")
                
                # Delete existing triples for this chunk
                # Delete all triples where the chunk is the source
                chunk_uri = f"http://rag.local/source/{chunk_id}"
                
                # SPARQL DELETE query to remove old triples
                delete_query = f"""
                PREFIX rel: <http://rag.local/relation/>
                DELETE {{
                    ?s ?p ?o .
                }}
                WHERE {{
                    ?s rel:hasSource <{chunk_uri}> .
                    ?s ?p ?o .
                }}
                """
                
                fuseki_client.update(kb_id, delete_query)
                logger.info(f"Deleted old graph triples for chunk {chunk_id}")
                
                # Extract new entities and relationships
                config = kb.chunking_config if kb.chunking_config else {}
                new_triples = await graph_processor.extract_graph_elements(content, chunk_id, kb_id, config)
                
                if new_triples:
                    # Insert new triples
                    fuseki_client.insert_triples(kb_id, new_triples)
                    logger.info(f"Inserted {len(new_triples)} new graph triples for chunk {chunk_id}")
                else:
                    logger.warning(f"No graph elements extracted from updated chunk {chunk_id}")
                    
            except Exception as graph_error:
                # Don't fail the entire update if graph update fails
                logger.error(f"Error updating graph for chunk {chunk_id}: {graph_error}")
                import traceback
                traceback.print_exc()
        
        # Update document's updated_at timestamp
        doc.updated_at = datetime.utcnow()
        await doc.save()
        
        return {
            "ok": True,
            "chunk_id": chunk_id,
            "content": content,
            "updated_at": doc.updated_at.isoformat(),
            "graph_updated": kb.enable_graph_rag if kb else False
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error updating chunk: {e}")
        print(error_details)
        raise HTTPException(status_code=500, detail=f"Failed to update chunk: {str(e)}")
