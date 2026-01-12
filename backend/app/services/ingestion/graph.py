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

logger = logging.getLogger(__name__)

# Inverse Relations Dictionary (Global Default)
# Format: "Original" : "Inverse"
INVERSE_RELATIONS = {
    "스승": "제자",
    "제자": "스승",
    "부모": "자식",
    "자식": "부모",
    "선배": "후배",
    "후배": "선배",
    "형": "동생",
    "동생": "형",
    "언니": "동생",
    "누나": "동생",
    "오빠": "동생",
    "남편": "아내",
    "아내": "남편"
}


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
        if spacy_candidates:
            filter_prompt = f"""Given these candidate entities from text analysis: {list(spacy_candidates)}

Review the original text and:
1. KEEP only meaningful entities (persons, organizations, concepts, skills)
2. ADD any important entities that were missed
3. REMOVE duplicates, particles, or meaningless words

Original Text:
{text}

Return JSON:
{{"entities": ["Entity1", "Entity2", ...]}}
"""
        else:
            # Fallback to pure LLM if spaCy failed
            prompt_path_p1 = Path("data/prompts/graph_entity_extraction_prompt.txt")
            if prompt_path_p1.exists():
                filter_prompt = prompt_path_p1.read_text(encoding="utf-8").replace("{text}", text)
            else:
                filter_prompt = f"Extract key entities from: {text}\nReturn JSON: {{\"entities\": [...]}}"
        
        try:
            r1 = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": filter_prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )
            entities = json.loads(r1.choices[0].message.content).get("entities", [])
            print(f"[Graph] Pass 1 Final entities ({len(entities)}): {entities[:10]}...")
        except Exception as e:
            logger.error(f"Pass 1 LLM failed: {e}")
            entities = list(spacy_candidates) if spacy_candidates else []


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
            subj = self._sanitize_uri(item['subject'])
            pred = self._sanitize_uri(item['predicate'])
            obj = self._sanitize_uri(item['object'])
            
            # URIs
            s_uri = f"<{self.namespace_entity}{subj}>"
            p_uri = f"<{self.namespace_relation}{pred}>"
            o_uri = f"<{self.namespace_entity}{obj}>"
            
            # Triple: Subject - Predicate - Object
            rdf_triples.append(f"{s_uri} {p_uri} {o_uri} .")

            # Auto-generate Inverse Relation
            if item['predicate'] in INVERSE_RELATIONS:
                inv_pred = INVERSE_RELATIONS[item['predicate']]
                inv_pred_safe = self._sanitize_uri(inv_pred)
                p_inv_uri = f"<{self.namespace_relation}{inv_pred_safe}>"
                
                # Inverse Triple: Object - InversePredicate - Subject
                # e.g. (성기훈, 제자, 오일남) -> (오일남, 스승, 성기훈)
                # "오일남 is 스승 of 성기훈"
                rdf_triples.append(f"{o_uri} {p_inv_uri} {s_uri} .")
                # print(f"[Graph] Auto-generated inverse: {item['object']} --{inv_pred}--> {item['subject']}")

            
            # Link Subject to Chunk (provenance)
            rdf_triples.append(f"{s_uri} <{self.namespace_relation}hasSource> {chunk_uri} .")
            
            # Link Object to Chunk (optional, but good for discovery)
            rdf_triples.append(f"{o_uri} <{self.namespace_relation}hasSource> {chunk_uri} .")
            
            # Annotate Subject with Label
            rdf_triples.append(f'{s_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{item["subject"]}" .')

            # Annotate Predicate with Label (Critical for search)
            rdf_triples.append(f'{p_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{item["predicate"]}" .')

            # Annotate Object with Label
            rdf_triples.append(f'{o_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{item["object"]}" .')

        return {
            "rdf_triples": rdf_triples,
            "structured_triples": triples_data
        }

graph_processor = GraphProcessor()
