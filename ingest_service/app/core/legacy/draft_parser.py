
from typing import List, Sequence
from llama_index.core.node_parser import NodeParser
from llama_index.core.schema import BaseNode, Document, TextNode
from llama_index.core import Settings as LlamaSettings
from llama_index.core.bridge.pydantic import Field

class ContextAwareNodeParser(NodeParser):
    target_size: int = Field(default=800, description="Target character size for chunks")
    llm_auto_size: bool = Field(default=False, description="Whether to let LLM decide size")
    
    def _parse_nodes(self, nodes: Sequence[BaseNode], show_progress: bool = False, **kwargs) -> List[BaseNode]:
        all_nodes = []
        for node in nodes:
            text = node.get_content()
            # If text is too short, just keep it
            if len(text) < self.target_size * 1.5 and not self.llm_auto_size:
                all_nodes.append(node)
                continue
                
            # Heuristic: Processing text in windows of ~4000 chars (safe for most LLM contexts)
            # to ask LLM for split points.
            # However, simpler implementation for now:
            # Split by paragraphs first to get manageable units.
            # Then group paragraphs into chunks using LLM decision or Accumulation.
            
            # Implementation: Accumulate paragraphs until > target_size, then ask LLM 
            # "Should we split here, or include next paragraph?"
            # This is "Semantic Grouping".
            
            splits = self._llm_split_text(text)
            
            for split_text in splits:
                if not split_text.strip():
                    continue
                new_node = TextNode(text=split_text)
                new_node.metadata = node.metadata.copy()
                all_nodes.append(new_node)
                
        return all_nodes

    def _llm_split_text(self, text: str) -> List[str]:
        # Simple paragraph splitting first
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = []
        current_len = 0
        
        target = self.target_size
        if self.llm_auto_size:
            target = 1000 # Default soft target for auto
            
        # We will accumulate paragraphs. When we exceed target, we check if we should break.
        # Actually, for "Context Aware", we want to avoid breaking LISTS or SECTIONS.
        
        # We'll use a prompt to check if the current accumulation + next paragraph 
        # constitute a coherent break or if they are tightly coupled.
        
        # Optimization: To avoid too many LLM calls, we only ask when we are near the formatted limit
        # or when we encounter potential structure markers.
        
        for para in paragraphs:
            para_len = len(para)
            
            if current_len + para_len < target * 0.5:
                # Too small, just add
                current_chunk.append(para)
                current_len += para_len
                continue
                
            # If adding this paragraph exceeds target significantly...
            # Or if we represent a "good size"...
            
            # Simple Logic without excessive LLM calls (Cost/Latency trade-off):
            # Accumulate until > target.
            
            # But user wants "Correct Context".
            # Let's try the "Markdown/Structure" aware strict split, enhanced by LLM?
            # No, let's use the LLM to validte the break.
            
            current_chunk.append(para)
            current_len += para_len
            
            if current_len >= target:
                # We reached target size. 
                # Ideally check if this is a good place to break.
                # Since we are iterating paragraphs, we are breaking at paragraph boundary.
                # This is already better than breaking mid-sentence.
                
                # To be "Context Aware", we should check if the LAST paragraph indicates a list start?
                # e.g. "The characters are:" -> Don't break.
                
                text_to_check = "\n\n".join(current_chunk[-2:]) # Check last 2 paragraphs
                if self._is_tightly_coupled(text_to_check):
                    # Don't break yet if possible, unless we are huge
                    if current_len < target * 2.0:
                        continue
                
                # Break here
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_len = 0
        
        if current_chunk:
            chunks.append("\n\n".join(current_chunk))
            
        return chunks

    def _is_tightly_coupled(self, text: str) -> bool:
        # Ask LLM if these two paragraphs are tightly coupled (e.g. list intro -> items)
        # This is expensive but accurate.
        
        # Fast Heuristic first
        if text.strip().endswith(':'): 
            return True
        
        # TODO: Use LlamaSettings.llm to ask.
        # For now, return False to mimic "Paragraph Splitting" which is better than "Sentence Splitting" for lists.
        return False

# Since implementing a full LLM loop inside the class within the 'write_to_file' 
# might be error prone without testing, 
# I will implement a ROBUST version that replaces the placeholder 
# directly in pipeline.py
