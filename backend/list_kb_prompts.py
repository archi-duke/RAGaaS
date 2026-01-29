from pymongo import MongoClient
import os

client = MongoClient("mongodb://root:example@mongo:27017")
db = client["ragaas"]

print("=== Knowledge Base Prompt Audit ===")
for kb in db["knowledge_bases"].find({}):
    name = kb.get("name", "Unknown")
    kb_id = kb.get("id", "No ID")
    
    custom_prompt = kb.get("promotion_metadata", {}).get("custom_prompt")
    template_prompt = kb.get("sparql_prompt_template")
    
    print(f"Name: {name}")
    print(f"ID: {kb_id}")
    
    if custom_prompt:
        print(f"  [FOUND] In promotion_metadata.custom_prompt (Len: {len(custom_prompt)})")
        print(f"  First 100 chars: {custom_prompt[:100].replace(chr(10), ' ')}...")
    else:
        print("  [NOT FOUND] In promotion_metadata.custom_prompt")
        
    if template_prompt:
        print(f"  [FOUND] In sparql_prompt_template (Len: {len(template_prompt)})")
        print(f"  First 100 chars: {template_prompt[:100].replace(chr(10), ' ')}...")
    else:
        print("  [NOT FOUND] In sparql_prompt_template")
    
    print("-" * 40)
