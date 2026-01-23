"""
LlamaIndex Pipeline - Chunking and Graph Extraction

Supported Chunking Strategies:
- fixed_size: SentenceSplitter (Default)
- sliding_window: SentenceWindowNodeParser
- hierarchical: HierarchicalNodeParser
- semantic: SemanticSplitterNodeParser
- markdown: MarkdownNodeParser

Supported Graph Extractors:
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
    """LlamaIndex-based Ingestion Pipeline"""
    
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
        """Return Node Parser based on chunking strategy"""
        
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
            # Complex pipeline needed for actual implementation
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
        """Return Extractor based on graph extractor type"""
        
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
        """Chunk documents and return list of nodes"""
        
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
        config: Dict[str, Any],
        examples: Optional[str] = None,
        custom_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Extract graph triples from nodes

        Supports both legacy pipe-delimited format and modern JSON format.
        JSON format allows richer extraction (entity types, properties, etc.)
        """
        
        if extractor_type == GraphExtractorType.NONE:
            return []
        
        all_triples = []
        
        # Simplified LLM-based triple extraction
        for node in nodes:
            try:
                text = node.get_content()
                if len(text.strip()) < 10:  # Skip too short text
                    continue
                
                # Prepare examples
                examples_text = ""
                if examples:
                    print(f"[Pipeline] Using Few-Shot Examples ({len(examples)} chars):\n{examples[:100]}...")
                    examples_text = f"\n[Reference Examples (Few-Shot)]\n{examples}\n"

                # Use custom prompt or default prompt
                if custom_prompt:
                    print(f"[Pipeline DEBUG] Custom prompt length: {len(custom_prompt)}. Using .replace() method.")
                    # Use safe replacement to avoid conflicts with JSON braces in prompt
                    prompt = custom_prompt.replace("{text}", text[:2000]).replace("{examples}", examples_text)
                else:
                    prompt = f"""Extract primary entities and their relationships from the following text.
Format: (Subject, Relation, Object)
Extract up to 5 triplets.
{examples_text}
Text:
{text[:2000]}

Triplets (one per line, format: Subject|Relation|Object):"""
                
                response = self.llm.complete(prompt)
                response_text = response.text.strip()
                
                # Try JSON parsing first (modern format)
                parsed_json = self._try_parse_json(response_text)
                if parsed_json:
                    # Extract triples from JSON
                    triples = parsed_json.get("triples", [])
                    for t in triples:
                        if all(k in t for k in ["subject", "predicate", "object"]):
                            triple = {
                                "subject": str(t["subject"]).strip(),
                                "predicate": str(t["predicate"]).strip(),
                                "object": str(t["object"]).strip(),
                                "source_node_id": node.node_id,
                                "confidence": t.get("confidence", 0.8),
                            }
                            all_triples.append(triple)
                    
                    # Also extract properties (entity attributes) as triples
                    properties = parsed_json.get("properties", [])
                    for prop in properties:
                        if all(k in prop for k in ["entity", "property", "value"]):
                            triple = {
                                "subject": str(prop["entity"]).strip(),
                                "predicate": f"has_{prop['property']}",
                                "object": str(prop["value"]).strip(),
                                "source_node_id": node.node_id,
                                "confidence": 0.9,
                            }
                            all_triples.append(triple)
                else:
                    # Fallback: Legacy pipe-delimited format
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
                                    "confidence": 0.7,
                                }
                                all_triples.append(triple)
                            
            except Exception as e:
                print(f"Error extracting from node {node.node_id}: {e}")
                import traceback
                traceback.print_exc()
                continue
            
            if len(all_triples) > 0 and len(all_triples) % 5 == 0:
                print(f"[Pipeline] Extraction progress: {len(all_triples)} triples extracted so far...")

        
        return all_triples

    def _try_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to parse JSON from LLM response, handling code blocks"""
        import json
        import re
        
        # Remove markdown code blocks if present
        json_pattern = r'```json\s*(.*?)\s*```'
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            text = match.group(1)
        elif '```' in text:
            # Generic code block
            parts = text.split('```')
            if len(parts) >= 2:
                text = parts[1]
        
        # Try parsing
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            # Not JSON format
            return None

    
    async def process(
        self,
        text: str,
        chunking_strategy: ChunkingStrategy,
        chunking_config: Dict[str, Any],
        graph_extractor_type: GraphExtractorType = GraphExtractorType.NONE,
        graph_config: Dict[str, Any] = None,
        enable_text_cleaning: bool = False,
        extraction_examples_yaml: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        enable_entity_normalization: bool = False,
        normalization_algorithm: str = "embedding",
        normalization_threshold: float = 0.85,
    ) -> Dict[str, Any]:
        """Execute the entire ingestion process"""
        
        graph_config = graph_config or {}
        
        # 0. Text Cleaning (Pre-chunking)
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
        normalization_suggestions = None
        if graph_extractor_type != GraphExtractorType.NONE:
            print(f"[Pipeline] Extracting graph using {graph_extractor_type}...")
            triples = self.extract_graph(nodes, graph_extractor_type, graph_config, extraction_examples_yaml, custom_prompt)
            print(f"[Pipeline] Extracted {len(triples)} triples.")
            
            # 4. Entity Normalization (Pre-loading)
            if enable_entity_normalization and len(triples) > 0:
                from app.core.entity_normalizer import entity_normalizer
                original_count = len(triples)
                
                print(f"[Pipeline] Running entity normalization with {normalization_algorithm} algorithm (threshold={normalization_threshold})...")
                
                # 유사 엔티티 찾기 및 제안 생성
                normalization_suggestions = await entity_normalizer.generate_normalization_suggestions(
                    triples, 
                    algorithm=normalization_algorithm,
                    threshold=normalization_threshold,
                    embed_model=self.embed_model,  # 임베딩 모델 전달
                    llm=self.llm  # LLM 모델 전달
                )
                
                print(f"[Pipeline] Found {len(normalization_suggestions)} entity groups to normalize")
                
                # [FIX] 제안된 통합을 실제로 트리플에 적용 (자동 적용)
                if normalization_suggestions:
                    original_triples_count = len(triples)
                    triples = entity_normalizer.apply_all_normalizations(triples, normalization_suggestions)
                    print(f"[Pipeline] Applied similarity-based normalization to {len(triples)} triples")
                
                # 기본 정규화는 항상 적용 (중복 제거 등)
                triples = entity_normalizer.normalize_triples(triples)
                triples = entity_normalizer.resolve_duplicates(triples)
                print(f"[Pipeline] After basic normalization: {original_count} -> {len(triples)} triples")
        
        return {
            "nodes": nodes,
            "embeddings": embeddings,
            "triples": triples,
            "node_count": len(nodes),
            "triple_count": len(triples),
            "normalization_suggestions": normalization_suggestions,
        }




# Singleton instance
ingest_pipeline = IngestPipeline()
