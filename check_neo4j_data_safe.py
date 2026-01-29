
import os
import sys
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password")

def check_data():
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            driver.verify_connectivity()
            print("Successfully connected to Neo4j.")
            
            # Check for '스승' relationship
            # Using parameters to avoid injection/escaping issues, though strictly not needed for simple check
            query = "MATCH (n)-[r:`스승`]->(m) RETURN n.label_ko, m.label_ko LIMIT 5"
            print(f"Checking for '스승' relationships...")
            records, summary, keys = driver.execute_query(query)
            if not records:
                print("No '스승' relationships found.")
            else:
                for r in records:
                    print(f"Found: {r['n.label_ko']} -> 스승 -> {r['m.label_ko']}")

            # Check for 'Duke' entity
            query_duke = "MATCH (n:Entity) WHERE n.label_ko CONTAINS 'Duke' RETURN n"
            print(f"\nChecking for 'Duke' entity...")
            records_duke, _, _ = driver.execute_query(query_duke)
            if not records_duke:
                 print("No 'Duke' entity found.")
            else:
                 print(f"Found Duke: {len(records_duke)} records")
                 for r in records_duke:
                     print(f" - {r['n']}")

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    check_data()
