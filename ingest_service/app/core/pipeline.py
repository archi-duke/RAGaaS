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
    NodeParser,
    SentenceSplitter,
    SentenceWindowNodeParser,
    HierarchicalNodeParser,
    SemanticSplitterNodeParser,
)
from llama_index.core.indices.property_graph import (
    SimpleLLMPathExtractor,
    DynamicLLMPathExtractor,
    SchemaLLMPathExtractor,
    ImplicitPathExtractor,
)
from llama_index.core.schema import BaseNode, TextNode
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from pydantic import Field
from typing import Sequence

from app.core.config import settings


class ContextAwareNodeParser(NodeParser):
    """LLM-based context-aware chunking using sliding window approach
    
    Strategy:
    - target_size: Recommended chunk size (not a hard limit)
    - max_chunk_size: Absolute maximum to prevent oversized chunks
    - Semantic boundaries are prioritized over strict size limits
    - A complete semantic unit (paragraph, section) can exceed target_size
    """
    
    llm: Any = Field(default=None, description="LLM instance for context analysis")
    target_size: int = Field(default=800, description="Target chunk size (recommended, not strict)")
    llm_auto_size: bool = Field(default=False, description="Let LLM decide size automatically")
    window_size: int = Field(default=1200, description="Size of analysis window")
    overlap: int = Field(default=300, description="Overlap between windows")
    max_chunk_size: int = Field(default=None, description="Maximum chunk size (default: target_size * 2)")
        
    def get_nodes_from_documents(self, documents: List[Document]) -> List[BaseNode]:
        """Parse documents into nodes using LLM-based context detection"""
        all_nodes = []
        
        for doc in documents:
            text = doc.get_content()
            metadata = doc.metadata
            
            # Split text using LLM sliding window
            chunks = self._llm_split_text(text)
            
            # Create nodes from chunks with accurate position tracking
            current_search_pos = 0
            
            for i, chunk_text in enumerate(chunks):
                if not chunk_text.strip():
                    continue
                
                # Find exact position in original text
                # Use normalized search to handle whitespace differences
                chunk_normalized = chunk_text.strip()
                chunk_start = text.find(chunk_normalized, current_search_pos)
                
                if chunk_start == -1:
                    # Fallback: try to find first few words
                    first_words = ' '.join(chunk_normalized.split()[:5])
                    chunk_start = text.find(first_words, current_search_pos)
                    if chunk_start == -1:
                        # Last resort: use sequential position
                        chunk_start = current_search_pos
                        print(f"[Warning] Could not find exact position for chunk {i}, using estimated position {chunk_start}")
                
                node = TextNode(
                    text=chunk_text,
                    metadata={
                        **metadata, 
                        "chunk_index": i,
                        "start_char_idx": chunk_start,
                        "end_char_idx": chunk_start + len(chunk_text)
                    }
                )
                all_nodes.append(node)
                
                # Update search position to after current chunk
                current_search_pos = chunk_start + len(chunk_text)
        
        # Sort nodes by start_char_idx to guarantee ordering
        all_nodes.sort(key=lambda n: n.metadata.get("start_char_idx", 0))
        
        # Reassign chunk_index after sorting
        for i, node in enumerate(all_nodes):
            node.metadata["chunk_index"] = i
        
        return all_nodes
    
    def _parse_nodes(self, nodes: List[BaseNode], show_progress: bool = False, **kwargs) -> List[BaseNode]:
        """Required by NodeParser base class - delegates to get_nodes_from_documents"""
        # Convert BaseNodes back to Documents for processing
        documents = []
        for node in nodes:
            doc = Document(text=node.get_content(), metadata=node.metadata)
            documents.append(doc)
        
        return self.get_nodes_from_documents(documents)
    
    def _llm_split_text(self, text: str) -> List[str]:
        """Split text using LLM to detect context boundaries with semantic coherence
        
        Prioritizes semantic completeness over strict size limits.
        """
        if len(text) < self.target_size:
            return [text]
        
        # Set max_chunk_size if not explicitly set
        if self.max_chunk_size is None:
            self.max_chunk_size = self.target_size * 2
        
        # Build prompt for LLM
        size_instruction = (
            "automatically determine optimal chunk size based on semantic coherence"
            if self.llm_auto_size
            else f"aim for chunks around {self.target_size} characters, but prioritize semantic completeness"
        )
        
        chunks = []
        remaining_text = text
        position = 0
        
        while len(remaining_text) > 0:
            # If remaining text is small, add as final chunk
            if len(remaining_text) < self.target_size * 0.5:
                chunks.append(remaining_text)
                break
            
            # Extract window for analysis
            window_size = min(self.window_size, len(remaining_text))
            window = remaining_text[:window_size]
            
            # Ask LLM to extract first semantic chunk
            prompt = f"""Analyze the following text and extract the first semantically complete section.

IMPORTANT:
- Return ONLY the extracted text, nothing else
- The section must end at a natural boundary (완결된 문장, 문단, 리스트 항목)
- DO NOT modify, summarize, or add any text
- {size_instruction}
- PRIORITIZE semantic completeness over size limits
- If a paragraph/section is slightly over target size but semantically complete, include it entirely
- DO NOT force-split in the middle of a meaningful unit
- Include complete sentences/paragraphs only
- Stop at: period(.), section break(\\n\\n), list end, dialogue completion

Text to analyze:
{window}

Return ONLY the extracted section (copy exact text):"""

            try:
                response = self.llm.complete(prompt)
                extracted = response.text.strip()
                
                # Remove markdown code blocks if present
                if extracted.startswith('```') and extracted.endswith('```'):
                    lines = extracted.split('\n')
                    extracted = '\n'.join(lines[1:-1]).strip()
                
                # Validate extraction
                if not extracted or len(extracted) < 50:
                    # Fallback to sentence-based split
                    chunk = self._extract_sentences_up_to_size(window, self.target_size)
                    if chunk:
                        chunks.append(chunk)
                        # Find exact position in remaining text
                        chunk_end = remaining_text.find(chunk) + len(chunk)
                        remaining_text = remaining_text[chunk_end:].lstrip()
                        position += chunk_end
                    else:
                        break
                    continue
                
                # Warn if chunk is excessively large (but still allow it)
                if len(extracted) > self.max_chunk_size:
                    print(f"[Warning] LLM extracted chunk of size {len(extracted)} exceeds max_chunk_size {self.max_chunk_size}. "
                          f"Keeping it as semantic unit is prioritized over size limit.")
                
                # Find exact match in remaining text to preserve accuracy
                # Try to find extracted text in original
                match_start = remaining_text.find(extracted[:100])  # Use first 100 chars as anchor
                
                if match_start != -1:
                    # Found match, extract from original text
                    chunk_end = match_start + len(extracted)
                    chunk = remaining_text[match_start:chunk_end]
                    chunks.append(chunk)
                    remaining_text = remaining_text[chunk_end:].lstrip()
                    position += chunk_end
                else:
                    # Couldn't find exact match, use sentence-based fallback
                    print(f"[Warning] Could not find LLM extraction in text, using sentence fallback")
                    chunk = self._extract_sentences_up_to_size(window, self.target_size)
                    if chunk:
                        chunks.append(chunk)
                        chunk_end = len(chunk)
                        remaining_text = remaining_text[chunk_end:].lstrip()
                        position += chunk_end
                    else:
                        # Last resort: take target_size worth of text at sentence boundary
                        chunk = window[:self.target_size]
                        last_sentence_end = self._find_last_sentence_end(chunk)
                        if last_sentence_end > 0:
                            chunk = chunk[:last_sentence_end]
                        chunks.append(chunk)
                        remaining_text = remaining_text[len(chunk):].lstrip()
                        position += len(chunk)
                        
            except Exception as e:
                print(f"LLM chunking error: {e}, using sentence fallback")
                chunk = self._extract_sentences_up_to_size(window, self.target_size)
                if chunk:
                    chunks.append(chunk)
                    remaining_text = remaining_text[len(chunk):].lstrip()
                    position += len(chunk)
                else:
                    break
        
        # Validation: ensure no empty chunks
        chunks = [c.strip() for c in chunks if c.strip()]
        
        return chunks if chunks else [text]
    
    def _extract_sentences_up_to_size(self, text: str, target_size: int) -> str:
        """Extract sentences up to target size, ending at sentence boundary
        
        Strategy:
        - Target size is a recommendation, not a hard limit
        - Allow exceeding target_size to preserve semantic units (up to max_size)
        - Prefer complete sentences/paragraphs even if slightly over target
        """
        import re
        
        # Allow up to 30% over target_size to preserve semantic units
        # But never exceed 2x target_size (absolute maximum)
        max_size = min(int(target_size * 1.3), target_size * 2)
        
        # Korean sentence endings: ., !, ?, 다., 요., etc.
        # Also handle paragraph breaks
        sentence_pattern = r'[.!?]\s+|\n\n'
        
        matches = list(re.finditer(sentence_pattern, text))
        
        if not matches:
            # No clear sentence boundaries, try to split at paragraph or return as is
            if '\n\n' in text:
                para_end = text.find('\n\n')
                return text[:para_end + 2] if para_end > 100 else text[:max_size]
            return text[:max_size]
        
        # Find the best sentence boundary:
        # 1. Prefer boundaries close to target_size
        # 2. Allow going over target_size to complete a sentence (up to max_size)
        # 3. Never force-split in the middle of a sentence
        best_end = 0
        best_distance = float('inf')
        
        for match in matches:
            end_pos = match.end()
            
            # Stop if we've gone way past the maximum allowed size
            if end_pos > max_size:
                break
            
            # Calculate distance from target
            distance = abs(end_pos - target_size)
            
            # Update best boundary if:
            # - We haven't passed target yet, OR
            # - We passed target but this is closer than previous best
            if end_pos <= target_size:
                # Before target: always update
                best_end = end_pos
                best_distance = distance
            elif end_pos <= max_size:
                # Past target but within max: use if closer to target
                # OR if we don't have a good boundary yet
                if distance < best_distance or best_end == 0:
                    best_end = end_pos
                    best_distance = distance
                else:
                    # We found a boundary past target, and it's getting worse - stop
                    break
        
        if best_end > 0:
            return text[:best_end].strip()
        
        # Fallback: return up to first sentence (even if it exceeds target)
        return text[:matches[0].end()].strip() if matches else text[:max_size]
    
    def _find_last_sentence_end(self, text: str) -> int:
        """Find the last complete sentence ending in text"""
        import re
        
        # Korean and English sentence endings
        sentence_endings = r'[.!?](?:\s|$)|\n\n'
        
        matches = list(re.finditer(sentence_endings, text))
        
        if matches:
            # Return position after last sentence ending
            return matches[-1].end()
        
        # No sentence ending found, try paragraph break
        last_para = text.rfind('\n\n')
        if last_para > 0:
            return last_para + 2
        
        return 0


class ChunkingStrategy(str, Enum):
    FIXED_SIZE = "fixed_size"
    SLIDING_WINDOW = "sliding_window"
    HIERARCHICAL = "hierarchical"
    CONTEXT_AWARE = "context_aware"
    PARENT_CHILD = "parent_child"


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
        
        elif strategy == ChunkingStrategy.CONTEXT_AWARE:
            # LLM-based Context Aware Chunking using sliding window
            target_size = config.get("target_size", 800)
            llm_auto_size = config.get("llm_auto_size", False)
            
            return ContextAwareNodeParser(
                llm=self.llm,
                target_size=target_size,
                llm_auto_size=llm_auto_size
            )
        
        elif strategy == ChunkingStrategy.PARENT_CHILD:
            # Parent-Child: Create custom parser that generates parent chunks
            # and splits them into children with parent metadata
            # We'll use SentenceSplitter for both levels with different sizes
            parent_size = config.get("parent_size", 2000)
            child_size = config.get("child_size", 500)
            parent_overlap = config.get("parent_overlap", 0)
            child_overlap = config.get("child_overlap", 100)
            
            # Return a custom wrapper that handles parent-child logic
            # For now, we'll use the child splitter and add parent metadata in chunk_document
            return SentenceSplitter(
                chunk_size=child_size,
                chunk_overlap=child_overlap,
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
        
        # Special handling for parent-child strategy
        if strategy == ChunkingStrategy.PARENT_CHILD:
            return self._chunk_parent_child(text, config)
        
        # Create Document
        document = Document(text=text)
        
        # Get appropriate parser
        parser = self.get_node_parser(strategy, config)
        
        # Parse into nodes
        nodes = parser.get_nodes_from_documents([document])
        
        # For hierarchical, extract parent-child relationships from node.relationships
        # and add to metadata for Milvus storage
        if strategy == ChunkingStrategy.HIERARCHICAL:
            for node in nodes:
                if hasattr(node, 'relationships'):
                    # Extract parent reference if exists
                    from llama_index.core.schema import NodeRelationship
                    if NodeRelationship.PARENT in node.relationships:
                        parent_node = node.relationships[NodeRelationship.PARENT]
                        if hasattr(parent_node, 'node_id'):
                            node.metadata['parent_id'] = parent_node.node_id
        
        return nodes
    
    def _chunk_parent_child(
        self,
        text: str,
        config: Dict[str, Any]
    ) -> List[BaseNode]:
        """Custom parent-child chunking with metadata"""
        from llama_index.core.schema import TextNode
        import uuid
        
        parent_size = config.get("parent_size", 2000)
        child_size = config.get("child_size", 500)
        parent_overlap = config.get("parent_overlap", 0)
        child_overlap = config.get("child_overlap", 100)
        
        # Create parent splitter
        parent_splitter = SentenceSplitter(
            chunk_size=parent_size,
            chunk_overlap=parent_overlap
        )
        
        # Create child splitter
        child_splitter = SentenceSplitter(
            chunk_size=child_size,
            chunk_overlap=child_overlap
        )
        
        # Split into parent chunks
        parent_doc = Document(text=text)
        parent_nodes = parent_splitter.get_nodes_from_documents([parent_doc])
        
        # Now split each parent into children
        all_child_nodes = []
        
        for parent_idx, parent_node in enumerate(parent_nodes):
            parent_text = parent_node.get_content()
            parent_id = f"parent_{parent_idx}"
            
            # Split parent into children
            child_doc = Document(text=parent_text)
            child_nodes = child_splitter.get_nodes_from_documents([child_doc])
            
            # Add parent metadata to each child
            for child_node in child_nodes:
                child_node.metadata['parent_id'] = parent_id
                child_node.metadata['parent_index'] = parent_idx
                child_node.metadata['parent_content'] = parent_text
                all_child_nodes.append(child_node)
        
        return all_child_nodes
    
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
Format:
- ALWAYS return a list of Triplets.
- Use 'Subject|Relation|Object' format (Pipe separated).
- NO conversational text. NO intro/outro. Only the data.
- Extract up to 5 triplets.

{examples_prompt_part}
{dictionary_text}

Text:
{text[:2000]}

Triplets:"""
                    
                    if (idx + 1) % 5 == 0 or idx == 0:
                        print(f"[Pipeline] Processing chunk {idx+1}/{len(nodes)}...")
                        
                    response = await self.llm.acomplete(prompt)
                    response_text = response.text.strip()
                    print(f"[Pipeline] Raw Extraction Response (Node {idx}): {response_text[:300]}...") # Debug log
                    
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
                            # Strip markdown bullets
                            if line.startswith("- "): line = line[2:]
                            elif line.startswith("* "): line = line[2:]
                            
                            if '|' in line:
                                parts = line.split('|')
                                if len(parts) >= 3:
                                    s = parts[0].strip()
                                    p = parts[1].strip()
                                    o = parts[2].strip()
                                    
                                    # Basic validation
                                    if s and p and o and len(s) < 50 and len(p) < 50: 
                                        node_triples.append({
                                            "subject": s,
                                            "predicate": p,
                                            "object": o,
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
        # ✅ Graph 추출이 없으면 Entity Dictionary도 불필요 (Non-Graph KB 최적화)
        if enable_entity_normalization and not entity_dictionary and graph_extractor_type != GraphExtractorType.NONE:
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
        elif graph_extractor_type == GraphExtractorType.NONE:
            print(f"[Pipeline] Phase 1: Skipped (Non-Graph mode - no entity extraction needed)")
        stats.append({"step": "Step 1: Entity Extraction (Pre-pass)", "duration": round(time.time() - t1, 2)})
        
        # PHASE 2: Chunking (Triple-level)
        t2 = time.time()
        if job_id and jobs.get(job_id, {}).get("status") == JobStatus.CANCELLED: return {}
        
        # ✅ 로그 메시지 개선: Non-Graph 모드 명시
        if graph_extractor_type == GraphExtractorType.NONE:
            print(f"[Pipeline] Phase 2: Chunking document (Non-Graph mode - vector search only)...")
        else:
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
        else:
            print(f"[Pipeline] Phase 3: Skipped (Non-Graph mode - no triple extraction)")
        
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
