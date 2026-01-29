import sqlite3
import os

# DB 후보군
db_paths = [
    "backend/data/ragaas.db",
    "backend/rag.db",
    "backend/app.db"
]

def check_mapping(db_path):
    if not os.path.exists(db_path):
        return

    print(f"\nChecking DB: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 테이블 목록 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables: {tables}")
        
        if ('triple_chunk_mapping',) in tables:
            print("Found 'triple_chunk_mapping' table.")
            # chunk_id 별 카운트 조회
            cursor.execute("SELECT chunk_id, COUNT(*) FROM triple_chunk_mapping GROUP BY chunk_id")
            rows = cursor.fetchall()
            print("--- Mapping Statistics ---")
            for row in rows:
                print(f"Chunk ID: {row[0]} | Count: {row[1]}")
                
            # 샘플 데이터 조회
            cursor.execute("SELECT * FROM triple_chunk_mapping LIMIT 3")
            print("\n--- Sample Entries ---")
            for row in cursor.fetchall():
                print(row)
        
        conn.close()
    except Exception as e:
        print(f"Error reading {db_path}: {e}")

if __name__ == "__main__":
    for path in db_paths:
        check_mapping(os.path.abspath(path))
