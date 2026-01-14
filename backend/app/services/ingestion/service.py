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
                # 오프셋 정보를 포함하여 청킹 (트리플-청크 매핑에 필수)
                chunks_data = chunking_service.chunk_by_size_with_offset(
                    text,
                    chunk_size=int(config.get("chunk_size", 1000)),
                    overlap=int(config.get("overlap", 200)),
                    separators=config.get("separators")
                )
                chunks = [{
                    "content": item["content"],
                    "metadata": {
                        "start_index": item["start_offset"],
                        "end_index": item["end_offset"]
                    }
                } for item in chunks_data]
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
                chunks_data = chunking_service.chunk_by_size_with_offset(text)
                chunks = []
                for item in chunks_data:
                    chunks.append({
                        "content": item["content"],  # "text" → "content"로 수정
                        "metadata": {
                            "start_index": item["start_offset"],
                            "end_index": item["end_offset"]
                        }
                    })

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
                text, doc_id, kb_id, texts_to_embed, graph_backend, config, chunks=chunks
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

    def _convert_triples_to_rdf(self, triples: List[dict], kb_id: str, doc_id: str) -> List[str]:
        """구조화된 트리플을 RDF 형식으로 변환"""
        import re
        import urllib.parse
        
        def sanitize_uri(text: str) -> str:
            """URI에 사용할 수 있도록 텍스트 정리"""
            clean = re.sub(r'[^a-zA-Z0-9_\uAC00-\uD7A3\u0400-\u04FF]+', '_', text.strip())
            return urllib.parse.quote(clean)
        
        rdf_lines = []
        namespace_entity = "http://rag.local/entity/"
        namespace_relation = "http://rag.local/relation/"
        
        for t in triples:
            subj = sanitize_uri(t.get("subject", ""))
            pred = sanitize_uri(t.get("predicate", ""))
            obj = sanitize_uri(t.get("object", ""))
            
            if not all([subj, pred, obj]):
                continue
            
            s_uri = f"<{namespace_entity}{subj}>"
            p_uri = f"<{namespace_relation}{pred}>"
            o_uri = f"<{namespace_entity}{obj}>"
            
            # 트리플 추가
            rdf_lines.append(f"{s_uri} {p_uri} {o_uri} .")
            
            # Label 추가 (검색 성능 향상)
            rdf_lines.append(f'{s_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{t["subject"]}" .')
            rdf_lines.append(f'{p_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{t["predicate"]}" .')
            rdf_lines.append(f'{o_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{t["object"]}" .')
        
        return rdf_lines

    async def _fallback_graph_extraction(
        self,
        text: str,
        doc_id: str,
        kb_id: str,
        texts_to_embed: List[str],
        graph_backend: str,
        config: dict,
        chunks: List[dict] = None  # 청크 오프셋 매핑을 위해 추가
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
        
        # 오프셋 포함 섹션 분할
        sections = chunking_service.split_into_sections_with_offset(
            text, 
            section_size=graph_section_size,
            overlap=graph_section_overlap
        )
        
        all_triples = []
        all_rdf_triples = []
        
        for i, section in enumerate(sections):
            section_text = section["text"]
            section_start = section["start_offset"]
            section_end = section["end_offset"]
            section_id = f"{doc_id}_section_{i}"
            
            try:
                graph_result = await graph_processor.extract_graph_elements(
                    section_text, section_id, kb_id, config
                )
                triples = graph_result.get("structured_triples", [])
                
                # 각 트리플에 소스 오프셋 추가
                for triple in triples:
                    triple["source_start"] = section_start
                    triple["source_end"] = section_end
                
                all_triples.extend(triples)
                
                # Fuseki는 나중에 일괄 처리
                if not is_neo4j:
                    rdf_triples = graph_result.get("rdf_triples", [])
                    all_rdf_triples.extend(rdf_triples)
                    
            except Exception as e:
                print(f"Error processing graph for section {i}: {e}")
        
        print(f"[Fallback] Total sections processed: {len(sections)}, Total triples collected: {len(all_triples)}")

        
        # 후처리: 필터링 + 정규화 + 역관계 생성 (Neo4j와 Fuseki 모두)
        if all_triples:
            from app.services.ingestion.graph_postprocessor import post_process_triples, add_inverse_relations
            
            print(f"[Fallback] Raw triples: {len(all_triples)}")
            
            # 1. 노이즈 제거 및 정규화 (오프셋 정보 유지)
            filtered_triples = post_process_triples(
                all_triples,
                confidence_threshold=config.get("confidence_threshold", 0.0),
                normalize=True
            )
            print(f"[Fallback] After filtering: {len(filtered_triples)}")
            
            # 2. 역관계 자동 생성 (config 옵션에 따라)
            if config.get("extract_inverse_relations", True):
                final_triples = add_inverse_relations(filtered_triples)
                print(f"[Fallback] With inverse relations: {len(final_triples)}")
            else:
                final_triples = filtered_triples
                print(f"[Fallback] Inverse relations disabled, using {len(final_triples)} triples")
            
            # 3. 트리플-오프셋 매핑 저장 (SQLite)
            await self._save_triple_mappings(kb_id, doc_id, final_triples, chunks)
            
            # 4. 백엔드별 적재
            if is_neo4j:
                all_triples = final_triples
            else:
                # Fuseki: 구조화된 트리플을 RDF로 변환
                rdf_triples = self._convert_triples_to_rdf(final_triples, kb_id, doc_id)
                fuseki_client.insert_triples(kb_id, rdf_triples)
                print(f"[Fallback] Inserted {len(rdf_triples)} RDF triples to Fuseki")
        
        if is_neo4j and all_triples:
            print(f"[Fallback] Inserting {len(all_triples)} triples to Neo4j...")
            
            for triple in all_triples:
                try:
                    # APOC을 사용하여 동적 관계 타입 생성
                    # predicate를 관계 타입으로 직접 사용 (예: :스승, :제자)
                    query = """
                    MERGE (s:Entity {name: $subj, kb_id: $kb_id})
                    MERGE (o:Entity {name: $obj, kb_id: $kb_id})
                    WITH s, o
                    CALL apoc.merge.relationship(s, $pred, {}, $props, o, $props) YIELD rel
                    RETURN rel

                    """
                    neo4j_client.execute_query(query, {
                        "subj": triple["subject"],
                        "obj": triple["object"],
                        "pred": triple["predicate"],
                        "kb_id": kb_id,
                        "props": {"is_inverse": triple.get("is_inverse", False)}
                    })
                except Exception as e:
                    print(f"Error inserting triple: {e}")
            
            print(f"[Fallback] Neo4j insertion complete.")
            
            # NOTE: Chunk 노드 및 MENTIONED_IN 관계 생성 로직 제거됨
            # 트리플-청크 매핑은 SQLite 해시 테이블로 관리
            
            print(f"[Fallback] Graph ingestion complete for {kb_id}")

    async def _save_triple_mappings(self, kb_id: str, doc_id: str, triples: List[dict], chunks: List[dict] = None):
        """트리플-오프셋 매핑을 SQLite에 저장"""
        from app.models.triple_chunk_mapping import TripleChunkMapping, compute_triple_hash
        import uuid
        
        # Pre-process chunks for faster lookup
        doc_chunks = []
        if chunks:
            for i, c in enumerate(chunks):
                meta = c.get("metadata", {})
                start = meta.get("start_index")
                end = meta.get("end_index")
                # 청크 ID 생성 (process_document와 동일한 로직)
                # 주의: process_document에서 id를 명시적으로 전달받지 않았으므로 재비생
                chunk_id = f"{doc_id}_{i}"
                if start is not None and end is not None:
                     doc_chunks.append({"id": chunk_id, "start": int(start), "end": int(end)})
        
        try:
            async with SessionLocal() as db:
                count = 0
                for triple in triples:
                    # 오프셋 정보가 없으면 스킵
                    if "source_start" not in triple or "source_end" not in triple:
                        continue
                    
                    t_start = int(triple["source_start"])
                    t_end = int(triple["source_end"])
                    
                    triple_hash = compute_triple_hash(
                        triple["subject"],
                        triple["predicate"],
                        triple["object"]
                    )
                    
                    # Find overlapping chunks
                    related_chunk_ids = []
                    if doc_chunks:
                        for dc in doc_chunks:
                             # Overlap check: max(s1, s2) < min(e1, e2)
                             if max(dc["start"], t_start) < min(dc["end"], t_end):
                                 related_chunk_ids.append(dc["id"])
                    
                    # If no related chunks found (or no chunks info), save with None (legacy behavior)
                    if not related_chunk_ids:
                        related_chunk_ids = [None]
                        
                    for chunk_id in related_chunk_ids:
                        mapping = TripleChunkMapping(
                            id=str(uuid.uuid4()),
                            kb_id=kb_id,
                            doc_id=doc_id,
                            chunk_id=chunk_id,
                            triple_hash=triple_hash,
                            subject=triple["subject"],
                            predicate=triple["predicate"],
                            object=triple["object"],
                            source_start=t_start,
                            source_end=t_end
                        )
                        db.add(mapping)
                        count += 1
                
                await db.commit()
                print(f"[Fallback] Saved {count} triple mappings (split by chunks) to SQLite (doc_id: {doc_id})")
                
                await db.commit()
                print(f"[Fallback] Saved {len(triples)} triple mappings to SQLite (doc_id: {doc_id})")
        except Exception as e:
            print(f"[Fallback] Error saving triple mappings: {e}")

ingestion_service = IngestionService()
