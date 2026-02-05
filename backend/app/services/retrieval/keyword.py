from typing import List, Dict, Any
from pymilvus import Collection
from app.services.embedding import embedding_service
from .base import RetrievalStrategy
import numpy as np
from openai import AsyncOpenAI
from app.core.config import settings

class KeywordRetrievalStrategy(RetrievalStrategy):
    async def extract_keywords_with_llm(self, query: str) -> str:
        """
        Extract meaningful keywords (nouns, roots) from query using LLM, removing particles.
        Returns a space-separated string of keywords.
        """
        prompt = f"""
        Extract the core keywords from the following Korean query, removing particles (Josa) and functional words.
        Return ONLY the keywords separated by spaces. Do not include any other text.
        
        Query: {query}
        Keywords:
        """
        try:
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=50
            )
            keywords = response.choices[0].message.content.strip()
            print(f"[LLM Keyword Extraction] '{query}' -> '{keywords}'")
            return keywords
        except Exception as e:
            print(f"LLM Keyword Extraction failed: {e}")
            return query

    async def search(self, kb_id: str, query: str, top_k: int, **kwargs) -> List[Dict[str, Any]]:
        score_threshold = kwargs.get("score_threshold", 0.0)
        use_llm_extraction = kwargs.get("use_llm_keyword_extraction", False)
        
        with open("backend_debug.log", "a") as f:
            f.write(f"Keyword Search Start. Query: {query}, TopK: {top_k}\n")
        
        # LLM Keyword Extraction
        search_query = query
        if use_llm_extraction:
            search_query = await self.extract_keywords_with_llm(query)

        # Get existing collection
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        collection = Collection(collection_name)
        collection.load()
        
        from rank_bm25 import BM25Okapi

        # Fetch candidate chunks from Milvus (fetch generic candidates)
        # Note: In a real large-scale system, you'd use an Inverted Index (Elasticsearch/Solr)
        results = collection.query(
            expr='chunk_id != ""',
            output_fields=["content", "doc_id", "chunk_id"],
            limit=2000
        )
        
        if not results:
            return []

        # Use shared tokenizer utility - choose mode based on use_multi_pos
        from app.services.retrieval.tokenizer import korean_tokenize
        use_multi_pos = kwargs.get("use_multi_pos", False)  # Default False for keyword-only search
        tokenizer_engine = kwargs.get("tokenizer", "kiwi")
        tokenize_mode = 'extended' if use_multi_pos else 'strict'

        # Tokenize Corpus
        tokenized_corpus = [
            korean_tokenize(
                hit.get("content", ""), 
                mode=tokenize_mode, 
                include_original_words=False, 
                min_length=1,
                engine=tokenizer_engine
            ) 
            for hit in results
        ]
        
        bm25 = BM25Okapi(tokenized_corpus)
        
        # Tokenize Query
        tokenized_query = korean_tokenize(
            search_query, 
            mode=tokenize_mode, 
            include_original_words=False, 
            min_length=1,
            engine=tokenizer_engine
        )
        doc_scores = bm25.get_scores(tokenized_query)
        
        # Combine results with scores
        retrieved = []
        for i, score in enumerate(doc_scores):
            # BM25 scores are not 0-1. They are positive floats.
            if score <= 0:
                continue
                
            hit = results[i]
            retrieved.append({
                "chunk_id": hit.get("chunk_id"),
                "content": hit.get("content"),
                "score": float(score), # BM25 score
                "metadata": {"doc_id": hit.get("doc_id")}
            })
        
        retrieved.sort(key=lambda x: x["score"], reverse=True)
        final_res = retrieved[:top_k]
        
        # Format display name for tokenizer
        tokenizer_display = "Kiwi"
        if tokenizer_engine == 'spacy':
            tokenizer_display = "spaCy (ko_lg)"

        # Attach extracted keywords and tokenizer info to ALL results
        # This ensures the keywords are available even if some chunks are filtered/reranked
        for result in final_res:
            if "extracted_keywords" not in result["metadata"]:
                result["metadata"]["extracted_keywords"] = tokenized_query
            # Add tokenizer name for UI display
            result["metadata"]["tokenizer"] = tokenizer_display
        
        with open("backend_debug.log", "a") as f:
            f.write(f"Keyword Search End. Found: {len(final_res)}\n")
            
        return final_res

    def _cosine_similarity(self, vec1, vec2) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))
