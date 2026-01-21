from typing import List, Tuple, Dict, Any
from pathlib import Path
from app.services.ingestion.spacy_processor import SpacyGraphProcessor
from openai import AsyncOpenAI
from app.core.config import settings
import json
import logging
import re
import urllib.parse
from app.core.fuseki import fuseki_client
import yaml

logger = logging.getLogger(__name__)

# [REMOVED] Inverse Relations Dictionary
# Inverse relations are now handled at query time via bidirectional search,
# not by physically duplicating triples at ingestion time.


class GraphProcessor:

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.namespace_entity = "http://rag.local/entity/"
        self.namespace_relation = "http://rag.local/relation/"
        self.namespace_source = "http://rag.local/source/"

    def _sanitize_uri(self, text: str) -> str:
        """Sanitize text to be used in URI."""
        # Replace spaces with underscores, remove special chars (preserve Korean and Cyrillic)
        clean = re.sub(r'[^a-zA-Z0-9_\uAC00-\uD7A3\u0400-\u04FF]+', '_', text.strip())
        return urllib.parse.quote(clean)

    async def extract_graph_elements(self, text: str, chunk_id: str, kb_id: str, config: Dict[str, Any] = {}) -> Dict[str, Any]:
        """
        Extracts entities and relations from text and returns structured data and RDF triples.
        """
        # Check config for method
        graph_settings = config.get("graph_settings", {})
        method = graph_settings.get("method", "llm") # Default to LLM
        
        if method == "spacy":
            processor = SpacyGraphProcessor(kb_id)
            # Pass merged config or graph_settings? Pass graph_settings
            # Spacy processor currently returns list[str]. 
            # We might need to adjust it later, but for now let's wrap it?
            # Or better, just assume LLM for Neo4j for this task to minimize complexity.
            # But to keep type consistency:
            rdf_triples = await processor.extract_graph_elements(text, chunk_id, graph_settings)
            return {"rdf_triples": rdf_triples, "structured_triples": []}

        # Fallback to LLM (Dynamic Prompt from File)
        prompt_path = Path("data/prompts/graph_extraction_prompt.txt")
        default_prompt_template = """
        Analyze the following text and extract key relationships and characteristics between the entities.

        CRITICAL INSTRUCTIONS:
        1. **STRICTLY BASED ON TEXT**: Ignore any prior knowledge about the entities (e.g., TV show plots). Extract information EXACTLY as written, even if fictional (e.g., "Energy Wave master/장풍의 고수").
        2. **Korean Predicates**: For Korean text, strongly prefer Korean predicates (e.g., "스승", "제자", "특징", "상태", "능력").
        3. **Capture Attributes**: Link entities to their descriptive traits as triples (Subject -> Predicate -> Attribute). 
           - Example: "오일남은 장풍의 고수다" -> {"subject": "오일남", "predicate": "특징", "object": "장풍의 고수"}

        Each triple should have:
        - "subject": Entity name
        - "predicate": Relationship or Attribute Type
        - "object": Entity name OR Attribute Value

        Text:
        {text}

        Output format:
        {
            "triples": [
                {"subject": "성기훈", "predicate": "스승", "object": "오일남"},
                {"subject": "오일남", "predicate": "특징", "object": "장풍의 고수"},
                {"subject": "오일남", "predicate": "건강상태", "object": "뇌종양"}
            ]
        }
        """
        
        if prompt_path.exists():
            try:
                with open(prompt_path, "r", encoding="utf-8") as f:
                    prompt_template = f.read()
            except Exception as e:
                logger.error(f"Failed to read prompt file: {e}")
                prompt_template = default_prompt_template
        else:
             # Try absolute path fallback if running from different cwd
             abs_path = Path("/app/data/prompts/graph_extraction_prompt.txt")
             if abs_path.exists():
                 try:
                    with open(abs_path, "r", encoding="utf-8") as f:
                        prompt_template = f.read()
                 except Exception:
                    prompt_template = default_prompt_template
             else:
                prompt_template = default_prompt_template


        # Load Few-shot examples for In-Context Learning
        examples_path = Path("extraction_examples.yaml")
        if not examples_path.exists():
             examples_path = Path("/app/extraction_examples.yaml")
             
        if examples_path.exists():
            try:
                with open(examples_path, "r", encoding="utf-8") as f:
                    examples = yaml.safe_load(f)
                    if examples:
                        examples_str = "\n\n[Few-shot Examples (Learn from these patterns)]\n"
                        for ex in examples:
                            triples = ex.get('triples', [])
                            if not triples and 'properties' in ex:
                                triples = []
                            examples_str += f"Input Text: {ex['text']}\nOutput JSON: {json.dumps({'triples': triples}, ensure_ascii=False)}\n\n"
                        
                        prompt_template += examples_str
                        logger.info(f"[Graph] Loaded {len(examples)} few-shot examples from {examples_path}")
                    else:
                        logger.warning(f"[Graph] Examples file found but empty or invalid content")
            except Exception as e:
                logger.warning(f"Failed to load examples: {e}")
        else:
             logger.warning(f"[Graph] Extraction examples file not found at {examples_path}")


        # MULTI-PASS STRATEGY IMPLEMENTATION (HYBRID)
        
        # Pass 1: HYBRID Entity Extraction (spaCy + LLM filtering)
        print("[Graph] Pass 1: Hybrid Entity Extraction (spaCy + LLM)")
        
        # Step 1a: spaCy NER + Noun extraction
        try:
            import spacy
            try:
                nlp = spacy.load("ko_core_news_sm")
            except OSError:
                nlp = spacy.load("en_core_web_sm")  # Fallback
            
            doc = nlp(text)
            spacy_candidates = set()
            
            # Extract named entities
            for ent in doc.ents:
                # Clean up: remove particles (의, 은, 는, 이, 가, 을, 를)
                clean = ent.text.rstrip("의은는이가을를에서로")
                if len(clean) >= 2:
                    spacy_candidates.add(clean)
            
            # Extract nouns (PROPN, NOUN)
            for token in doc:
                if token.pos_ in ["PROPN", "NOUN"] and len(token.text) >= 2:
                    # Skip particles
                    if token.text not in ["것", "수", "등", "때", "중"]:
                        spacy_candidates.add(token.text)
            
            print(f"[Graph] spaCy candidates ({len(spacy_candidates)}): {list(spacy_candidates)[:10]}...")
        except Exception as e:
            logger.error(f"spaCy extraction failed: {e}")
            spacy_candidates = set()
        
        # Step 1b: LLM filters and completes the entity list
        # Step 1b: LLM filters and completes the entity list
        # We allow LLM to expand upon spaCy candidates to catch missed entities (e.g., "강새벽")
        candidates_str = str(list(spacy_candidates)) if spacy_candidates else "None"
        
        filter_prompt = f"""Analyze the provided text and identify ALL key entities (Persons, Organizations, Concepts, Locations, Artifacts).

I have run a basic NLP extraction and found these potential candidates: {candidates_str}

**Your Task:**
1. **Verify & Filter**: Keep valid candidates from the list above.
2. **Discover Missing**: Read the text carefully to find **missed entities** that the NLP tool failed to catch (e.g., specific names, nicknames, novel terms).
   - *Example*: If text mentions "탈북자 강새벽", but NLP missed "강새벽", you MUST add it.
3. **Clean & Normalize**: Remove common nouns/particles.
4. **[NEW] Entity Deduplication & Normalization**: 
   - If the same person/entity is mentioned with different names (e.g., full name vs. nickname, Korean vs. English), **choose ONE canonical name** and use it consistently.
   - **Preference Order**: Full Korean Name > Nickname > English Name
   - **Examples**:
     * "성기훈", "기훈", "Seong Gi-hun" → Normalize to "성기훈" (full Korean name)
     * "조상우", "상우", "Cho Sang-woo" → Normalize to "조상우"
     * "오일남", "일남", "Oh Il-nam" → Normalize to "오일남"
   - **CRITICAL**: Return ONLY the canonical name in the final entity list. Do NOT include variants.

Text:
{text}

Return JSON with:
1. "entities": List of unique, normalized canonical entity names
2. "entity_mappings": Dictionary mapping all variants to their canonical form (for reference)

Example Output:
{{
  "entities": ["성기훈", "조상우", "오일남"],
  "entity_mappings": {{
    "기훈": "성기훈",
    "Seong Gi-hun": "성기훈",
    "상우": "조상우",
    "Cho Sang-woo": "조상우",
    "일남": "오일남",
    "Oh Il-nam": "오일남"
  }}
}}
"""
        
        try:
            r1 = await self.client.chat.completions.create(
                model="gpt-4o", # Use strong model for entity discovery
                messages=[{"role": "user", "content": filter_prompt}],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            response_data = json.loads(r1.choices[0].message.content)
            entities = response_data.get("entities", [])
            entity_mappings = response_data.get("entity_mappings", {})
            
            logger.info(f"[Graph] Pass 1 Final entities ({len(entities)}): {entities[:10]}...")
            if entity_mappings:
                logger.info(f"[Graph] Entity mappings found: {len(entity_mappings)} variants normalized")
                print(f"[Graph] Entity Normalization Map: {entity_mappings}")
        except Exception as e:
            logger.error(f"Pass 1 LLM failed: {e}")
            entities = list(spacy_candidates) if spacy_candidates else []
            entity_mappings = {}



        # Pass 2: Relation Extraction with Hints
        # Use the main template from prompt_template (which was loaded earlier from file or default)
        relation_prompt = prompt_template.replace("{text}", text)
        
        # Determine how to inject entities into Pass 2
        # If the template has {entities} placeholder, use it.
        # Otherwise, prepend it as a hint.
        entities_str = ', '.join(entities) if entities else "None identified yet"
        if "{entities}" in relation_prompt:
            relation_prompt = relation_prompt.replace("{entities}", entities_str)
        else:
            # Prepend entities hint if not in template to maintain Multi-pass benefit
            relation_prompt = f"Entities to focus on (Hints from Pass 1): {entities_str}\n\n" + relation_prompt

        
        try:
            r2 = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": relation_prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )
            content = r2.choices[0].message.content
            print(f"[Graph] Pass 2 LLM Response: {content[:200]}...")
            data = json.loads(content)
            triples_data = data.get("triples", [])
            print(f"[Graph] Pass 2 Extracted {len(triples_data)} triples.")
        except Exception as e:
            logger.error(f"Pass 2 failed: {e}")
            triples_data = []

        rdf_triples = []
        
        # Chunk URI
        chunk_uri = f"<{self.namespace_source}{chunk_id}>"
        
        for item in triples_data:
            # [NEW] Entity Normalization: 변형된 이름을 정규 이름으로 변환
            subject_raw = item['subject']
            object_raw = item['object']
            
            # entity_mappings에서 정규 이름 찾기 (없으면 원본 사용)
            subject_normalized = entity_mappings.get(subject_raw, subject_raw)
            object_normalized = entity_mappings.get(object_raw, object_raw)
            
            # 정규화 로그 (변경된 경우만)
            if subject_raw != subject_normalized:
                logger.info(f"[Graph] Normalized subject: '{subject_raw}' -> '{subject_normalized}'")
            if object_raw != object_normalized:
                logger.info(f"[Graph] Normalized object: '{object_raw}' -> '{object_normalized}'")
            
            subj = self._sanitize_uri(subject_normalized)
            pred = self._sanitize_uri(item['predicate'])
            obj = self._sanitize_uri(object_normalized)
            
            # URIs
            s_uri = f"<{self.namespace_entity}{subj}>"
            p_uri = f"<{self.namespace_relation}{pred}>"
            o_uri = f"<{self.namespace_entity}{obj}>"
            
            # Triple: Subject - Predicate - Object
            rdf_triples.append(f"{s_uri} {p_uri} {o_uri} .")

            # [REMOVED] Auto-generate Inverse Relation
            # Inverse relations are now inferred at query time, not stored physically.
            
            # Link Subject to Chunk (provenance)
            rdf_triples.append(f"{s_uri} <{self.namespace_relation}hasSource> {chunk_uri} .")
            
            # Link Object to Chunk (optional, but good for discovery)
            rdf_triples.append(f"{o_uri} <{self.namespace_relation}hasSource> {chunk_uri} .")
            
            # Annotate Subject with Label (정규화된 이름 사용)
            rdf_triples.append(f'{s_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{subject_normalized}" .')

            # Annotate Predicate with Label (Critical for search)
            rdf_triples.append(f'{p_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{item["predicate"]}" .')

            # Annotate Object with Label (정규화된 이름 사용)
            rdf_triples.append(f'{o_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{object_normalized}" .')

        return {
            "rdf_triples": rdf_triples,
            "structured_triples": triples_data
        }

graph_processor = GraphProcessor()
