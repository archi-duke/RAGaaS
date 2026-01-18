
import sqlite3
import os

db_path = "backend/rag_system.db"
doc_id_part = "d16b3e2-c86c-4549-8b23-2d07eb3e13c9"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    # Search in documents table
    cursor.execute("SELECT id, kb_id FROM documents WHERE id = ?", (doc_id_part,))
    row = cursor.fetchone()
    if row:
        print(f"Found Document! ID: {row[0]}, KB_ID: {row[1]}")
    else:
        print(f"Document {doc_id_part} not found in DB.")
        
        # List all documents to check prefix
        cursor.execute("SELECT id, kb_id FROM documents LIMIT 5")
        print("\nSample Documents:")
        for r in cursor.fetchall():
            print(f"Doc: {r[0]} -> KB: {r[1]}")

except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
