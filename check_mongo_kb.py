import motor.motor_asyncio
import asyncio
import json

async def check_kb_pipeline():
    client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["ragaas"]
    kb = await db["knowledge_bases"].find_one({"id": "d2980afe-3238-4d34-854d-400bb3937bb9"})
    if kb:
        print(f"KB Name: {kb.get('name')}")
        pipeline = kb.get("pipeline_config", {})
        print("Pipeline Config:")
        print(json.dumps(pipeline, indent=2, ensure_ascii=False))
    else:
        print("KB not found.")

if __name__ == "__main__":
    asyncio.run(check_kb_pipeline())
