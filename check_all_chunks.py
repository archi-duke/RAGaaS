from pymilvus import connections, Collection

connections.connect(host='localhost', port='19530')

kb_id = 'd2980afe-3238-4d34-854d-400bb3937bb9'
collection_name = f"kb_{kb_id.replace('-', '_')}"

collection = Collection(collection_name)
collection.load()

doc_id = '1a815e61-64d0-46e4-bda1-f7de2775a3f8'

# 이 문서의 모든 청크 조회
results = collection.query(
    expr=f'doc_id == "{doc_id}"',
    output_fields=['chunk_id', 'content'],
    limit=20
)

print(f"Total chunks: {len(results)}")
for i, chunk in enumerate(results):
    content = chunk['content']
    chunk_id = chunk['chunk_id']
    
    # "오일남", "Duke", "스승", "제자" 키워드 체크
    has_keyword = any(kw in content for kw in ['오일남', 'Duke', '스승', '제자'])
    
    print(f"\n{'='*60}")
    print(f"Chunk {i}: {chunk_id}")
    print(f"Has keywords: {has_keyword}")
    if has_keyword:
        print(f"Content preview: {content[:300]}")
