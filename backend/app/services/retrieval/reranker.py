from typing import List, Dict, Any, Optional
from app.services.embedding import embedding_service
from sentence_transformers import CrossEncoder # type: ignore
import numpy as np
import math

class RerankingService:
    def __init__(self):
        self.reranker = None
    
    def _get_reranker(self):
        if not self.reranker:
            # Multilingual Cross-Encoder for Korean and other languages
            self.reranker = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')
        return self.reranker
        
    def _cosine_similarity(self, vec1, vec2) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))

    async def rerank_results(
        self,
        query: str,
        results: List[Dict],
        top_k: int = 5,
        threshold: float = 0.0
    ) -> List[Dict]:
        """Rerank using Cross-Encoder"""
        if not results:
            return []
            
        reranker = self._get_reranker()
        pairs = [[query, result['content']] for result in results]
        reranker_scores = reranker.predict(pairs)
        
        # Min-Max normalization for better score discrimination
        min_score = min(reranker_scores)
        max_score = max(reranker_scores)
        if max_score - min_score > 0:
            normalized_scores = [(s - min_score) / (max_score - min_score) for s in reranker_scores]
        else:
            # All scores are identical
            normalized_scores = [0.5] * len(reranker_scores)
        
        # Add small floor to avoid exact 0.0
        normalized_scores = [max(0.01, s) for s in normalized_scores]
        
        for result, score in zip(results, normalized_scores):
            # Use Cross-Encoder normalized score as the main score
            result['score'] = float(score)
            if 'metadata' not in result: result['metadata'] = {}
            result['metadata']['_reranker_raw_score'] = float(score)
            
        filtered = [r for r in results if r['score'] >= threshold]
        filtered.sort(key=lambda x: x['score'], reverse=True)
        top_results = filtered[:top_k]
        
        return top_results
            
        return top_results

    async def llm_rerank_results(
        self,
        query: str,
        results: List[Dict],
        top_k: int = 5,
        threshold: float = 0.0,
        strategy: str = "full",
        llm_model_config: Optional[dict] = None,
    ) -> List[Dict]:
        """Rerank using LLM (OpenAI compatible)"""
        if not results:
            return []
            
        from openai import AsyncOpenAI
        from app.core.config import settings
        import asyncio
        import os

        if llm_model_config:
            from app.core.models_resolver import resolve_model_config
            resolved = await resolve_model_config(llm_model_config)
            api_key = resolved["api_key"]
            llm_model = resolved["model"]
            base_url = resolved.get("base_url")
            extra_headers = resolved.get("extra_headers") or {}
        else:
            api_key = settings.OPENAI_API_KEY
            llm_model = "gpt-3.5-turbo"
            base_url = None
            extra_headers = {}
        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        if extra_headers:
            client_kwargs["default_headers"] = extra_headers
        client = AsyncOpenAI(**client_kwargs)
        
        # Load prompt template from file
        prompt_path = "/app/data/prompts/rerank_llm_prompt.txt"
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
        except FileNotFoundError:
            print(f"[Rerank] Prompt file not found at {prompt_path}, using fallback.")
            prompt_template = "Query: {query}\n\nChunk: {chunk_content}\n\nRate relevance 0.0 to 1.0. Output ONLY the number."
        
        async def evaluate(result: Dict) -> tuple[Dict, float]:
            chunk_content = result['content']
            
            # Simple truncation for brevity in prompt
            if strategy == 'limited':
                chunk_content = chunk_content[:1500]
            
            prompt = prompt_template.format(query=query, chunk_content=chunk_content)

            try:
                resp = await client.chat.completions.create(
                    model=llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0, max_tokens=10
                )
                content = resp.choices[0].message.content.strip()
                print(f"[Rerank DEBUG] Chunk snippet: {chunk_content[:30]}... | LLM Response: {content}")
                
                import re
                match = re.search(r"(\d+(\.\d+)?)", content)
                if match:
                    score = float(match.group(1))
                    print(f"[Rerank DEBUG] Parsed Score: {score}")
                else:
                    print(f"[Rerank DEBUG] Failed to parse score from content: {content}")
                    score = 0.0
                return (result, max(0.0, min(1.0, score)))
            except Exception as e:
                print(f"[Rerank DEBUG] Error evaluating chunk: {e}")
                import traceback
                traceback.print_exc()
                return (result, 0.0)
            except:
                return (result, 0.0)
                
        tasks = [evaluate(r) for r in results]
        evaluated = await asyncio.gather(*tasks)
        
        for result, score in evaluated:
            # Use LLM score directly as the main score
            result['score'] = float(score)
            if 'metadata' not in result: result['metadata'] = {}
            result['metadata']['_llm_reranker_raw_score'] = float(score)
            
        filtered = [r for r in results if r['score'] >= threshold]
        filtered.sort(key=lambda x: x['score'], reverse=True)
        
        return filtered[:top_k]

reranking_service = RerankingService()
