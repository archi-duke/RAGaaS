
import sqlite3
import os

# Try both potential paths
paths = [
    "/Users/dukekimm/Works/RAGaaS/backend/data/rag_system.db",
    "/Users/dukekimm/Works/RAGaaS/backend/rag_system.db",
     "/Users/dukekimm/Works/RAGaaS/rag_system.db"
]

found = False
for db_path in paths:
    if os.path.exists(db_path):
        print(f"Checking DB at: {db_path}")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, graph_backend, created_at FROM knowledge_bases")
            rows = cursor.fetchall()
            print(f"Found {len(rows)} KB entries.")
            for row in rows:
                print(f"ID: {row[0]}, Name: {row[1]}, Backend: {row[2]}")
                if row[1] == "test2":
                    print(f"MATCH FOUND! ID: {row[0]}")
            conn.close()
            found = True
        except Exception as e:
            print(f"Error reading {db_path}: {e}")
            
if not found:
    print("No database files found in checked paths.")
