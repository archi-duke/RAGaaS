"""
Noun Extractor: 청크별 엔티티 추출 및 링킹 (Doc2Graph 전략)
최초 반영 시점의 안정적인 버전으로 복구됨.
"""
import json
import asyncio
import logging
from typing import Dict, List, Any
from llama_index.core.schema import BaseNode
from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

class NounExtractor:
    def __init__(self, llm=None):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.system_prompt = """당신은 텍스트에서 지식 그래프 구축을 위한 주요 엔티티(인물, 조직, 장소, 사건, 개념 등)를 추출하는 전문가입니다.

[추출 규칙]
1. 텍스트의 모든 주요 엔티티와 핵심 개념을 추출하세요.
2. 각 엔티티에 대해 이름(name)과 유형(type)을 명시하세요.
3. 결과는 반드시 "entities" 키를 가진 JSON 객체여야 합니다.

[엔티티 유형 예시]
- PERSON, ORGANIZATION, LOCATION, OBJECT, EVENT, CONCEPT, TECHNOLOGY

분석할 텍스트가 주어지면 위 규칙에 따라 JSON으로 응답하세요."""

    async def extract_from_text(self, text: str, window_size: int = 5000) -> Dict[str, Any]:
        # DEBUG: Check API Key
        import os
        from app.core.config import settings
        key_prefix = self.client.api_key[:15] if self.client.api_key else "None"
        env_key_prefix = settings.OPENAI_API_KEY[:15] if settings.OPENAI_API_KEY else "None"
        print(f"\n[NounExtractor DEBUG] Client Key: {key_prefix}...")
        print(f"[NounExtractor DEBUG] Settings Key: {env_key_prefix}...\n")

        """
        Process raw text directly (Pre-chunking NOT required).
        Splits text into large windows and extracts entities in parallel.
        """
        # 1. Split text into large windows (simple character slicing)
        # In a real scenario, use a token splitter, but char slicing is fast and sufficient for large windows.
        windows = []
        for i in range(0, len(text), window_size):
            windows.append(text[i : i + window_size])
            
        logger.info(f"[NounExtractor] Processing {len(windows)} large text windows (approx {window_size} chars each)...")

        # 2. Extract in Parallel
        sem = asyncio.Semaphore(10)
        
        async def restricted_extract(text_window, idx):
            async with sem:
                return await self._extract_from_string(text_window, idx)

        tasks = [restricted_extract(w, i) for i, w in enumerate(windows)]
        results = await asyncio.gather(*tasks)
        
        # 3. Consolidate Results
        raw_entity_map = {}
        for entities_list in results:
            for name in entities_list:
                name = name.strip()
                if not name: continue
                
                if name not in raw_entity_map:
                    raw_entity_map[name] = {"types": set(), "chunk_ids": set()}
                
                # Revert to generic type
                raw_entity_map[name]["types"].add("Entity")
                # No chunk_ids in this phase since we are pre-chunking.
                # Use a placeholder or manage mapping later if needed.
                raw_entity_map[name]["chunk_ids"].add("doc_global")
        
        return {name: {"types": list(data["types"]), "chunk_ids": list(data["chunk_ids"])} 
                for name, data in raw_entity_map.items()}

    async def _extract_from_string(self, text: str, idx: int) -> List[str]:
        try:
            # Doc2Graph Strategy: Simple Prompt for Maximum Recall
            # Type classification is REMOVED to prevent LLM from filtering entities.
            user_prompt = (
                "다음 텍스트에서 주요 명사와 복합 명사를 추출해서 각 명사를 한 줄에 하나씩 출력해줘.\n"
                "특히 '오징어 게임', '프론트 맨'처럼 여러 단어가 합쳐져 하나의 고유한 의미를 나타내는 경우 반드시 하나의 단위로 추출해.\n\n"
                "출력 포맷:\n"
                "명사1\n"
                "명사2\n"
                "...\n\n"
                f"텍스트:\n{text}"
            )

            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that extracts nouns and compound nouns from Korean text."},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0
            )
            content = response.choices[0].message.content
            
            # Split by newline and clean up
            entities = [line.strip() for line in content.split('\n') if line.strip()]
            
            # Simple list of strings (Doc2Graph format)
            logger.info(f"[Window {idx+1}] Extracted {len(entities)} raw entities.")
            return entities

        except Exception as e:
            logger.error(f"[Window {idx+1}] Extraction failed: {e}")
            return []

        except Exception as e:
            logger.error(f"[Window {idx+1}] Extraction failed: {e}")
            return []

    # Keep this for compatibility if needed, but extract_from_text is preferred now.
    async def extract_from_chunks(self, chunks: List[BaseNode], window_size: int = 30000) -> Dict[str, Any]:
        # Fallback to text extraction by joining chunks
        full_text = "\n\n".join([c.get_content() for c in chunks])
        return await self.extract_from_text(full_text, window_size)

    # Deprecated internal method (removed _extract_from_bucket logic since we use string now)
    async def _extract_from_bucket(self, bucket_chunks, idx):
        pass


