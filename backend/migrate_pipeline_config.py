"""
Migration script to add pipeline_config column to knowledge_bases table.
Run this inside the backend container or with the same database file.
"""
import sqlite3
import json

DB_PATH = "/app/data/rag_system.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(knowledge_bases)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'pipeline_config' not in columns:
        print("Adding pipeline_config column...")
        cursor.execute("""
            ALTER TABLE knowledge_bases 
            ADD COLUMN pipeline_config TEXT DEFAULT '{\"stages\": []}'
        """)
        conn.commit()
        print("Migration completed successfully!")
    else:
        print("Column pipeline_config already exists, skipping.")
    
    conn.close()

if __name__ == "__main__":
    migrate()
