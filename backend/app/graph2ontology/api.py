"""Python SDK API"""

from pathlib import Path
from typing import Union, Optional,  Optional, Union
import uuid

from app.graph2ontology.config import load_config, Config
from app.graph2ontology.chunkers import OEChunker, RAGChunker
from app.graph2ontology.extractors import LLMStubExtractor
from app.graph2ontology.builders import TriGBuilder, ChunksBuilder, EntityRegistryBuilder
from app.graph2ontology.loaders import FusekiLoader, MilvusLoader
from app.graph2ontology.qa import QAReporter
from app.graph2ontology.models.chunk import OEChunk, RAGChunk
from app.graph2ontology.models.candidate import CandidateExtractionResult
import json


class Doc2OntoClient:
    """Doc2Onto Python SDK 클라이언트
    
    다른 서비스에서 직접 import하여 사용
    
    Example:
        from app.graph2ontology.api import Doc2OntoClient
        
        client = Doc2OntoClient(config_path="./config.yml")
        result = client.build(input_dir="./docs", output_dir="./out")
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        config: Optional[Config] = None,
    ):
        """
        Args:
            config_path: 설정 파일 경로
            config: Config 객체 (config_path보다 우선)
        """
        if config:
            self.config = config
        elif config_path:
            self.config = load_config(config_path)
        else:
            self.config = Config()
        
        # 청커 초기화
        self._oe_chunker = OEChunker(
            chunk_size=self.config.chunking.oe_chunk_size,
            chunk_overlap=self.config.chunking.oe_chunk_overlap,
            section_aware=self.config.chunking.oe_section_aware,
        )
        self._rag_chunker = RAGChunker(
            chunk_size=self.config.chunking.rag_chunk_size,
            chunk_overlap=self.config.chunking.rag_chunk_overlap,
        )
        
        # 추출기 초기화
        self._extractor = LLMStubExtractor(
            confidence_threshold=self.config.extraction.confidence_threshold,
            llm_endpoint=self.config.extraction.llm_endpoint,
            llm_model=self.config.extraction.llm_model,
        )
    
    def chunk_document(
        self,
        file_path: str,
        doc_id: Optional[str] = None,
        doc_ver: str = "v1",
    ) -> dict:
        """문서 청킹
        
        Args:
            file_path: 문서 파일 경로
            doc_id: 문서 ID (기본: 파일명)
            doc_ver: 문서 버전
            
        Returns:
            {"oe_chunks": [...], "rag_chunks": [...]}
        """
        file_path = Path(file_path)
        doc_id = doc_id or file_path.stem
        
        # OE-Chunking
        oe_chunks = list(self._oe_chunker.chunk_file(file_path, doc_id, doc_ver))
        
        # RAG-Chunking
        rag_chunks = []
        for oe_chunk in oe_chunks:
            for rag_chunk in self._rag_chunker.chunk_text(
                oe_chunk.text,
                doc_id,
                doc_ver,
                source_oe_chunk_idx=oe_chunk.chunk_idx,
                base_offset=oe_chunk.start_offset or 0,
                section_path=oe_chunk.section_path,
            ):
                rag_chunks.append(rag_chunk)
        
        return {
            "oe_chunks": oe_chunks,
            "rag_chunks": rag_chunks,
        }
    
    def extract_candidates(
        self,
        oe_chunks: list[OEChunk],
        run_id: Optional[str] = None,
        filter_by_confidence: bool = True,
    ) -> list[CandidateExtractionResult]:
        """온톨로지 후보 추출
        
        Args:
            oe_chunks: OE-Chunk 리스트
            run_id: 실행 ID
            filter_by_confidence: confidence 필터링 적용 여부
            
        Returns:
            추출 결과 리스트
        """
        run_id = run_id or str(uuid.uuid4())[:8]
        results = []
        
        for chunk in oe_chunks:
            result = self._extractor.extract(chunk, run_id)
            if filter_by_confidence:
                result = self._extractor.filter_by_confidence(result)
            results.append(result)
        
        return results
    
    def build_trig(
        self,
        candidates: list[CandidateExtractionResult],
        rag_chunks: Optional[list[RAGChunk]] = None,
        run_id: Optional[str] = None,
    ) -> dict:
        """TriG 데이터 생성
        
        Args:
            candidates: 추출 결과 리스트
            rag_chunks: RAG-Chunk 리스트 (Evidence 연결용)
            run_id: 실행 ID
            
        Returns:
            {"base_trig": str, "evidence_trig": str}
        """
        run_id = run_id or str(uuid.uuid4())[:8]
        
        builder = TriGBuilder(
            base_uri=self.config.ontology.base_uri,
            base_graph_uri=self.config.ontology.base_graph_uri,
            evidence_graph_prefix=self.config.ontology.evidence_graph_prefix,
        )
        
        for result in candidates:
            builder.build_from_candidates(result)
            
            # Evidence 추가
            if rag_chunks:
                for triple in result.triples:
                    # source_chunk_id로 매칭되는 청크 찾기
                    matching = [c for c in rag_chunks if c.chunk_id == triple.source_chunk_id]
                    if matching:
                        builder.add_evidence_triple(triple, matching[0], run_id)
        
        return {
            "base_graph": builder.base_graph,
            "evidence_graphs": builder.evidence_graphs,
        }
    
    def build(
        self,
        input_dir: str,
        output_dir: str,
        dry_run: bool = False,
        run_id: Optional[str] = None,
        external_chunks: Optional[str] = None,
    ) -> dict:
        """전체 파이프라인 실행
        
        Args:
            input_dir: 입력 문서 디렉토리
            output_dir: 출력 디렉토리
            dry_run: 외부 서비스 없이 파일만 생성
            run_id: 실행 ID
            
        Returns:
            실행 결과 요약
        """
        run_id = run_id or str(uuid.uuid4())[:8]
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 빌더 초기화
        trig_builder = TriGBuilder(
            base_uri=self.config.ontology.base_uri,
            base_graph_uri=self.config.ontology.base_graph_uri,
            evidence_graph_prefix=self.config.ontology.evidence_graph_prefix,
        )
        chunks_builder = ChunksBuilder()
        registry_builder = EntityRegistryBuilder(base_uri=self.config.ontology.base_uri)
        qa_reporter = QAReporter(run_id=run_id)
        
        all_candidates = []
        doc_files = list(input_path.glob("*.txt"))
        
        for doc_file in doc_files:
            doc_id = doc_file.stem
            
            # 청킹
            chunk_result = self.chunk_document(str(doc_file), doc_id)
            oe_chunks = chunk_result["oe_chunks"]
            
            rag_chunks = []
            external_chunk_map = {} # (start, end) -> chunk_id

            if external_chunks:
                # 외부 청크 로드
                with open(external_chunks, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        c_data = json.loads(line)
                        if c_data.get("doc_id") == doc_id:
                            rag_chunk = RAGChunk(
                                chunk_id=c_data.get("chunk_id", ""),
                                doc_id=c_data.get("doc_id", ""),
                                doc_ver=c_data.get("doc_ver", "v1"),
                                text=c_data.get("text", ""),
                                chunk_idx=c_data.get("chunk_idx", 0),
                                start_offset=c_data.get("start_offset"),
                                end_offset=c_data.get("end_offset"),
                                section_path=c_data.get("section_path"),
                                chunk_hash=c_data.get("chunk_hash", ""),
                            )
                            rag_chunks.append(rag_chunk)
                            if rag_chunk.start_offset is not None and rag_chunk.end_offset is not None:
                                external_chunk_map[(rag_chunk.start_offset, rag_chunk.end_offset)] = rag_chunk.chunk_id
            else:
                 # Default generic RAG chunking
                 rag_chunks = chunk_result["rag_chunks"]
            
            chunks_builder.chunks.extend(rag_chunks)
            
            # 후보 추출
            candidates = self.extract_candidates(oe_chunks, run_id)
            all_candidates.extend(candidates)
            
            for result in candidates:
                trig_builder.build_from_candidates(result)
                registry_builder.register_from_candidates(result)
                
                for triple in result.triples:
                    try:
                        if external_chunks and external_chunk_map:
                             # 외부 청크: OE-Chunk offset 범위 내에 있는 RAG Chunk 찾기
                             oe_start = triple.source_chunk_id # Wait, triple has source_chunk_id which is OEChunk ID.
                             # Need to find OEChunk object first or parse ID?
                             # Actually we are iterating candidates result which came from 'oe_chunks' loop.
                             # But 'triples' loop here iterates ALL candidates from ALL chunks? NO.
                             # The loop 'for result in candidates:' iterates per OE chunk result.
                             # So 'result.triples' are from THAT oe_chunk.
                             pass
                        
                        # Fix: The original logic below assumed rag_chunks have 'source_oe_chunk_idx'.
                        # With external chunks, they don't have it. We must match by offset.
                        
                        # Find source OE Chunk for this result
                        # We can trust 'result' corresponds to one of 'oe_chunks'.
                        
                        # Let's find matches
                        matching = []
                        if external_chunks:
                            # For external chunks without offsets, use text-based matching
                            # Find RAG chunks that contain the triple's source text or entities
                            triple_entities = [triple.subject, triple.object]
                            
                            for rag_chunk in rag_chunks:
                                # Check if any entity from the triple appears in this chunk
                                chunk_text_lower = rag_chunk.text.lower() if rag_chunk.text else ""
                                for entity in triple_entities:
                                    if entity and entity.lower() in chunk_text_lower:
                                        matching.append(rag_chunk)
                                        break  # Found a match, move to next chunk
                            
                            # If no text matches, fallback to using all chunks (less precise)
                            if not matching:
                                matching = rag_chunks[:3]  # Use first 3 chunks as evidence
                        else:
                            # Native chunks - use source_oe_chunk_idx
                            try:
                                oe_idx = int(triple.source_chunk_id.split("|")[-1])
                                matching = [
                                    c for c in rag_chunks 
                                    if c.source_oe_chunk_idx == oe_idx
                                ]
                            except (ValueError, IndexError):
                                matching = []

                        if matching:
                            for match in matching[:3]:  # Limit to 3 evidence chunks per triple
                                trig_builder.add_evidence_triple(triple, match, run_id)
                    except (ValueError, IndexError):
                        pass
            
            # QA 통계
            oe_avg = sum(len(c.text) for c in oe_chunks) / len(oe_chunks) if oe_chunks else 0
            rag_avg = sum(len(c.text) for c in rag_chunks) / len(rag_chunks) if rag_chunks else 0
            qa_reporter.add_document_stats(doc_id, len(oe_chunks), len(rag_chunks), oe_avg, rag_avg)
        
        # 저장
        trig_builder.serialize_base(output_path / "base.trig")
        trig_builder.serialize_evidence(output_path / "evidence.trig")
        chunks_count = chunks_builder.serialize(output_path / "chunks.jsonl")
        registry_builder.serialize(output_path / "entity_registry.json")
        
        # candidates 저장
        with open(output_path / "candidates_filtered.jsonl", "w", encoding="utf-8") as f:
            for r in all_candidates:
                f.write(r.model_dump_json() + "\n")
        
        qa_reporter.add_extraction_stats(
            sum(r.total_candidates for r in all_candidates),
            sum(r.total_candidates for r in all_candidates),
            triples=sum(r.total_triples for r in all_candidates),
        )
        qa_reporter.add_entity_stats(registry_builder.registry.total_entities)
        qa_reporter.save(output_path / "qa_report.md")
        
        return {
            "run_id": run_id,
            "documents": len(doc_files),
            "chunks": chunks_count,
            "triples": sum(r.total_triples for r in all_candidates),
            "entities": registry_builder.registry.total_entities,
            "output_dir": str(output_path),
        }
    
    def load_to_fuseki(
        self,
        trig_path: str,
        endpoint: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict:
        """Fuseki에 TriG 업로드
        
        Args:
            trig_path: TriG 파일 경로
            endpoint: Fuseki 엔드포인트 (기본: config에서)
            dry_run: 실제 업로드 없이 확인만
        """
        endpoint = endpoint or self.config.storage.fuseki_endpoint
        loader = FusekiLoader(
            endpoint=endpoint,
            dataset=self.config.storage.fuseki_dataset,
        )
        return loader.upload(trig_path, dry_run=dry_run)
    
    def load_to_milvus(
        self,
        chunks_path: str,
        embedding_fn=None,
        dry_run: bool = False,
    ) -> dict:
        """Milvus에 청크 적재
        
        Args:
            chunks_path: chunks.jsonl 파일 경로
            embedding_fn: 임베딩 함수
            dry_run: 실제 적재 없이 확인만
        """
        loader = MilvusLoader(
            host=self.config.storage.milvus_host,
            port=self.config.storage.milvus_port,
            collection=self.config.storage.milvus_collection,
        )
        return loader.load(chunks_path, embedding_fn=embedding_fn, dry_run=dry_run)
