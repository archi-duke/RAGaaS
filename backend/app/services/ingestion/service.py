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
from app.core.database import client # or remove completely if not used directly

from typing import List, Optional, Dict, Any

class IngestionService:
    def _normalize_whitespace(self, text: str) -> str:
        """
        Normalize whitespace: 
        1. Keep double newlines (paragraphs).
        2. Replace single newlines with space (hard breaks in PDF).
        3. Clean up excessive spaces.
        """
        import re
        if not text:
            return ""
            
        # Standardize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Mark paragraphs (2+ newlines with optional whitespace in between)
        placeholder = " [[PARA]] "
        text = re.sub(r'\n\s*\n+', placeholder, text)
        
        # Replace remaining single newlines with space
        text = text.replace('\n', ' ')
        
        # Restore paragraphs
        text = text.replace(placeholder, '\n\n')
        
        # Clean up multiple spaces
        text = re.sub(r'[ \t]+', ' ', text)
        
        return text.strip()

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
            # NOTE: Graph RAG is now handled by the LlamaIndex Ingest Service (document.py)
            # This legacy method is kept for non-graph document processing fallback only.

            # 1. Parse File
            text = ""
            if filename.endswith(".pdf"):
                pdf = PdfReader(io.BytesIO(file_content))
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
            else:
                text = file_content.decode("utf-8")

            # 1.5. Normalize Whitespace (Merge hard breaks from PDF/Text)
            text = self._normalize_whitespace(text)

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


            # 5. Update Status to COMPLETED
            doc = await Document.get(doc_id)
            if doc:
                doc.status = DocumentStatus.COMPLETED.value
                await doc.save()
                
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
                doc = await Document.get(doc_id)
                if doc:
                    doc.status = DocumentStatus.ERROR.value
                    await doc.save()
                    
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
            # Return without quote to keep Korean readable (Fuseki supports UTF-8 IRIs)
            return clean
        
        rdf_lines = []
        namespace_entity = "http://rag.local/inst/"
        namespace_relation = "http://rag.local/rel/"
        
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
            
            # Note: Triple-chunk mappings are no longer stored in MongoDB.
            # source_node_id is stored directly in Neo4j/Fuseki and retrieved at query time.
            
            # 백엔드별 적재
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
            print(f"[Fallback] Graph ingestion complete for {kb_id}")


ingestion_service = IngestionService()

