
import sqlite3
import json

db_path = "backend/data/rag_system.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

kb_ids = [
    "298f7c64-5032-4f9e-930a-1e774c434759", # test
    "fe5ef020-a2f7-425d-883d-5f8982c6320c"  # test2
]

print(f"{'Name':<10} | {'Metric':<10} | {'Graph':<10} | {'Pipeline Config'}")
print("-" * 80)

for kb_id in kb_ids:
    cursor.execute("SELECT name, metric_type, graph_backend, pipeline_config FROM knowledge_bases WHERE id = ?", (kb_id,))
    row = cursor.fetchone()
    if row:
        pipeline = row['pipeline_config']
        # pipeline might be null or json string or json object depending on how library returned it, usually sqlite returns string/buffer but python adaptation might vary. 
        # But here straightforward fetch. Assume column type TEXT or JSON.
        
        print(f"{row['name']:<10} | {row['metric_type']:<10} | {row['graph_backend']:<10} | {pipeline}")
    else:
        print(f"KB {kb_id} not found")

conn.close()
