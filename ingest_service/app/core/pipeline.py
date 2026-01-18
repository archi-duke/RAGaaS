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
        """노드에서 그래프 트리플 추출"""
        
        extractor = self.get_graph_extractor(extractor_type, config)
        
        if extractor is None:
            return []
        
        # Extract paths from nodes
        all_triples = []
        
        for node in nodes:
            try:
                # SimpleLLMPathExtractor와 다른 추출기들은 
                # extract() 또는 __call__() 메서드를 통해 추출
                # 실제 구현 시 PropertyGraphIndex를 사용하는 것이 더 적합
                extracted = extractor.extract([node])
                
                for path in extracted:
                    # path는 (entity1, relation, entity2) 형태
                    if hasattr(path, 'subj') and hasattr(path, 'obj'):
                        triple = {
                            "subject": str(path.subj),
                            "predicate": str(path.rel),
                            "object": str(path.obj),
                            "source_node_id": node.node_id,
                        }
                        all_triples.append(triple)
            except Exception as e:
                print(f"Error extracting from node {node.node_id}: {e}")
                continue
        
        return all_triples
    
    async def process(
        self,
        text: str,
        chunking_strategy: ChunkingStrategy,
        chunking_config: Dict[str, Any],
        graph_extractor_type: GraphExtractorType = GraphExtractorType.NONE,
        graph_config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """전체 인제스션 프로세스 실행"""
        
        graph_config = graph_config or {}
        
        # 1. Chunk document
        nodes = self.chunk_document(text, chunking_strategy, chunking_config)
        
        # 2. Generate embeddings
        embeddings = []
        for node in nodes:
            embedding = await self.embed_model.aget_text_embedding(node.get_content())
            embeddings.append(embedding)
        
        # 3. Extract graph (if enabled)
        triples = []
        if graph_extractor_type != GraphExtractorType.NONE:
            triples = self.extract_graph(nodes, graph_extractor_type, graph_config)
        
        return {
            "nodes": nodes,
            "embeddings": embeddings,
            "triples": triples,
            "node_count": len(nodes),
            "triple_count": len(triples),
        }


# Singleton instance
ingest_pipeline = IngestPipeline()
