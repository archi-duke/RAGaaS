import asyncio
from app.core.database import init_db
from app.models.document import Document

async def check_doc_status():
    await init_db()
    # Find the most recent document
    doc = await Document.find().sort("-created_at").limit(1).to_list()
    if doc:
        d = doc[0]
        print(f"ID: {d.id}")
        print(f"Status (Legacy): {d.status}")
        print(f"Doc Status (New): {d.doc_status}")
        print(f"Process Step: {d.process_step}")
        print(f"Extractor Type: {d.extractor_type}")
        print(f"Processing Metadata Keys: {list(d.processing_metadata.keys()) if d.processing_metadata else 'None'}")
    else:
        print("No documents found.")

if __name__ == "__main__":
    asyncio.run(check_doc_status())
