import spacy
nlp = spacy.load("ko_core_news_sm")

def clean_text(text):
    doc = nlp(text)
    # Assume the whole text is the entity for testing
    last_token = doc[-1]
    
    print(f"Text: {text}")
    print(f"Last Token: '{last_token.text}'")
    print(f"POS: {last_token.pos_}, TAG: {last_token.tag_}, LEMMA: {last_token.lemma_}")
    
    # 1. Check for specific Josa tags in the tag string (e.g., 'jco', 'jcm')
    # Use simple string check for 'j' in tags if they are separated by '+'
    tags = last_token.tag_.split('+')
    has_josa = any(t.startswith('j') for t in tags)
    
    if has_josa:
        # Try to use lemma to split
        # Lemma format usually: "stem+josa"
        parts = last_token.lemma_.split('+')
        # We assume the last part is the josa if matched
        # But we need to be careful.
        # Construct the clean text using the first part of lemma if feasible?
        # Or just remove the suffix matching the josa?
        
        # Heuristic: if text ends with the josa identified in lemma
        if len(parts) > 1:
             # Assume last part is Josa
             # Reconstruct root
             root = "".join(parts[:-1]) # simplistic
             print(f"  -> Lemma Heuristic: {root}")
             return root
    
    # 2. Fallback: Common Josa suffix removal if POS indicates NOUN/PROPN/NUM
    # and we suspect it wasn't split.
    # List of common josas
    josas = ['의', '은', '는', '이', '가', '을', '를', '에', '와', '과', '로', '으로', '에서', '에게', '께', '부터', '까지']
    
    if last_token.pos_ in ['NOUN', 'PROPN', 'NUM']:
        for josa in josas:
             if last_token.text.endswith(josa):
                 # Check strict length to avoid removing from short words excessively?
                 # e.g. "가" (to act/go?) -> "가". "시" -> "시".
                 if len(last_token.text) > len(josa):
                     # Verify it's not part of the word? Hard without dictionary.
                     # But current user context implies these are Entities.
                     # "시즌 2의" -> "의" is definitely Josa.
                     print(f"  -> Suffix Heuristic: {last_token.text[:-len(josa)]}")
                     return last_token.text[:-len(josa)]
                     
    return last_token.text

samples = ["시즌 2의", "애플의", "아이폰을", "집에서", "서울로", "학교에", "우리가", "시즌 2", "버스"]
for s in samples:
    cleaned = clean_text(s)
    print(f"Input: {s} -> Clean: {cleaned}")
    print("-" * 20)
