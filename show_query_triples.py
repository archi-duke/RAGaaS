
import sys
import os
import asyncio
from neo4j import GraphDatabase

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

# Import settings and generator
try:
    from app.core.config import settings
    from app.doc2onto.qa.cypher_generator import CypherGenerator
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

# Neo4j connection
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password")

async def main():
    print("Initializing CypherGenerator...")
    
    generator = CypherGenerator(api_key=settings.OPENAI_API_KEY)
    question = "성기훈의 스승의 스승은 누구야?"
    
    print(f"\n--- 1. Generating Query for: {question} ---")
    try:
        result = generator.generate(question, context=None)
    except Exception as e:
        print(f"Generation failed: {e}")
        return

    cypher_query = result.get("cypher")
    thought = result.get("thought")
    
    print(f"Thought: {thought}")
    print(f"Generated Cypher: {cypher_query}")
    
    if not cypher_query:
        print("Failed to generate query.")
        return

    print(f"\n--- 2. Executing Visualization ---")
    
    if "RETURN" in cypher_query:
        # Extract MATCH clause and RETURN * to get Nodes
        match_clause = cypher_query.split("RETURN")[0].strip()
        visual_query = f"{match_clause} RETURN *"
        print(f"Visual Query: {visual_query}")
        
        try:
            with GraphDatabase.driver(URI, auth=AUTH) as driver:
                records, _, _ = driver.execute_query(visual_query)
                print(f"\nFound {len(records)} path records.")
                
                print("\n[Extracted Triples from Path]")
                for i, record in enumerate(records):
                    # Attempt to extract 'n', 'm', 'o' pattern
                    # If variables are n, m, o, we can reconstruct the path
                    
                    n_node = record.get('n')
                    m_node = record.get('m')
                    o_node = record.get('o')
                    
                    if n_node and m_node:
                        n_label = n_node.get('label_ko') or n_node.get('name')
                        m_label = m_node.get('label_ko') or m_node.get('name')
                        print(f"1. ({n_label}) -[스승]-> ({m_label})")
                        
                    if m_node and o_node:
                        m_label = m_node.get('label_ko') or m_node.get('name')
                        o_label = o_node.get('label_ko') or o_node.get('name')
                        print(f"2. ({m_label}) -[스승]-> ({o_label})")
                        
                    # Fallback: Print all nodes
                    if not (n_node and m_node and o_node):
                        print(f"Record {i+1} Nodes:")
                        for key in record.keys():
                             node = record[key]
                             if hasattr(node, 'get'):
                                 print(f" - {key}: {node.get('label_ko') or node.get('name')}")
                                 
        except Exception as e:
            print(f"Error executing visual query: {e}")
    else:
        print("Query format not supported for auto-visualization.")

if __name__ == "__main__":
    asyncio.run(main())
