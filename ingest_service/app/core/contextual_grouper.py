"""
Contextual Grouper: 엔티티 해소 (Doc2Graph 전략)
"""
import json
import logging
import asyncio
from typing import Dict, List, Any, Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class ContextualGrouper:
    """
    Doc2Graph Style Grouper:
    Uses LLM only (No Embeddings) to group noun variants based on strict identity rules.
    """
    def __init__(self, llm=None, llm_config: Optional[Dict[str, Any]] = None):
        cfg = llm_config or {}
        self.cfg = cfg
        self.model = cfg.get("model")
        self.system_prompt = (
            "You are a linguistics expert who merges noun fragments into compound nouns and groups entities.\n"
            "Goal: Group words that refer to the EXACT SAME specific entity or individual."
        )

    async def group_nouns(self, raw_entity_map: Dict[str, Any], chunks: Any = None) -> Dict[str, Any]:
        """
        Groups raw entities using LLM prompts (Doc2Graph logic).
        """
        # 1. Prepare candidate list
        candidates = list(raw_entity_map.keys())
        if not candidates:
            return {}

        logger.info(f"[Grouper] Consolidating {len(candidates)} candidates using Doc2Graph strategy...")

        # 2. Split into batches
        batch_size = 300 # Doc2Graph defaultish
        batches = [candidates[i:i + batch_size] for i in range(0, len(candidates), batch_size)]
        
        mappings = {}
        
        for batch_keys in batches:
            batch_mapping = await self._process_batch_simple(batch_keys)
            mappings.update(batch_mapping)

        # 3. Apply mappings to create final dictionary
        final_dict = {}
        
        for original_name, original_data in raw_entity_map.items():
            # Canonical Mapping
            canonical_name = mappings.get(original_name, original_name)
            
            if canonical_name not in final_dict:
                final_dict[canonical_name] = {
                    "type": "Entity", # Revert to generic type as Doc2Graph doesn't infer types
                    "variants": set(),
                    "chunk_ids": set()
                }
            
            final_dict[canonical_name]["variants"].add(original_name)
            
            if "chunk_ids" in original_data:
                final_dict[canonical_name]["chunk_ids"].update(original_data["chunk_ids"])
        
        # Convert sets to lists
        return {
            name: {
                "type": info["type"],
                "variants": sorted(list(info["variants"])),
                "chunk_ids": list(info["chunk_ids"])
            }
            for name, info in final_dict.items()
        }

    async def _process_batch_simple(self, candidates: List[str]) -> Dict[str, str]:
        """
        Doc2Graph style grouping without Types.
        """
        candidates_str = "\n".join(candidates)
        
        user_prompt = (
            "다음 명사 리스트에서 **'철자나 표기법이 유사하여 같은 단어로 볼 수 있는 것들'만** 그룹화해줘.\n"
            "단어의 의미를 해석해서 추론하지 말고, **글자 형태가 비슷한 경우**에만 통합해야 해.\n\n"
            "[그룹화 규칙]\n"
            "1. **띄어쓰기/붙여쓰기 차이**: (예: '오징어 게임' = '오징어게임', '프론트 맨' = '프론트맨') -> 긴 쪽이나 띄어쓰기가 된 쪽을 대표어로.\n"
            "2. **이름의 일부 포함**: (예: '성기훈' = '기훈', '조상우' = '상우') -> 풀네임을 대표어로.\n"
            "3. **조사/접미사 제거**: (예: '참가자들' -> '참가자')\n"
            "4. **절대 금지**: 의미가 같아도 글자가 다르면 묶지 마. (예: '프론트 맨'과 '황인호'는 글자가 다르므로 절대 묶으면 안 됨!)\n\n"
            "출력 형식: '대표단어, 변형1, 변형2...'\n"
            f"리스트:\n{candidates_str}"
        )

        try:
            from app.core.llm import achat
            content = await achat(
                self.cfg,
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=self.model, temperature=0,
            )
            
            # Parse Doc2Graph style output
            # Line format: "Representative, Variant1, Variant2"
            mapping = {}
            lines = content.split('\n')
            
            for line in lines:
                # Remove numbers if present (e.g. "1. Sung Ki-hoon, Ki-hoon")
                import re
                clean_line = re.sub(r'^\d+\.\s*', '', line.strip())
                clean_line = re.sub(r'^-\s*', '', clean_line)
                
                parts = [p.strip() for p in clean_line.split(',') if p.strip()]
                if not parts: continue
                
                representative = parts[0]
                for p in parts:
                    mapping[p] = representative
            
            return mapping

        except Exception as e:
            logger.error(f"[Grouper] Batch processing failed: {e}")
            return {}
