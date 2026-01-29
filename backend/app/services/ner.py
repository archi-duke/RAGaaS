from typing import List, Set, Literal
import re

class NERService:
    """NER service supporting multiple engines (regex, Kiwi, spaCy)"""
    
    def __init__(self):
        self._spacy_nlp = None
        self._kiwi = None
    
    def _get_spacy(self):
        """Lazy load spaCy model"""
        if self._spacy_nlp is None:
            try:
                import spacy
                try:
                    self._spacy_nlp = spacy.load("ko_core_news_lg")
                    print("[NER] Loaded spaCy model: ko_core_news_lg")
                except OSError:
                    try:
                        self._spacy_nlp = spacy.load("ko_core_news_sm")
                        print("[NER] Loaded spaCy model: ko_core_news_sm")
                    except OSError:
                        self._spacy_nlp = False
            except ImportError:
                print("[NER] spaCy not found")
                self._spacy_nlp = False
        return self._spacy_nlp
    
    def _get_kiwi(self):
        """Lazy load Kiwi"""
        if self._kiwi is None:
            try:
                from kiwipiepy import Kiwi
                self._kiwi = Kiwi()
                print("[NER] Loaded Kiwi morphological analyzer")
            except ImportError:
                print("[NER] Kiwi not found")
                self._kiwi = False
        return self._kiwi
    
    def extract_entities(
        self, 
        text: str, 
        engine: Literal['regex', 'kiwi', 'spacy'] = 'regex',
        mode: Literal['nnp', 'ner'] = 'nnp'
    ) -> Set[str]:
        """
        Extract entities based on engine and mode.
        
        Args:
            text: Input text
            engine: 'regex', 'kiwi', or 'spacy'
            mode: 'nnp' (Proper Noun POS) or 'ner' (Named Entity Recognition)
        """
        if engine == 'spacy':
            return self._extract_spacy(text, mode)
        elif engine == 'kiwi':
            return self._extract_kiwi(text, mode)
        else:
            return self._extract_entities_regex(text)
    
    def _extract_spacy(self, text: str, mode: str) -> Set[str]:
        nlp = self._get_spacy()
        if not nlp: return self._extract_entities_regex(text)
        
        doc = nlp(text)
        entities = set()
        
        if mode == 'ner':
            # Use spaCy's built-in NER (ents)
            for ent in doc.ents:
                if ent.label_ in {'PERSON', 'ORG', 'GPE', 'LOC'}:
                    entities.add(ent.text)
        else:
            # Use spaCy's POS tagging (PROPN)
            for token in doc:
                if token.pos_ == 'PROPN':
                    if len(token.text) >= 2:
                        entities.add(token.text)
        return entities

    def _extract_kiwi(self, text: str, mode: str) -> Set[str]:
        kiwi = self._get_kiwi()
        if not kiwi: return self._extract_entities_regex(text)
        
        result = kiwi.analyze(text)
        if not result: return set()
        
        entities = set()
        best_analysis = result[0][0]
        
        if mode == 'ner':
            # Kiwi NER simulation: Merge consecutive NNPs
            # e.g. "성" + "기훈" -> "성기훈"
            current_entity = []
            
            for i, token in enumerate(best_analysis):
                if token.tag.startswith('NNP'):
                    current_entity.append(token.form)
                else:
                    if current_entity:
                        full_entity = "".join(current_entity)
                        if len(full_entity) >= 2:
                            entities.add(full_entity)
                        current_entity = []
            # Flush last entity
            if current_entity:
                full_entity = "".join(current_entity)
                if len(full_entity) >= 2:
                    entities.add(full_entity)
                    
        else:
            # Simple NNP mode: One token = One entity
            for token in best_analysis:
                if token.tag.startswith('NNP'):
                    if len(token.form) >= 2:
                        entities.add(token.form)
                        
        return entities
    
    def _extract_entities_regex(self, text: str) -> Set[str]:
        """Original regex-based entity extraction"""
        entities = set()
        words = text.split()
        
        for word in words:
            # Remove punctuation
            clean_word = re.sub(r'[^\w\s]', '', word)
            
            # Korean person names (2-4 characters + 씨/선생/배우 등)
            if re.match(r'^[가-힣]{2,4}(씨|선생|배우|감독|작가|님)?$', clean_word):
                # Remove titles
                base_name = re.sub(r'(씨|선생|배우|감독|작가|님)$', '', clean_word)
                if len(base_name) >= 2:
                    entities.add(base_name)
            
            # Standalone 2-3 character names (common Korean name length)
            elif re.match(r'^[가-힣]{2,3}$', clean_word):
                entities.add(clean_word)
        
        return entities

    def filter_by_entities(
        self, 
        query: str, 
        results: List[dict], 
        penalty: float = 0.5,
        engine: Literal['regex', 'kiwi', 'spacy'] = 'regex',
        mode: Literal['nnp', 'ner'] = 'nnp'
    ) -> List[dict]:
        """
        Filter/penalize results based on entity matching.
        """
        # Extract entities from query
        query_entities = self.extract_entities(query, engine=engine, mode=mode)
        
        if not query_entities:
            # No entities found in query, return as-is
            return results
        
        print(f"[NER][{engine}:{mode}] Query entities: {query_entities}")
        
        # Check each result
        for result in results:
            content = result.get('content', '')
            content_entities = self.extract_entities(content, engine=engine, mode=mode)
            
            # Check if query entities are in content
            matched = query_entities & content_entities  # Intersection
            
            if not matched:
                # No entity match - apply penalty
                original_score = result['score']
                result['score'] = original_score * penalty
                
                # Store NER score in metadata (preserve existing metadata!)
                if 'metadata' not in result:
                    result['metadata'] = {}
                # Don't overwrite, just add NER fields
                result['metadata']['_ner_original'] = original_score
                result['metadata']['_ner_penalty'] = penalty
                # Store debug info
                result['metadata']['_ner_engine'] = f"{engine}:{mode}"
                
                print(f"[NER] Penalty applied: {original_score:.4f} → {result['score']:.4f}")
            else:
                print(f"[NER] Match found: {matched}")
        
        # Re-sort by adjusted scores
        results.sort(key=lambda x: x['score'], reverse=True)
        
        return results

ner_service = NERService()
