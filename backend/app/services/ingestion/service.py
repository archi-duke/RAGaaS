import io
from pypdf import PdfReader
from .text_splitter import chunking_service
from app.services.embedding import embedding_service
from app.core.milvus import create_collection
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.core.fuseki import fuseki_client
from app.core.neo4j_client import neo4j_client
from app.services.ingestion.graph import graph_processor
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.core.database import SessionLocal, get_db
from app.services.ingestion.doc2onto import doc2onto_processor


class IngestionService:
    async def process_document(
        self, 
        kb_id: str, 
        doc_id: str, 
        filename: str, 
        file_content: bytes, 
        chunking_strategy: str = "size",
        chunking_config: str = "{}"
    ):
        try:
            # Check if Graph RAG is enabled (Doc2Onto)
            use_doc2onto = False
            graph_backend = "ontology"
            async with SessionLocal() as db:
                result = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.id == kb_id))
                kb_check = result.scalars().first()
                if kb_check and kb_check.enable_graph_rag and getattr(kb_check, 'graph_backend', '') in ['neo4j', 'ontology']:
                    use_doc2onto = True
                    graph_backend = getattr(kb_check, 'graph_backend', 'ontology')

            # 1. Parse File
            text = ""
            if filename.endswith(".pdf"):
                pdf = PdfReader(io.BytesIO(file_content))
                for page in pdf.pages:
                    text += page.extract_text()
            else:
                text = file_content.decode("utf-8")

            # 2. Chunking
            chunks = []
            
            # Parse config if it's a string (from FormData)
            import json
            config = {}
            if chunking_config and isinstance(chunking_config, str):
                try:
                    config = json.loads(chunking_config)
                except:
                    pass
            elif isinstance(chunking_config, dict):
                config = chunking_config

            if chunking_strategy == "size":
                texts = chunking_service.chunk_by_size(
                    text,
                    chunk_size=int(config.get("chunk_size", 1000)),
                    overlap=int(config.get("overlap", 200)),
                    separators=config.get("separators")
                )
                chunks = [{"content": t, "metadata": {}} for t in texts]
            elif chunking_strategy == "parent_child":
                chunks = chunking_service.chunk_parent_child(
                    text,
                    parent_size=int(config.get("parent_size", 2000)),
                    child_size=int(config.get("child_size", 500)),
                    parent_overlap=int(config.get("parent_overlap", 0)),
                    child_overlap=int(config.get("child_overlap", 100)),
                    separators=config.get("separators")
                )
            elif chunking_strategy == "context_aware":
                if config.get("semantic_mode"):
                    texts = chunking_service.chunk_semantic(
                        text,
                        buffer_size=int(config.get("buffer_size", 1)),
                        breakpoint_threshold_type=config.get("breakpoint_type", "percentile"),
                        breakpoint_threshold_amount=float(config.get("breakpoint_amount", 95.0))
                    )
                else:
                    # Convert config headers (e.g. {"h1": true}) to list of tuples
                    headers = []
                    if config.get("h1"): headers.append(("#", "Header 1"))
                    if config.get("h2"): headers.append(("##", "Header 2"))
                    if config.get("h3"): headers.append(("###", "Header 3"))
                    
                    texts = chunking_service.chunk_context_aware(
                        text,
                        headers_to_split_on=headers if headers else None
                    )
                chunks = [{"content": t, "metadata": {}} for t in texts]
            else:
                texts = chunking_service.chunk_by_size(text)
                chunks = [{"content": t, "metadata": {}} for t in texts]

            # 3. Embedding
            texts_to_embed = [c["content"] for c in chunks if c["content"].strip()]
            
            if not texts_to_embed:
                print(f"Warning: No text content found in document {filename}")
                # We can either raise error or just mark as completed with 0 chunks
                # For now, let's raise error to inform user
                raise ValueError("No text content could be extracted from the document.")

            # Batch embedding if needed, but for now simple
            vectors = await embedding_service.get_embeddings(texts_to_embed)

            # 4. Insert into Milvus
            collection = create_collection(kb_id)
            
            # Extract metadata
            metadatas = [c["metadata"] for c in chunks if c["content"].strip()]

            data = [
                [doc_id] * len(texts_to_embed), # doc_id
                [f"{doc_id}_{i}" for i in range(len(texts_to_embed))], # chunk_id
                texts_to_embed, # content
                metadatas, # metadata
                vectors # vector
            ]
            
            collection.insert(data)
            collection.flush() # Ensure data is visible

            # 4.5. Doc2Onto Graph Ingestion (if enabled)
            # Doc2Onto handles triple extraction and links to RAGaaS chunks
            
            # FORCE FALLBACK to RAGaaS extraction (User Request)
            print("[Ingestion] Forcing Fallback Graph Extraction (Skipping Doc2Onto)")
            await self._fallback_graph_extraction(
                text, doc_id, kb_id, texts_to_embed, graph_backend, config
            )
            
            # Original Doc2Onto logic (Disabled)
            if False and use_doc2onto and doc2onto_processor.enabled:
                import tempfile
                import os
                
                print(f"[Doc2Onto] Starting graph extraction for {doc_id}...")
                print(f"[Doc2Onto] Backend: {graph_backend}, Chunks: {len(texts_to_embed)}")
                
                # Export RAGaaS chunks to temp file for Doc2Onto
                chunks_jsonl_path = None
                tmp_doc_path = None
                
                try:
                    # Create temp directory for this document
                    tmp_dir = tempfile.mkdtemp(prefix=f"doc2onto_{doc_id}_")
                    
                    # Export chunks to JSONL
                    chunks_jsonl_path = os.path.join(tmp_dir, "ragaas_chunks.jsonl")
                    with open(chunks_jsonl_path, "w", encoding="utf-8") as f:
                        for i, chunk_text in enumerate(texts_to_embed):
                            chunk_data = {
                                "chunk_id": f"{doc_id}_{i}",
                                "doc_id": doc_id,
                                "doc_ver": "v1",
                                "text": chunk_text,
                                "chunk_idx": i,
                                "start_offset": None,  # RAGaaS doesn't track offsets
                                "end_offset": None,
                                "section_path": None,
                                "chunk_hash": ""
                            }
                            f.write(json.dumps(chunk_data, ensure_ascii=False) + "\n")
                    
                    # Save document to temp file
                    suffix = ".pdf" if filename.endswith(".pdf") else ".txt"
                    tmp_doc_path = os.path.join(tmp_dir, f"{doc_id}{suffix}")
                    with open(tmp_doc_path, "w", encoding="utf-8") as f:
                        f.write(text)
                    
                    # Call Doc2Onto with external chunks
                    doc2onto_result = await doc2onto_processor.process_document_full(
                        file_path=tmp_doc_path,
                        kb_id=kb_id,
                        doc_id=doc_id,
                        graph_backend=graph_backend,
                        chunking_strategy=chunking_strategy,
                        external_chunks_path=chunks_jsonl_path,
                        config=config
                    )
                    
                    if doc2onto_result.get("status") == "success":
                        print(f"[Doc2Onto] Graph extraction completed: {doc2onto_result.get('result', {})}")
                    elif doc2onto_result.get("status") == "skipped":
                        print(f"[Doc2Onto] Skipped: {doc2onto_result.get('reason')}. Using fallback LLM extraction.")
                        # Fallback to legacy extraction if Doc2Onto is skipped
                        await self._fallback_graph_extraction(
                            text, doc_id, kb_id, texts_to_embed, graph_backend, config
                        )
                    else:
                        print(f"[Doc2Onto] Unexpected result: {doc2onto_result}")
                        
                except Exception as e:
                    print(f"[Doc2Onto] Error during graph extraction: {e}")
                    import traceback
                    traceback.print_exc()
                    # Continue without graph - don't fail the entire ingestion
                    
                finally:
                    # Cleanup temp files
                    if tmp_dir and os.path.exists(tmp_dir):
                        import shutil
                        # Keep for debugging, uncomment to clean up
                        # shutil.rmtree(tmp_dir, ignore_errors=True)
                        pass
            
            # 5. Update Status to COMPLETED
            async with SessionLocal() as db:
                result = await db.execute(select(Document).filter(Document.id == doc_id))
                doc = result.scalars().first()
                if doc:
                    doc.status = DocumentStatus.COMPLETED.value
                    await db.commit()
                    
                    # Broadcast WebSocket notification
                    from app.core.websocket_manager import manager
                    await manager.broadcast(kb_id, {
                        "type": "document_status_update",
                        "doc_id": doc_id,
                        "status": DocumentStatus.COMPLETED.value,
                        "filename": filename
                    })
        except Exception as e:
            # Update status to ERROR on failure
            print(f"Error processing document {doc_id}: {str(e)}")
            try:
                async with SessionLocal() as db:
                    result = await db.execute(select(Document).filter(Document.id == doc_id))
                    doc = result.scalars().first()
                    if doc:
                        doc.status = DocumentStatus.ERROR.value
                        await db.commit()
                        
                        # Broadcast WebSocket notification for error
                        from app.core.websocket_manager import manager
                        await manager.broadcast(kb_id, {
                            "type": "document_status_update",
                            "doc_id": doc_id,
                            "status": DocumentStatus.ERROR.value,
                            "filename": filename
                        })
            except Exception as db_err:
                print(f"Error updating document status to ERROR: {str(db_err)}")

    async def _fallback_graph_extraction(
        self,
        text: str,
        doc_id: str,
        kb_id: str,
        texts_to_embed: List[str],
        graph_backend: str,
        config: dict
    ):
        """Fallback to legacy LLM-based graph extraction when Doc2Onto is disabled."""
        print(f"[Fallback] Using legacy LLM graph extraction for {doc_id}...")
        
        graph_section_size = int(config.get("graph_section_size", 6000))
        graph_section_overlap = int(config.get("graph_section_overlap", 500))
        
        is_neo4j = graph_backend == 'neo4j'
        
        if not is_neo4j:
            try:
                fuseki_client.create_dataset(kb_id)
            except Exception as e:
                print(f"Warning: Could not create/verify Fuseki dataset: {e}")
        
        sections = chunking_service.split_into_sections(
            text, 
            section_size=graph_section_size,
            overlap=graph_section_overlap
        )
        
        all_triples = []
        for i, section_text in enumerate(sections):
            section_id = f"{doc_id}_section_{i}"
            try:
                graph_result = await graph_processor.extract_graph_elements(
                    section_text, section_id, kb_id, config
                )
                triples = graph_result.get("structured_triples", [])
                
                if not is_neo4j:
                    rdf_triples = graph_result.get("rdf_triples", [])
                    if rdf_triples:
                        fuseki_client.insert_triples(kb_id, rdf_triples)
                else:
                    all_triples.extend(triples)
                    
            except Exception as e:
                print(f"Error processing graph for section {i}: {e}")
        
        if is_neo4j and all_triples:
            chunk_ids = [f"{doc_id}_{i}" for i in range(len(texts_to_embed))]
            
            for triple in all_triples:
                try:
                    query = """
                    MERGE (s:Entity {name: $subj})
                    MERGE (o:Entity {name: $obj})
                    MERGE (s)-[:RELATION {type: $pred}]->(o)
                    """
                    neo4j_client.execute_query(query, {
                        "subj": triple["subject"],
                        "obj": triple["object"],
                        "pred": triple["predicate"]
                    })
                except Exception as e:
                    print(f"Error inserting triple: {e}")
            
            # Link entities to chunks
            for i, chunk_text in enumerate(texts_to_embed):
                chunk_id = chunk_ids[i]
                chunk_text_lower = chunk_text.lower()
                
                for triple in all_triples:
                    subj = triple["subject"]
                    obj = triple["object"]
                    
                    subj_in_chunk = subj.lower() in chunk_text_lower
                    obj_in_chunk = obj.lower() in chunk_text_lower
                    
                    if subj_in_chunk or obj_in_chunk:
                        try:
                            link_query = "MERGE (c:Chunk {id: $chunk_id})"
                            params = {"chunk_id": chunk_id}
                            
                            if subj_in_chunk:
                                link_query += """
                                WITH c
                                MATCH (s:Entity {name: $subj})
                                MERGE (s)-[:MENTIONED_IN]->(c)
                                """
                                params["subj"] = subj
                            if obj_in_chunk:
                                link_query += """
                                WITH c
                                MATCH (o:Entity {name: $obj})
                                MERGE (o)-[:MENTIONED_IN]->(c)
                                """
                                params["obj"] = obj
                                
                            neo4j_client.execute_query(link_query, params)
                        except:
                            pass
            
            print(f"[Fallback] Graph ingestion complete for {kb_id}")

ingestion_service = IngestionService()
