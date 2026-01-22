import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from bson import ObjectId

async def inspect_kb():
    uri = os.environ.get('MONGO_URI', 'mongodb://root:example@mongo:27017')
    client = AsyncIOMotorClient(uri)
    db = client['ragaas']
    
    print("--- Inspecting KBs ---")
    async for kb in db.knowledge_bases.find():
        print(f"Name: {kb.get('name')}")
        print(f"_id: {kb.get('_id')} (type: {type(kb.get('_id'))})")
        print(f"Keys: {list(kb.keys())}")
        print("-" * 20)

        # Target Check (name='test jf')
        if kb.get('name') == 'test jf':
            print("==> TARGET FOUND (test jf)")
            
            # Read Prompt
            with open('/app/data/prompts/sparql_vibe_prompt.txt', 'r', encoding='utf-8') as f:
                vibe_content = f.read()
            
            # Update
            res = await db.knowledge_bases.update_one(
                {'_id': kb['_id']},
                {'$set': {'sparql_prompt_template': vibe_content}}
            )
            print(f"✅ Updated 'test jf' prompt. Modified: {res.modified_count}")

asyncio.run(inspect_kb())
