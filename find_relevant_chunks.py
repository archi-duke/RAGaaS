from pymilvus import connections, Collection

connections.connect(host='localhost', port='19530')

kb_id = 'd2980afe-3238-4d34-854d-400bb3937bb9'
collection_name = f"kb_{kb_id.replace('-', '_')}"

collection = Collection(collection_name)
collection.load()

doc_id = '1a815e61-64d0-46e4-bda1-f7de2775a3f8'

# Duke, 오일남, 성기훈이 모두 언급된 청크 찾기
keywords = ['Duke', '오일남', '성기훈', '스승', '제자']

results = collection.query(
    expr=f'doc_id == "{doc_id}"',
    output_fields=['chunk_id', 'content'],
    limit=20
)

print(f"Document has {len(results)} chunks\n")

relevant_chunks = []
for chunk in results:
    content = chunk['content']
    match_count = sum(1 for kw in keywords if kw in content)
    
    if match_count >= 2:  # 2개 이상 키워드 매칭
        relevant_chunks.append((chunk['chunk_id'], match_count, content[:200]))

print(f"Found {len(relevant_chunks)} relevant chunks:\n")
for cid, count, preview in sorted(relevant_chunks, key=lambda x: -x[1]):
    print(f"Chunk: {cid.split('_')[-1]}, Matches: {count}")
    print(f"Preview: {preview}\n")
