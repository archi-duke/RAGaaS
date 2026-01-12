import asyncio
import sys
import os
# Add path to import backend modules
sys.path.append('/app')

from app.services.ingestion.graph import GraphProcessor

async def test_extraction():
    print("--- Testing Graph Extraction Logic ---")
    
    processor = GraphProcessor()
    
    # Test Text
    text = "성기훈은 오일남의 제자이며, 오일남은 Duke의 스승이다."
    chunk_id = "test_chunk_001"
    
    print(f"Input Text: {text}")
    print("Running extraction...")
    
    # Run extraction (mocking config/client if needed, but here we run real LLM call)
    # The container has OPENAI_API_KEY so it should work.
    result = await processor.extract_graph_elements(text, chunk_id, "test_kb", {})
    triples = result.get("rdf_triples", [])

    
    print("\n--- Extracted Triples (Turtle format) ---")
    for t in triples:
        print(t)
        
    print("\n--- Validation ---")
    # Check for specific triples
    # 1. 성기훈 --제자--> 오일남 (성기훈 is Disciple of 오일남)
    # 2. 오일남 --스승--> 성기훈 (INVERSE: 오일남 is Teacher of 성기훈)
    # 3. 오일남 --스승--> Duke (오일남 is Teacher of Duke)
    # 4. Duke --제자--> 오일남 (INVERSE: Duke is Disciple of 오일남)
    
    # Simplified checks (using string matching since URIs are encoded)
    check_1 = any("성기훈" in t and "제자" in t and "오일남" in t for t in triples)
    check_2 = any("오일남" in t and "스승" in t and "성기훈" in t for t in triples)
    check_3 = any("오일남" in t and "스승" in t and "Duke" in t for t in triples)
    check_4 = any("Duke" in t and "제자" in t and "오일남" in t for t in triples)
    
    print(f"1. (성기훈, 제자, 오일남) Exists? {check_1}")
    print(f"2. [AUTO] (오일남, 스승, 성기훈) Exists? {check_2}")
    print(f"3. (오일남, 스승, Duke) Exists? {check_3}")
    print(f"4. [AUTO] (Duke, 제자, 오일남) Exists? {check_4}")

if __name__ == "__main__":
    asyncio.run(test_extraction())
