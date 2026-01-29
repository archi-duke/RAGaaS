import json
import asyncio
from typing import Dict, List, Any
from llama_index.core.schema import BaseNode
from .noun_extractor import NounExtractor
from .contextual_grouper import ContextualGrouper


class DictionaryBuilder:
    """
    청크 기반 엔티티 사전 구축기.
    
    Phase 1: 각 청크에서 모든 명사 추출 및 명사-청크 링킹
    Phase 2: 공출현 패턴과 컨텍스트를 활용한 엔티티 그룹핑
    """
    
    def __init__(self, llm):
        self.llm = llm
        self.noun_extractor = NounExtractor(llm)
        self.contextual_grouper = ContextualGrouper(llm)
    
    async def build_from_text(self, text: str, sampling_size: int = 5000) -> Dict[str, Dict[str, Any]]:
        """
        Global Entity Dictionary from Raw Text (Doc2Graph Phase 1 Optimized)
        No pre-chunking required.
        """
        if not text:
            return {}
        
        print(f"[DictionaryBuilder] Building dictionary from raw text ({len(text)} chars)...")
        
        # Phase 1: Noun Extraction (Parallel Windows)
        # sampling_size here acts as 'window_size' for splitting large text
        raw_entity_map = await self.noun_extractor.extract_from_text(text, window_size=sampling_size)
        
        if not raw_entity_map:
            print("[DictionaryBuilder] No entities extracted.")
            return {}
        
        # Phase 2: Contextual Grouping (LLM Only)
        # Apply strict grouping and type consolidation
        entity_dict = await self.contextual_grouper.group_nouns(raw_entity_map)
        
        # Pass 1 결과 그대로 반환 -> (이제 Grouping 적용됨)
        # entity_dict = raw_entity_map 

        print(f"[DictionaryBuilder] Dictionary built with {len(entity_dict)} canonical entities.")
        return entity_dict

    async def build(self, chunks: List[BaseNode], sampling_size: int = 100000) -> Dict[str, Dict[str, Any]]:
        """
        청크 리스트로부터 Global Entity Dictionary를 생성합니다. (GraphRAG 전략)
        """
        if not chunks:
            print("[DictionaryBuilder] No chunks provided.")
            return {}
        
        print(f"[DictionaryBuilder] Building dictionary from {len(chunks)} chunks...")
        
        # Phase 1: 엔티티 프로필 추출 (Doc2Graph 스타일)
        # sampling_size는 여기서 'bucket window size'로 사용됨
        raw_entity_map = await self.noun_extractor.extract_from_chunks(chunks, window_size=sampling_size)
        
        if not raw_entity_map:
            print("[DictionaryBuilder] No entities extracted.")
            return {}
        
        # Phase 2: 컨텍스트 기반 해소 및 요약 (GraphRAG 스타일)
        entity_dict = await self.contextual_grouper.group_nouns(raw_entity_map, chunks)
        
        print(f"[DictionaryBuilder] Dictionary built with {len(entity_dict)} canonical entities.")
        return entity_dict
