import spacy
from spacy.matcher import PhraseMatcher
import logging
from typing import List, Dict, Any, Tuple
import urllib.parse
import re
from app.services.ingestion.entity_store import EntityStore

logger = logging.getLogger(__name__)

_SHARED_NLP = None

class SpacyGraphProcessor:
    def __init__(self, kb_id: str, model_name: str = "ko_core_news_sm"):
        self.kb_id = kb_id
        global _SHARED_NLP
        if _SHARED_NLP is None:
            try:
                logger.info(f"Loading spaCy model: {model_name}")
                _SHARED_NLP = spacy.load(model_name)
            except OSError:
                logger.warning(f"Model '{model_name}' not found. Downloading...")
                from spacy.cli import download
                download(model_name)
                _SHARED_NLP = spacy.load(model_name)
        
        self.nlp = _SHARED_NLP
            
        self.matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        self.entity_store = EntityStore(kb_id)
        
        # Load known entities into PhraseMatcher
        self._refresh_matcher()
        
        self.namespace_entity = "http://rag.local/entity/"
        self.namespace_relation = "http://rag.local/relation/"
        self.namespace_source = "http://rag.local/source/"

    def _refresh_matcher(self):
        """Reload patterns from EntityStore into PhraseMatcher."""
        patterns = self.entity_store.get_patterns()
        self.matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER") # Reset
        
        # Group by label
        grouped = {}
        for p in patterns:
            label = p['label']
            if label not in grouped:
                grouped[label] = []
            grouped[label].append(self.nlp.make_doc(p['pattern']))
            
        for label, docs in grouped.items():
            self.matcher.add(label, docs)
        
        logger.info(f"Refreshed PhraseMatcher with {len(patterns)} patterns for KB {self.kb_id}")

    def _sanitize_uri(self, text: str) -> str:
        """Sanitize text to be used in URI."""
        clean = re.sub(r'[^a-zA-Z0-9_\uAC00-\uD7A3\u0400-\u04FF]+', '_', text.strip())
        return urllib.parse.quote(clean)

    async def extract_graph_elements(self, text: str, chunk_id: str, config: Dict[str, Any] = {}) -> List[str]:
        """
        Extract entities using spaCy (NER + PhraseMatcher).
        Update EntityStore.
        Return RDF triples.
        """
        doc = self.nlp(text)
        
        found_entities = []
        
        # 1. Run PhraseMatcher (Known Entities)
        matches = self.matcher(doc)
        for match_id, start, end in matches:
            span = doc[start:end]
            label = self.nlp.vocab.strings[match_id]
            # Normalize found text
            clean_text = self._normalize_entity(span)
            if clean_text:
                found_entities.append({"text": clean_text, "label": label, "source": "gazetteer"})

        # 2. Run NER (New Candidates)
        # Note: spaCy NER runs automatically in the pipeline
        for ent in doc.ents:
            clean_text = self._normalize_entity(ent)
            if clean_text:
                found_entities.append({"text": clean_text, "label": ent.label_, "source": "ner"})
            
        # Deduplicate by text
        seen = set()
        unique_candidates = []
        for e in found_entities:
            key = (e['text'], e['label'])
            if key not in seen:
                seen.add(key)
                unique_candidates.append(e)
                
        candidates = [{"text": e["text"], "label": e["label"]} for e in unique_candidates]
        
        # 3. Update Entity Store
        self.entity_store.add_candidates(candidates)
        
        # 4. Check for promotion
        if config.get("auto_promote", False):
            self.entity_store.promote_entities(
                min_freq=config.get("min_freq", 3),
                min_len=config.get("min_len", 2)
            )
            self._refresh_matcher() 

        # 5. Generate Triples
        rdf_triples = []
        chunk_uri = f"<{self.namespace_source}{chunk_id}>"
        
        # Use sanitized unique entities for triples
        for e in unique_candidates:
            text = e["text"]
            label = e["label"]
            
            subj_clean = self._sanitize_uri(text)
            s_uri = f"<{self.namespace_entity}{subj_clean}>"
            
            # Type definition
            type_uri = f"<http://rag.local/type/{label}>"
            rdf_triples.append(f"{s_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> {type_uri} .")
            
            # Label
            rdf_triples.append(f'{s_uri} <http://www.w3.org/2000/01/rdf-schema#label> "{text}" .')
            
            # Link to Source
            rdf_triples.append(f"{s_uri} <{self.namespace_relation}hasSource> {chunk_uri} .")
        
        return rdf_triples

    def _normalize_entity(self, span) -> str:
        """
        Strip Korean particles (Josa) from the entity span.
        Handles both separate tokens (e.g. [시즌, 2, 의]) and agglutinated tokens (e.g. [애플의]).
        """
        if not span:
            return ""
            
        # 1. Trim standalone particle tokens from the end
        # ADP: Adposition (includes Josa), PART: Particle, PUNCT: Punctuation (optional, might as well clean)
        end_idx = span.end
        while end_idx > span.start:
            last_token = span.doc[end_idx - 1]
            if last_token.pos_ in ['ADP', 'PART', 'PUNCT']:
                end_idx -= 1
            else:
                break
                
        if end_idx == span.start:
            return ""
        
        # 2. Check the (new) last token for agglutinated suffixes
        last_token = span.doc[end_idx - 1]
        clean_last = last_token.text
        
        # Heuristic for Person Names (PROPN) or specific cases like "이정재의"
        # spaCy sometimes analyzes names weirdly: '이정재의' -> '이정+재+의' (common error)
        # Strategy:
        # If ENTITY LABEL is PERSON, be very careful about stripping.
        # Check if the lemma decompostion makes sense length-wise.
        
        normalized = False
        is_person = span.label_ == "PERSON" or (hasattr(span, 'ent_type_') and span.ent_type_ == "PERSON")
        
        # Heuristic A: Lemma Decomposition (e.g. "2+의", "이정재+는")
        if '+' in last_token.lemma_:
            parts = last_token.lemma_.split('+')
            # Lemma often looks like "stem+josa"
            # If parts[0] is substantial, take it.
            # But if parts[0] is short and total length is long (meaning over-segmentation), confirm logic.
            # Example bad case: "이정재의" -> "이정+재+의". parts[0] is "이정". 
            
            # Sub-heuristic: If it's a PERSON and lemma split results in a short name (<2 chars) but original was long, suspicious.
            # But Korean names are usually 3 chars (2 char given name).
            # "이정" is 2 chars. "이정재" is 3. 
            
            # Let's rely on TAG if possible.
            # nq=ProperNoun, ncn=Noun, j*=Particle
            
            # Simple approach: Join all NOUN/PROPN/ROOT parts of the lemma?
            # spaCy LEMMA string doesn't give POS per part easily.
            
            # Better approach:
            # If the last character of the text matches a known Josa, and the lemma supports that the suffix is separable.
            
            # Let's try a safer truncation based on known Josa suffixes rather than trusting Lemma blindly for Names.
            pass

        # Use explicitly reliable suffixes
        # Only strip if the suffix is definitely a Josa
        josas = ['의', '은', '는', '이', '가', '을', '를', '에', '와', '과', '로', '으로', '에서', '에게', '께', '부터', '까지', '도', '만', '이랑', '랑']
        
        # Sort by length to match longest first ("으로" vs "로")
        josas.sort(key=len, reverse=True)
        
        # Check if it ends with a Josa
        for josa in josas:
            if clean_last.endswith(josa):
                # Validation: Does the remaining part look valid?
                stem = clean_last[:-len(josa)]
                
                # Constraint 1: Length
                if len(stem) < 1: continue
                
                # Constraint 2: If PERSON, assume name >= 2 chars usually.
                # "이" (Person?) -> unlikely standalone. "이정재" -> "이정재"
                # "공유가" -> "공유" (2 chars ok)
                if is_person and len(stem) < 2:
                    continue
                
                # Apply strip
                clean_last = stem
                normalized = True
                break
        
        # Fallback: Use Lemma if Josa match failed but Lemma indicates distinct particle?
        # Only if NOT normalized yet.
        if not normalized and '+' in last_token.lemma_:
            parts = last_token.lemma_.split('+')
            # Only use first part if it covers most of the word or if subsequent parts are clearly particles (starts with j/e)
            # This is hard to know from string "stem+suff".
            # Trust Josa string matching more for now as it's safer for "이정재의" case.
            pass
            
        # Reconstruct text
        if end_idx - 1 > span.start:
            prefix = span.doc[span.start:end_idx-1].text_with_ws
            return (prefix + clean_last).strip()
        else:
            return clean_last.strip()
        # 6. Simple Relation Extraction (Co-occurrence)
        # Link entities that appear close to each other? 
        # Or just link all entities in this chunk to each other with "related_to"? (might be too dense)
        # For now, let's stick to Node extraction + Source linking as per "Bootstrap" focus.
        # The prompt said "Entity extraction", not relation extraction optimization.
        # "Target pipeline: Detect entities -> Dictionary -> ..."
        
        return rdf_triples

