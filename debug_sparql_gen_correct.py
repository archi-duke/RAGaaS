
import sys
import os
import asyncio
import urllib.parse

# Setup Paths:
# 1. RAGaaS/backend
sys.path.append(os.path.join(os.getcwd(), 'backend'))

# 2. Doc2Onto (Assuming it is at ../Doc2Onto relative to RAGaaS root)
doc2onto_path = os.path.abspath(os.path.join(os.getcwd(), '..', 'Doc2Onto'))
if os.path.exists(doc2onto_path):
    sys.path.append(doc2onto_path)
else:
    print(f"Warning: Doc2Onto path not found at {doc2onto_path}")

try:
    from app.core.config import settings
    # Override Fuseki URL for local execution
    settings.FUSEKI_URL = "http://localhost:3030"
    
    from app.core.fuseki import fuseki_client
    from doc2onto.qa.sparql_generator import SPARQLGenerator
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

async def main():
    print("Initializing SPARQLGenerator...")
    
    if not settings.OPENAI_API_KEY:
        print("Warning: OPENAI_API_KEY not found in settings.")
        
    generator = SPARQLGenerator(api_key=settings.OPENAI_API_KEY)
    
    # Use the same question
    question = "성기훈의 스승의 스승은 누구야?"
    kb_id = "fe5ef020-a2f7-425d-883d-5f8982c6320c" # test2
    
    print(f"\n--- 1. Generating SPARQL for: {question} ---")
    
    # Locate the module file and copy it
    try:
        import doc2onto.qa.sparql_generator
        module_file = doc2onto.qa.sparql_generator.__file__
        print(f"DEBUG: Found SPARQLGenerator source at: {module_file}")
        
        dest_path = os.path.join(os.getcwd(), 'backend/app/doc2onto/qa/sparql_generator.py')
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        with open(module_file, 'r') as rf:
            content = rf.read()
        with open(dest_path, 'w') as wf:
            wf.write(content)
        print(f"DEBUG: Successfully copied to {dest_path}")
        
    except Exception as e:
        print(f"DEBUG: Failed to copy module file: {e}")

    try:
        # Generate with inverse_relation='auto'
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
    
    if not sparql_query:
        print("No SPARQL query generated.")
        return
        
    print(f"\n--- 2. Executing against Fuseki ({settings.FUSEKI_URL}) ---")
    # Inject UnionGraph if needed (Doc2Onto usually needs it to search across named graphs)
    if "WHERE" in sparql_query and "FROM" not in sparql_query:
        sparql_query = sparql_query.replace("WHERE", "FROM <urn:x-arq:UnionGraph>\nWHERE", 1)
        
    # Add prefixes just in case generator didn't include all
    prefixes = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    """
    if "PREFIX" not in sparql_query:
        full_query = prefixes + sparql_query
    else:
        full_query = sparql_query
        
    try:
        results = fuseki_client.query_sparql(kb_id, full_query)
        bindings = results.get("results", {}).get("bindings", [])
        
        print(f"Found {len(bindings)} bindings.")
        print("\n[Result Triples]")
        
        # Visualize as triples
        # We try to extract s, p, o or whatever variables are returned
        for binding in bindings:
            # If the query returns ?s ?p ?o, print as triple
            # If it returns ?answer, print as (Question, hasAnswer, ?answer)
            
            row_parts = []
            for var, val_dict in binding.items():
                val = val_dict['value']
                # Simplify display
                display_val = val.split('/')[-1].split('#')[-1]
                row_parts.append(f"{var}: {display_val}")
            
            print(", ".join(row_parts))
            
    except Exception as e:
        print(f"Execution failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
