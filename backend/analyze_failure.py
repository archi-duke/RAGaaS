import spacy

# Mock the normalization logic from spacy_processor.py
def normalize_entity(span):
    if not span: return ""
    end_idx = span.end
    while end_idx > span.start:
        last_token = span.doc[end_idx - 1]
        if last_token.pos_ in ['ADP', 'PART', 'PUNCT']:
            end_idx -= 1
        else:
            break
    if end_idx == span.start: return ""
    
    last_token = span.doc[end_idx - 1]
    clean_last = last_token.text
    normalized = False
    
    # Heuristic for Person Names
    is_person = span.label_ == "PERSON"
    
    if '+' in last_token.lemma_:
        parts = last_token.lemma_.split('+')
        # Simplified simulation of logic
        pass

    josas = ['의', '은', '는', '이', '가', '을', '를', '에', '와', '과', '로', '으로', '에서', '에게', '께', '부터', '까지', '도', '만', '이랑', '랑']
    josas.sort(key=len, reverse=True)
    
    for josa in josas:
        if clean_last.endswith(josa):
            stem = clean_last[:-len(josa)]
            if len(stem) < 1: continue
            if is_person and len(stem) < 2: continue
            clean_last = stem
            normalized = True
            break
            
    if end_idx - 1 > span.start:
        prefix = span.doc[span.start:end_idx-1].text_with_ws
        return (prefix + clean_last).strip()
    else:
        return clean_last.strip()

nlp = spacy.load("ko_core_news_sm")
text = "시즌 2의 대부분 동안 오영일로 변장하여 플레이어 001로 변장한 후"
doc = nlp(text)

print(f"Text: {text}")
print("--- NER Results ---")
found = False
for ent in doc.ents:
    norm = normalize_entity(ent)
    print(f"Entity: '{ent.text}' ({ent.label_}) -> Normalized: '{norm}'")
    if "오영일" in norm:
        found = True

print("-" * 20)
print("--- Token Analysis ---")
for token in doc:
    print(f"{token.text}\t{token.pos_}\t{token.tag_}")

if not found:
    print("\nCONCLUSION: '오영일' was NOT detected as a named entity by the default spaCy model.")
else:
    print("\nCONCLUSION: '오영일' WAS detected.")
