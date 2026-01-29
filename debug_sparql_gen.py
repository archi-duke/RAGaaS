
import sys
import os
import asyncio

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

# Import settings and generator
try:
    from app.core.config import settings
    from app.doc2onto.qa.sparql_generator import SPARQLGenerator
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

async def main():
    print("Initializing SPARQLGenerator...")
    
    if not settings.OPENAI_API_KEY:
        print("Warning: OPENAI_API_KEY not found in settings.")
        
    generator = SPARQLGenerator(api_key=settings.OPENAI_API_KEY)
    question = "성기훈의 스승의 스승은 누구야?"
    
    print(f"\n--- 1. Generating SPARQL for: {question} ---")
    try:
        # Intentionally using the same params as FusekiBackend
        result = generator.generate(
            question=question, 
            context="Entities: 성기훈",
            mode="ontology",
            inverse_relation="auto"
        )
    except Exception as e:
        print(f"Generation failed: {e}")
        return

    sparql_query = result.get("sparql")
    thought = result.get("thought")
    
    print(f"Thought: {thought}")
    print(f"Generated SPARQL:\n{sparql_query}")

if __name__ == "__main__":
    asyncio.run(main())
