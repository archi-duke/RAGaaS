import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings
from app.models.prompt import PromptTemplate

async def import_prompts():
    print("Connecting to MongoDB...")
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(database=client[settings.MONGO_DB], document_models=[PromptTemplate])
    
    prompts_dir = Path("data/prompts")
    if not prompts_dir.exists():
        prompts_dir = Path("../data/prompts") # Try relative path if run from scripts dir
        if not prompts_dir.exists():
            print(f"Prompts directory not found at {prompts_dir.absolute()}")
            return

    print(f"Scanning prompts in {prompts_dir.absolute()}...")
    
    count = 0
    for file_path in prompts_dir.glob("*.txt"):
        name = file_path.stem
        content = file_path.read_text(encoding="utf-8")
        
        # Determine strict type based on filename
        p_type = "general"
        if "sparql" in name:
            p_type = "sparql"
        elif "cypher" in name:
            p_type = "cypher"
        elif "rerank" in name:
            p_type = "rerank"
        elif "extraction" in name:
            p_type = "extraction"
            
        print(f"Importing {name} (Type: {p_type})...")
        
        # Upsert
        existing = await PromptTemplate.find_one(PromptTemplate.name == name)
        if existing:
            existing.content = content
            existing.type = p_type
            existing.updated_at = existing.updated_at # Should update timestamp
            await existing.save()
            print(f"  -> Updated.")
        else:
            new_prompt = PromptTemplate(
                name=name,
                content=content,
                type=p_type
            )
            await new_prompt.insert()
            print(f"  -> Created.")
        count += 1
            
    print(f"Done. Imported/Updated {count} prompts.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(import_prompts())
