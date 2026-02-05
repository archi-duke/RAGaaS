import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from uuid import UUID

async def update_kb_prompt():
    uri = os.environ.get('MONGO_URI', 'mongodb://root:example@mongo:27017')
    client = AsyncIOMotorClient(uri)
    db = client['ragaas']
    
    # List KBs to find the correct one
    print("--- Listing KBs ---")
    async for kb in db.knowledge_bases.find():
        kbid = kb.get('id')
        name = kb.get('name')
        print(f"Found KB: name='{name}', id='{kbid}' (type: {type(kbid)})")
        
        # Target KB Check (using string comparison)
        if str(kbid) == '4ba60b29-cfd3-4c04-969a-bfa64d6a46e1':
            print(f"==> MATCH FOUND: {name}")
            
            # Read prompt file
            try:
                with open('/app/data/prompts/sparql_vibe_prompt.txt', 'r', encoding='utf-8') as f:
                    vibe_content = f.read()
            except FileNotFoundError:
                # Fallback path for local execution context vs docker
                vibe_content = "PREFIX ..." 
                print("Warning: Prompt file not found in path, skipping update content.")

            if vibe_content:
                # Update
                res = await db.knowledge_bases.update_one(
                    {'_id': kb['_id']},
                    {'$set': {'sparql_prompt_template': vibe_content}}
                )
                print(f"Update Result: matched={res.matched_count}, modified={res.modified_count}")
                
asyncio.run(update_kb_prompt())
