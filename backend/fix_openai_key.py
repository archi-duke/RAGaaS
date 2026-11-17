import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
import os
import sys

os.chdir('/Users/dukekimm/Works/RAGaaS/backend')

from app.models.provider import BuiltinProviderConfig
from app.core.config import settings
from app.core.encryption import encrypt

async def main():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(database=client[settings.MONGO_DB], document_models=[BuiltinProviderConfig])
    
    openai_key = None
    with open("../.env") as f:
        for line in f:
            if line.startswith("OPENAI_API_KEY="):
                openai_key = line.strip().split("=", 1)[1]
    
    if not openai_key:
        print("No OPENAI_API_KEY found")
        sys.exit(1)
        
    cfg = await BuiltinProviderConfig.find_one({"provider_id": "openai"})
    if not cfg:
        cfg = BuiltinProviderConfig(provider_id="openai")
        
    cfg.encrypted_key = encrypt(openai_key)
    await cfg.save()
    print("Successfully updated builtin openai key with new ENCRYPTION_KEY.")

if __name__ == "__main__":
    asyncio.run(main())
