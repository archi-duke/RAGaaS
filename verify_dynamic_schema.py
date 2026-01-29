import asyncio
import os
import sys
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
# Try to find .env in current or parent dirs if standard load_dotenv doesn't work
load_dotenv()

# Add backend directory to path so 'app' module can be found
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.services.retrieval.sparql_generator import SPARQLGenerator
from app.core.config import settings

async def test_dynamic_schema():
    print("--- Environment Check ---")
    api_key = settings.OPENAI_API_KEY
    if api_key:
        print(f"OPENAI_API_KEY: {api_key[:10]}... (Loaded)")
    else:
        print("OPENAI_API_KEY: Not Found! Check .env file.")
        # Try manual load if empty
        if not api_key and os.path.exists(".env"):
             print("Reading .env manually...")
             with open(".env") as f:
                 for line in f:
                     if line.startswith("OPENAI_API_KEY"):
                         os.environ["OPENAI_API_KEY"] = line.split("=")[1].strip().replace('"', '')
                         print("Manually loaded API Key.")
    
    fuseki_url = settings.FUSEKI_URL
    print(f"FUSEKI_URL: {fuseki_url}")
    
    # Check Fuseki Connection and Datasets
    ds_names = []
    try:
        print(f"Connecting to {fuseki_url}/$/datasets ...")
        resp = requests.get(f"{fuseki_url}/$/datasets", auth=("admin", "admin"), timeout=5)
        if resp.status_code == 200:
            datasets = resp.json().get("datasets", [])
            ds_names = [d["ds.name"] for d in datasets]
            print(f"Available Fuseki Datasets ({len(ds_names)}): {ds_names}")
        else:
            print(f"Failed to list datasets: {resp.status_code}")
    except Exception as e:
        print(f"Fuseki Connection Error: {e}")
        return

    print("\n--- Initializing SPARQLGenerator ---")
    # Re-import to pick up env var changes if any
    from app.services.retrieval.sparql_generator import SPARQLGenerator
    generator = SPARQLGenerator()
    
    # KB_ID selection
    kb_id = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1" # Default test target
    safe_name = f"/kb_{kb_id.replace('-', '_')}"
    
    # Check if target dataset exists
    if safe_name not in ds_names:
        print(f"WARNING: Target dataset based on KB ID '{safe_name}' not found in Fuseki.")
        # Try to pick one if available
        candidates = [n for n in ds_names if n.startswith("/kb_")]
        if candidates:
            picked = candidates[0]
            kb_id = picked.replace("/kb_", "").replace("_", "-")
            print(f"Falling back to existing dataset: {picked} -> {kb_id}")
        else:
            print("No KB datasets found. Cannot proceed with schema fetch.")
            return
            
    print(f"Testing Schema Fetch for KB: {kb_id}")
    schema = generator._fetch_fuseki_schema(kb_id)
    
    if schema:
        print("\n[Fetched Schema]")
        print(f"Predicates ({len(schema['predicates'])}): {schema['predicates'][:10]}")
        print(f"Classes ({len(schema['classes'])}): {schema['classes'][:10]}")
        
        if not schema['predicates']:
            print("Warning: Predicate list is empty. Is the graph populated?")
        
        # Test Generate
        print("\nTesting Generate with Dynamic Schema...")
        question = "장풍을 사용하는 참가자는?"
        
        entities = ["장풍"]
        
        result = generator.generate(
            question=question,
            entities=entities,
            kb_id=kb_id,
            use_dynamic_schema=True
        )
        
        print("\n[Generation Result]")
        if result.get("sparql"):
            print("SPARQL Generated Successfully:")
            print(result.get("sparql"))
            
            # Check for injected predicates
            found_preds = [p for p in schema['predicates'] if p in result.get("sparql")]
            if found_preds:
                print(f"[SUCCESS] Generated SPARQL uses dynamic predicates: {found_preds}")
            else:
                print("[WARNING] Generated SPARQL does NOT use dynamic predicates.")
        else:
            print(f"Generation Failed: {result}")
        
    else:
        print("Failed to fetch schema.")

if __name__ == "__main__":
    asyncio.run(test_dynamic_schema())
