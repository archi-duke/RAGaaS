import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os

async def update_target_kb():
    uri = os.environ.get('MONGO_URI', 'mongodb://root:example@mongo:27017')
    client = AsyncIOMotorClient(uri)
    db = client['ragaas']
    
    # Read modified prompt file (from within docker path)
    prompt_path = '/app/data/prompts/sparql_vibe_prompt.txt'
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading prompt file: {e}")
        return

    # Update KB by name
    res = await db.knowledge_bases.update_many(
        {'name': 'test jf'},
        {'$set': {'sparql_prompt_template': content}}
    )
    print(f"Updated 'test jf': matched={res.matched_count}, modified={res.modified_count}")

if __name__ == '__main__':
    asyncio.run(update_target_kb())
