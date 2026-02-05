
import sqlite3
import os

DB_PATH = 'backend/data/rag_system.db'

def check_db():
    if not os.path.exists(DB_PATH):
        print("Database file does not exist.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check knowledge_bases table
        try:
            cursor.execute("SELECT count(*) FROM knowledge_bases")
            count = cursor.fetchone()[0]
            print(f"Knowledge Bases count: {count}")
            
            if count > 0:
                cursor.execute("SELECT name FROM knowledge_bases")
                names = cursor.fetchall()
                print("Existing KBs:", [n[0] for n in names])
        except sqlite3.OperationalError:
            print("Table 'knowledge_bases' does not exist.")
            
        conn.close()
    except Exception as e:
        print(f"Error reading database: {e}")

if __name__ == "__main__":
    check_db()
