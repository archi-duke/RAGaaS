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
import asyncio
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
    
    async def extract_graph(
        self,
        nodes: List[BaseNode],
        extractor_type: GraphExtractorType,
        config: Dict[str, Any],
        examples: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        entity_dictionary: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """Extract graph triples from nodes in parallel"""
        if extractor_type == GraphExtractorType.NONE:
            return []
        
        num_workers = config.get("num_workers", 5)
        sem = asyncio.Semaphore(num_workers)
        
        async def process_node(node, idx):
            async with sem:
                try:
                    text = node.get_content()
                    if len(text.strip()) < 10: return []
                    
                    # Dictionary injection
                    dictionary_text = ""
                    if entity_dictionary:
                        dict_lines = []
                        for canon, info in list(entity_dictionary.items())[:50]:
                            aliases = ", ".join(info.get("variants", []))
                            dict_lines.append(f"- {canon} (Aliases: {aliases})" if aliases else f"- {canon}")
                        if dict_lines:
                            dictionary_text = "\n[Global Entity Dictionary (Use these canonical names)]\n" + "\n".join(dict_lines) + "\n"

                    # Prompt building
                    # The examples are now directly embedded into the prompt string if provided
                    examples_prompt_part = f"\n[Reference Examples (Few-Shot)]\n{examples}\n" if examples else ""

                    if custom_prompt:
                        # Use safe replacement to avoid conflicts with JSON braces in prompt
                        prompt = custom_prompt.replace("{text}", text[:2000]).replace("{examples}", examples_prompt_part + dictionary_text)
                    else:
                        prompt = f"""Extract primary entities and their relationships from the following text.
Format: (Subject, Relation, Object)
Extract up to 5 triplets.
{examples_prompt_part}
{dictionary_text}
Text:
{text[:2000]}

Triplets (one per line, format: Subject|Relation|Object):"""
                    
                    if (idx + 1) % 5 == 0 or idx == 0:
                        print(f"[Pipeline] Processing chunk {idx+1}/{len(nodes)}...")
                        
                    response = await self.llm.acomplete(prompt)
                    response_text = response.text.strip()
                    
                    node_triples = []
                    parsed_json = self._try_parse_json(response_text)
                    if parsed_json:
                        for t in parsed_json.get("triples", []):
                            if all(k in t for k in ["subject", "predicate", "object"]):
                                node_triples.append({
                                    "subject": str(t["subject"]).strip(),
                                    "predicate": str(t["predicate"]).strip(),
                                    "object": str(t["object"]).strip(),
                                    "source_node_id": node.node_id,
                                    "confidence": t.get("confidence", 0.8),
                                })
                        # Also extract properties (entity attributes) as triples
                        properties = parsed_json.get("properties", [])
                        for prop in properties:
                            if all(k in prop for k in ["entity", "property", "value"]):
                                node_triples.append({
                                    "subject": str(prop["entity"]).strip(),
                                    "predicate": f"has_{prop['property']}",
                                    "object": str(prop["value"]).strip(),
                                    "source_node_id": node.node_id,
                                    "confidence": 0.9,
                                })
                    else:
                        for line in response_text.split('\n'):
                            line = line.strip()
                            if '|' in line:
                                parts = line.split('|')
                                if len(parts) >= 3:
                                    node_triples.append({
                                        "subject": parts[0].strip(),
                                        "predicate": parts[1].strip(),
                                        "object": parts[2].strip(),
                                        "source_node_id": node.node_id,
                                        "confidence": 0.7,
                                    })
                    return node_triples
                except Exception as e:
                    print(f"Error extracting from node {idx}: {e}")
                    import traceback
                    traceback.print_exc()
                    return []

        tasks = [process_node(node, i) for i, node in enumerate(nodes)]
        results = await asyncio.gather(*tasks)
        
        all_triples = []
        for r in results:
            all_triples.extend(r)
            
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
        entity_dictionary: Optional[Dict[str, Dict[str, Any]]] = None,
        sampling_size: Optional[int] = None, # User-defined sampling size
        kb_id: Optional[str] = None,  # ✅ 추가: 임시 파일 저장용
        doc_id: Optional[str] = None,  # ✅ 추가: 임시 파일 저장용
        job_id: Optional[str] = None, # For cancellation checks
        status_callback: Optional[any] = None # Async function(status: str)
    ) -> Dict[str, Any]:
        """Execute the entire ingestion process in Doc2Graph order with timing stats."""
        import time
        from app.api.ingest import jobs, JobStatus
        
        start_total = time.time()
        stats = []

        graph_config = graph_config or {}
        
        # 0. Text Cleaning
        t0 = time.time()
        if enable_text_cleaning:
            from app.core.text_cleaner import text_cleaner
            text = text_cleaner.clean(text)
        stats.append({"step": "Step 0: Text Cleaning", "duration": round(time.time() - t0, 2)})
        
        # PHASE 1: Entity Extraction (Global Dictionary)
        t1 = time.time()
        if enable_entity_normalization and not entity_dictionary:
            if job_id and jobs.get(job_id, {}).get("status") == JobStatus.CANCELLED: return {}
            
            if status_callback:
                await status_callback("EXTRACTING_ENTITIES")
                
            print(f"[Pipeline] Phase 1: Building Global Entity Dictionary...")
            from app.core.dictionary_builder import DictionaryBuilder
            dict_builder = DictionaryBuilder(self.llm)
            effective_sampling_size = sampling_size if sampling_size else 10000
            entity_dictionary = await dict_builder.build_from_text(text, sampling_size=effective_sampling_size)
            
            # ✅ 엔티티 추출 완료 상태 전송
            if status_callback:
                await status_callback("ENTITY_EXTRACTED")
            
            # ✅ 임시 파일 저장: 엔티티 사전
            if kb_id and doc_id and entity_dictionary:
                from app.utils.temp_storage import temp_storage
                await temp_storage.save_entity_dictionary(kb_id, doc_id, entity_dictionary)
        stats.append({"step": "Step 1: Entity Extraction (Pre-pass)", "duration": round(time.time() - t1, 2)})
        
        # PHASE 2: Chunking (Triple-level)
        t2 = time.time()
        if job_id and jobs.get(job_id, {}).get("status") == JobStatus.CANCELLED: return {}
        print(f"[Pipeline] Phase 2: Chunking document for Triple Extraction...")
        nodes = self.chunk_document(text, chunking_strategy, chunking_config)
        stats.append({"step": f"Step 2: Text Chunking ({len(nodes)} chunks)", "duration": round(time.time() - t2, 2)})

        # PHASE 3: Triple Extraction & Embeddings
        t3 = time.time()
        if job_id and jobs.get(job_id, {}).get("status") == JobStatus.CANCELLED: return {}
        print(f"[Pipeline] Phase 3: Generating embeddings...")
        embeddings = []
        for i, node in enumerate(nodes):
            embedding = await self.embed_model.aget_text_embedding(node.get_content())
            embeddings.append(embedding)
        
        triples = []
        normalization_suggestions = None
        if graph_extractor_type != GraphExtractorType.NONE:
            if status_callback:
                await status_callback("EXTRACTING_TRIPLES")
                
            print(f"[Pipeline] Phase 3: Extracting graph triples in parallel...")
            triples = await self.extract_graph(
                nodes, 
                graph_extractor_type, 
                graph_config, 
                extraction_examples_yaml, 
                custom_prompt,
                entity_dictionary=entity_dictionary 
            )
            
            # ✅ 트리플 추출 완료 상태 전송
            if status_callback:
                await status_callback("TRIPLE_EXTRACTED")
            
            # ✅ 임시 파일 저장: 트리플
            if kb_id and doc_id and triples:
                from app.utils.temp_storage import temp_storage
                await temp_storage.save_triples(kb_id, doc_id, triples)
        
        # ✅ 임시 파일 저장: 청크 (트리플 추출 여부와 관계없이 항상 저장)
        if kb_id and doc_id and nodes:
            from app.utils.temp_storage import temp_storage
            chunks_data = [{
                "content": node.get_content(), 
                "metadata": node.metadata,
                "node_id": node.node_id
            } for node in nodes]
            await temp_storage.save_chunks(kb_id, doc_id, chunks_data)
        stats.append({"step": f"Step 3: Triple Extraction ({len(triples)} triples)", "duration": round(time.time() - t3, 2)})
            
        # PHASE 4: Post-normalization
        t4 = time.time()
        if enable_entity_normalization and len(triples) > 0:
            if job_id and jobs.get(job_id, {}).get("status") == JobStatus.CANCELLED: return {}
            from app.core.entity_normalizer import entity_normalizer
            print(f"[Pipeline] Phase 4: Running final entity normalization...")
            
            normalization_suggestions = await entity_normalizer.generate_normalization_suggestions(
                triples, 
                algorithm=normalization_algorithm,
                threshold=normalization_threshold,
                embed_model=self.embed_model,
                llm=self.llm
            )
            
            if normalization_suggestions:
                triples = entity_normalizer.apply_all_normalizations(triples, normalization_suggestions)
            
            triples = entity_normalizer.normalize_triples(triples)
            triples = entity_normalizer.resolve_duplicates(triples)
        stats.append({"step": "Step 4: Entity Normalization", "duration": round(time.time() - t4, 2)})

        total_duration = round(time.time() - start_total, 2)
        stats.append({"step": "Total Execution Time", "duration": total_duration})
        
        return {
            "nodes": nodes,
            "embeddings": embeddings,
            "triples": triples,
            "entity_dictionary": entity_dictionary,
            "node_count": len(nodes),
            "triple_count": len(triples),
            "normalization_suggestions": normalization_suggestions,
            "stats": stats
        }




# Singleton instance
ingest_pipeline = IngestPipeline()
