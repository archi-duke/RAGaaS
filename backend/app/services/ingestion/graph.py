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
        
        # [UPGRADED] Single-Pass Graph Extraction (Optimized for Recall)
        # We merge Entity Discovery, Normalization, and Relation Extraction into one call
        # to prevent missing valid entities like '장풍' that might be filtered in multi-pass.

        # Add Critical Normalization Rules to the prompt
        system_rules = """
        ### CRITICAL RULE: Entity Normalization
        1. **Consistency**: If the same person/entity has multiple names (e.g., "성기훈", "기훈", "Seong Gi-hun"), choose **ONE canonical Korean name** (e.g., "성기훈") and use it for all triples.
        2. **Mappings**: Return a dictionary of variant-to-canonical mappings you performed.
        3. **Capture All Valid Entities**: Do not ignore skills, abilities, or artifacts (e.g., "장풍", "달고나") if they have relationships.
        """
        
        relation_prompt = prompt_template.replace("{text}", text) + "\n\n" + system_rules
        
        try:
            print(f"[Graph] Single-Pass Extraction for chunk {chunk_id[:8]}...")
            r1 = await self.client.chat.completions.create(
                model="gpt-4o", # Use strong model for high-fidelity extraction
                messages=[{"role": "user", "content": relation_prompt}],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            content = r1.choices[0].message.content
            data = json.loads(content)
            
            # The LLM should now return both triples and entity_mappings in one go
            triples_data = data.get("triples", [])
            entity_mappings = data.get("entity_mappings", {})
            
            logger.info(f"[Graph] Extracted {len(triples_data)} triples with {len(entity_mappings)} mapping hints.")
        except Exception as e:
            logger.error(f"Single-Pass Extraction failed: {e}")
            triples_data = []
            entity_mappings = {}

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
