
import sqlite3
import os

# Database Path
DB_PATH = 'backend/data/rag_system.db'

def migrate_db():
    print(f"Checking database at {DB_PATH}...")
    
    if not os.path.exists(DB_PATH):
        print("Database file not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if column exists
    cursor.execute("PRAGMA table_info(knowledge_bases)")
    columns = [info[1] for info in cursor.fetchall()]

    if 'graph_backend' not in columns:
        print("Adding 'graph_backend' column to 'knowledge_bases' table...")
        try:
            cursor.execute("ALTER TABLE knowledge_bases ADD COLUMN graph_backend TEXT DEFAULT 'ontology'")
            conn.commit()
            print("Migration successful.")
        except Exception as e:
            print(f"Migration failed: {e}")
    else:
        print("'graph_backend' column already exists.")

    conn.close()

if __name__ == "__main__":
    migrate_db()
