import sys
import os
import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv("/Users/dukekimm/Works/RAGaaS/.env")

# Add Doc2Onto to path
sys.path.append('/Users/dukekimm/Works/Doc2Onto')

try:
    from doc2onto.qa.sparql_generator import SPARQLGenerator
except ImportError:
    sys.path.append('/Users/dukekimm/Works/Doc2Onto/doc2onto/qa')
    try:
        from sparql_generator import SPARQLGenerator
    except ImportError:
        print("Could not import SPARQLGenerator.")
        sys.exit(1)

def query_fuseki(sparql_query, dataset_name):
    fuseki_url = f"http://localhost:3030/{dataset_name}/sparql"
    
    # Enable Union Graph to search across all Named Graphs
    params = {
        'default-graph-uri': 'urn:x-arq:UnionGraph'
    }
    
    try:
        response = requests.post(fuseki_url, params=params, data={'query': sparql_query})
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Fuseki Query Error: {e}")
        try:
            print("Response:", response.text)
        except:
            pass
        return None

def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not found in .env")
        try:
            with open("/Users/dukekimm/Works/RAGaaS/.env") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY"):
                        api_key = line.split("=")[1].strip().strip('"')
                        break
        except:
            pass
            
    if not api_key:
        print("CRITICAL: Could not find OPENAI_API_KEY.")
        return

    # Check validation query first to see if entities exist
    dataset_name = "kb_fe5ef020_a2f7_425d_883d_5f8982c6320c"
    print(f"--- Checking for '성기훈' in dataset {dataset_name} ---")
    check_query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?s ?label WHERE {
        ?s rdfs:label ?label .
        FILTER(CONTAINS(str(?label), "성기훈") || CONTAINS(str(?label), "Seong"))
    } LIMIT 10
    """
    check_result = query_fuseki(check_query, dataset_name)
    if check_result:
        bindings = check_result.get('results', {}).get('bindings', [])
        if bindings:
            print("Found related entities:")
            for row in bindings:
                 print(f" - {row.get('label', {}).get('value')} ({row.get('s', {}).get('value')})")
        else:
            print("Warning: '성기훈' or 'Seong' related entities not found in graph.")

    question = "성기훈의 스승의 스승은 누구야?"
    print(f"\n--- Question: {question} ---")

    generator = SPARQLGenerator(api_key=api_key, llm_model="gpt-4o-mini") 
    
    try:
        result = generator.generate(question, mode="ontology")
        print("\n[Generation Result]")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        sparql_query = result.get('sparql')
        if not sparql_query:
            print("No SPARQL query generated.")
            return

        print(f"\n[Executing on Fuseki]")
        
        # Prepend standard prefixes if missing
        prefixes = """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        """
        full_query = prefixes + sparql_query
        
        fuseki_result = query_fuseki(full_query, dataset_name)
        
        if fuseki_result:
            print("\n[Fuseki Result]")
            bindings = fuseki_result.get('results', {}).get('bindings', [])
            if not bindings:
                 print("No results found.")
            else:
                for row in bindings:
                    simple_row = {k: v['value'] for k, v in row.items()}
                    print(simple_row)

    except Exception as e:
        print(f"Error during execution: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
