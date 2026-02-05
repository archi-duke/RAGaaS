
import sqlite3
import os

db_path = "backend/rag_system.db"
if not os.path.exists(db_path):
    print("DB file not found")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    cursor.execute("SELECT id, name FROM knowledge_bases")
    rows = cursor.fetchall()
    for row in rows:
        print(f"ID: {row[0]}, Name: {row[1]}")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
