"""
Contextual Grouper: 엔티티 해소 (Doc2Graph 전략)
"""
import json
import logging
import asyncio
from typing import Dict, List, Any
from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

class ContextualGrouper:
    """
    Doc2Graph Style Grouper:
    Uses LLM only (No Embeddings) to group noun variants based on strict identity rules.
    """
    def __init__(self, llm=None):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.system_prompt = (
            "You are a linguistics expert who merges noun fragments into compound nouns and groups entities.\n"
            "Goal: Group words that refer to the EXACT SAME specific entity or individual."
        )

    async def group_nouns(self, raw_entity_map: Dict[str, Any], chunks: Any = None) -> Dict[str, Any]:
        """
        Groups raw entities using LLM prompts only. (Doc2Graph logic)
        """
        # 1. Prepare candidate list
        candidates = list(raw_entity_map.keys())
        if not candidates:
            return {}

        logger.info(f"[Grouper] Consolidating {len(candidates)} candidates using Doc2Graph strategy...")

        # 2. Split into batches if too many candidates (to avoid context limit)
        # Doc2Graph usually handles few hundred entities at once.
        batch_size = 500
        batches = [candidates[i:i + batch_size] for i in range(0, len(candidates), batch_size)]
        
        mappings = {}
        
        for batch in batches:
            batch_mapping = await self._process_batch(batch)
            mappings.update(batch_mapping)

        # 3. Apply mappings to create final dictionary
        final_dict = {}
        for original_name, data in raw_entity_map.items():
            canonical_name = mappings.get(original_name, original_name)
            
            if canonical_name not in final_dict:
                final_dict[canonical_name] = {
                    "type": "Entity", # Doc2Graph doesn't infer strict types during grouping
                    "variants": set(),
                    "chunk_ids": set()
                }
            
            # Add variant only if it's different from the canonical name
            if original_name != canonical_name:
                final_dict[canonical_name]["variants"].add(original_name)
            
            # Merge chunk IDs
            final_dict[canonical_name]["chunk_ids"].update(data["chunk_ids"])
            
            # Inherit types if available and specific
            if "types" in data:
                # Simple logic to keep existing types
                pass

        # Convert sets to lists for JSON serialization
        return {
            name: {
                "type": info["type"],
                "variants": sorted(list(info["variants"])),
                "chunk_ids": list(info["chunk_ids"])
            }
            for name, info in final_dict.items()
        }

    async def _process_batch(self, candidates: List[str]) -> Dict[str, str]:
        candidates_str = ", ".join(candidates)
        
        # Doc2Graph Strict Prompt
        user_prompt = (
            "다음 명사 리스트에서 **'동일한 인물'이나 '동일한 특정 개체'를 지칭하는 단어들**을 그룹화해줘.\n"
            "특히 '오징어', '게임' 처럼 단어가 분리되어 리스트에 있고, 이들이 합쳐진 '오징어 게임'도 리스트에 있다면 **'오징어 게임'을 대표어로 하여 통합**해.\n"
            "'프론트', '맨'이 '프론트 맨'의 일부라면 '프론트 맨'으로 통합해.\n"
            "단, '성기훈', '기훈' 같은 이름 변형은 계속 그룹화하되, **의미가 단순히 비슷한 유의어(예: 자동차-탈것)는 묶지 마.**\n\n"
            "출력 형식 (JSON):\n"
            "{\n"
            "  \"groups\": [\n"
            "    {\"canonical\": \"대표단어\", \"variants\": [\"변형1\", \"변형2\"]},\n"
            "    ...\n"
            "  ]\n"
            "}\n\n"
            f"명사 리스트:\n[{candidates_str}]"
        )

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o", # Grouping needs high intelligence, sticking to 4o per Doc2Graph
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            groups = data.get("groups", [])
            
            mapping = {}
            for group in groups:
                canonical = group.get("canonical")
                variants = group.get("variants", [])
                if canonical:
                    for v in variants:
                        mapping[v] = canonical
                    # Ensure canonical maps to itself (implied, but good for safety)
                    mapping[canonical] = canonical
            
            return mapping

        except Exception as e:
            logger.error(f"[Grouper] Batch processing failed: {e}")
            return {}  # Return empty mapping on failure (preserve originals)_dict
