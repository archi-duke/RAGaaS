print("Starting...")
import spacy
print("Imported spacy")
try:
    nlp = spacy.load("ko_core_news_sm")
    print("Loaded model")
except Exception as e:
    print(f"Error loading model: {e}")
    exit(1)

def clean_text(text):
    doc = nlp(text)
    last_token = doc[-1]
    
    # Heuristic 1: Check tags
    tags = last_token.tag_.split('+')
    has_josa = any(t.startswith('j') for t in tags)
    
    if has_josa:
        parts = last_token.lemma_.split('+')
        if len(parts) > 1:
             return "".join(parts[:-1])
    
    # Heuristic 2: Suffix
    josas = ['의', '은', '는', '이', '가', '을', '를', '에', '와', '과', '로', '으로', '에서', '에게', '께', '부터', '까지']
    if last_token.pos_ in ['NOUN', 'PROPN', 'NUM']:
        for josa in josas:
             if last_token.text.endswith(josa) and len(last_token.text) > len(josa):
                 return text[:-len(josa)] # Strip from full text end
                 
    return text

samples = ["시즌 2의", "애플의", "아이폰을", "집에서", "서울로", "학교에", "우리가", "시즌 2", "버스"]
for s in samples:
    cleaned = clean_text(s)
    print(f"Input: {s} -> Clean: {cleaned}")

