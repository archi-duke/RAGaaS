"""
LlamaIndex Pipeline - Chunking and Graph Extraction

지원하는 청킹 전략:
- fixed_size: SentenceSplitter (기본)
- sliding_window: SentenceWindowNodeParser
- hierarchical: HierarchicalNodeParser
- semantic: SemanticSplitterNodeParser
- markdown: MarkdownNodeParser

지원하는 그래프 추출기:
- simple: SimpleLLMPathExtractor
- dynamic: DynamicLLMPathExtractor
- schema: SchemaLLMPathExtractor
"""
from typing import List, Dict, Any, Optional, Literal
from enum import Enum

from llama_index.core import Document, Settings as LlamaSettings
from llama_index.core.node_parser import (
    SentenceSplitter,
    SentenceWindowNodeParser,
    HierarchicalNodeParser,
    SemanticSplitterNodeParser,
    MarkdownNodeParser,
)
from llama_index.core.indices.property_graph import (
    SimpleLLMPathExtractor,
    DynamicLLMPathExtractor,
    SchemaLLMPathExtractor,
    ImplicitPathExtractor,
)
from llama_index.core.schema import BaseNode
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI

from app.core.config import settings


class ChunkingStrategy(str, Enum):
    FIXED_SIZE = "fixed_size"
    SLIDING_WINDOW = "sliding_window"
    HIERARCHICAL = "hierarchical"
    SEMANTIC = "semantic"
    MARKDOWN = "markdown"
    HYBRID = "hybrid"


class GraphExtractorType(str, Enum):
    SIMPLE = "simple"
    DYNAMIC = "dynamic"
    SCHEMA = "schema"
    NONE = "none"


class IngestPipeline:
    """LlamaIndex 기반 인제스션 파이프라인"""
    
    def __init__(self):
        # Initialize LLM and Embedding
        self.llm = OpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY
        )
        self.embed_model = OpenAIEmbedding(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.OPENAI_API_KEY
        )
        
        # Set global settings
        LlamaSettings.llm = self.llm
        LlamaSettings.embed_model = self.embed_model
    
    def get_node_parser(
        self,
        strategy: ChunkingStrategy,
        config: Dict[str, Any]
    ):
        """청킹 전략에 따른 Node Parser 반환"""
        
        if strategy == ChunkingStrategy.FIXED_SIZE:
            return SentenceSplitter(
                chunk_size=config.get("chunk_size", 1024),
                chunk_overlap=config.get("chunk_overlap", 20),
            )
        
        elif strategy == ChunkingStrategy.SLIDING_WINDOW:
            return SentenceWindowNodeParser.from_defaults(
                window_size=config.get("window_size", 3),
                window_metadata_key="window",
                original_text_metadata_key="original_sentence",
            )
        
        elif strategy == ChunkingStrategy.HIERARCHICAL:
            chunk_sizes = config.get("chunk_sizes", [2048, 512, 128])
            return HierarchicalNodeParser.from_defaults(
                chunk_sizes=chunk_sizes
            )
        
        elif strategy == ChunkingStrategy.SEMANTIC:
            return SemanticSplitterNodeParser(
                buffer_size=config.get("buffer_size", 1),
                breakpoint_percentile_threshold=config.get("breakpoint_threshold", 95),
                embed_model=self.embed_model,
            )
        
        elif strategy == ChunkingStrategy.MARKDOWN:
            return MarkdownNodeParser()
        
        elif strategy == ChunkingStrategy.HYBRID:
            # Hybrid: Markdown first, then SentenceSplitter for large chunks
            # 실제 구현 시 복합 파이프라인 필요
            return SentenceSplitter(
                chunk_size=config.get("chunk_size", 1024),
                chunk_overlap=config.get("chunk_overlap", 20),
            )
        
        else:
            # Default to SentenceSplitter
            return SentenceSplitter(chunk_size=1024, chunk_overlap=20)
    
    def get_graph_extractor(
        self,
        extractor_type: GraphExtractorType,
        config: Dict[str, Any]
    ):
        """그래프 추출기 타입에 따른 Extractor 반환"""
        
        if extractor_type == GraphExtractorType.NONE:
            return None
        
        elif extractor_type == GraphExtractorType.SIMPLE:
            return SimpleLLMPathExtractor(
                llm=self.llm,
                max_paths_per_chunk=config.get("max_paths_per_chunk", 10),
                num_workers=config.get("num_workers", 4),
            )
        
        elif extractor_type == GraphExtractorType.DYNAMIC:
            allowed_entity_types = config.get("allowed_entity_types", None)
            allowed_relation_types = config.get("allowed_relation_types", None)
            
            return DynamicLLMPathExtractor(
                llm=self.llm,
                max_triplets_per_chunk=config.get("max_triplets_per_chunk", 20),
                num_workers=config.get("num_workers", 4),
                allowed_entity_types=allowed_entity_types,
                allowed_relation_types=allowed_relation_types,
            )
        
        elif extractor_type == GraphExtractorType.SCHEMA:
            # Schema-based extraction requires predefined schema
            entities = config.get("possible_entities", ["PERSON", "ORGANIZATION", "LOCATION"])
            relations = config.get("possible_relations", ["WORKS_FOR", "LOCATED_IN", "KNOWS"])
            schema = config.get("kg_validation_schema", None)
            
            return SchemaLLMPathExtractor(
                llm=self.llm,
                possible_entities=entities,
                possible_relations=relations,
                kg_validation_schema=schema,
                strict=config.get("strict", False),
                num_workers=config.get("num_workers", 4),
                max_triplets_per_chunk=config.get("max_triplets_per_chunk", 10),
            )
        
        return None
    
    def chunk_document(
        self,
        text: str,
        strategy: ChunkingStrategy,
        config: Dict[str, Any]
    ) -> List[BaseNode]:
        """문서를 청킹하여 노드 리스트 반환"""
        
        # Create Document
        document = Document(text=text)
        
        # Get appropriate parser
        parser = self.get_node_parser(strategy, config)
        
        # Parse into nodes
        nodes = parser.get_nodes_from_documents([document])
        
        return nodes
    
    def extract_graph(
        self,
        nodes: List[BaseNode],
        extractor_type: GraphExtractorType,
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """노드에서 그래프 트리플 추출
        
        Note: LlamaIndex의 Path Extractor들은 PropertyGraphIndex와 함께 사용되도록 설계됨.
        여기서는 직접 LLM을 호출하여 트리플을 추출하는 간소화된 방식 사용.
        """
        
        if extractor_type == GraphExtractorType.NONE:
            return []
        
        all_triples = []
        
        # 간소화된 LLM 기반 트리플 추출
        for node in nodes:
            try:
                text = node.get_content()
                if len(text.strip()) < 50:  # 너무 짧은 텍스트는 스킵
                    continue
                
                # 간단한 프롬프트 기반 추출
                prompt = f"""다음 텍스트에서 주요 엔티티와 관계를 추출하세요.
형식: (주체, 관계, 객체)
최대 5개까지 추출하세요.

텍스트:
{text[:2000]}

트리플 (한 줄에 하나씩, 형식: 주체|관계|객체):"""
                
                response = self.llm.complete(prompt)
                response_text = response.text.strip()
                
                # 응답 파싱
                for line in response_text.split('\n'):
                    line = line.strip()
                    if '|' in line:
                        parts = line.split('|')
                        if len(parts) >= 3:
                            triple = {
                                "subject": parts[0].strip(),
                                "predicate": parts[1].strip(),
                                "object": parts[2].strip(),
                                "source_node_id": node.node_id,
                            }
                            all_triples.append(triple)
                            
            except Exception as e:
                print(f"Error extracting from node {node.node_id}: {e}")
                continue
            
            if len(all_triples) > 0 and len(all_triples) % 5 == 0:
                print(f"[Pipeline] Extraction progress: {len(all_triples)} triples extracted so far...")

        
        return all_triples

    
    async def process(
        self,
        text: str,
        chunking_strategy: ChunkingStrategy,
        chunking_config: Dict[str, Any],
        graph_extractor_type: GraphExtractorType = GraphExtractorType.NONE,
        graph_config: Dict[str, Any] = None,
        enable_text_cleaning: bool = False,
    ) -> Dict[str, Any]:
        """전체 인제스션 프로세스 실행"""
        
        graph_config = graph_config or {}
        
        # 0. Text Cleaning (청크 가공 전 정제)
        if enable_text_cleaning:
            from app.core.text_cleaner import text_cleaner
            original_len = len(text)
            text = text_cleaner.clean(text)
            print(f"[Pipeline] Text cleaned: {original_len} -> {len(text)} chars")
        
        # 1. Chunk document
        print(f"[Pipeline] Chunking document ({len(text)} chars)...")
        nodes = self.chunk_document(text, chunking_strategy, chunking_config)
        print(f"[Pipeline] Created {len(nodes)} nodes.")

        
        # 2. Generate embeddings
        print(f"[Pipeline] Generating embeddings for {len(nodes)} nodes...")
        embeddings = []
        for i, node in enumerate(nodes):
            embedding = await self.embed_model.aget_text_embedding(node.get_content())
            embeddings.append(embedding)
            if (i + 1) % 5 == 0:
                print(f"[Pipeline] Embedded {i+1}/{len(nodes)} nodes...")
        
        # 3. Extract graph (if enabled)
        triples = []
        if graph_extractor_type != GraphExtractorType.NONE:
            print(f"[Pipeline] Extracting graph using {graph_extractor_type}...")
            triples = self.extract_graph(nodes, graph_extractor_type, graph_config)
            print(f"[Pipeline] Extracted {len(triples)} triples.")
            
            # 4. Entity Normalization (적재 직전)
            if graph_config.get("enable_entity_normalization", True):
                from app.core.entity_normalizer import entity_normalizer
                original_count = len(triples)
                triples = entity_normalizer.normalize_triples(triples)
                triples = entity_normalizer.resolve_duplicates(triples)
                print(f"[Pipeline] Entity normalized: {original_count} -> {len(triples)} triples")
        
        return {
            "nodes": nodes,
            "embeddings": embeddings,
            "triples": triples,
            "node_count": len(nodes),
            "triple_count": len(triples),
        }




# Singleton instance
ingest_pipeline = IngestPipeline()
