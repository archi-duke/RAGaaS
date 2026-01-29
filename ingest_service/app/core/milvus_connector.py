"""
Milvus Vector Store Connector

기존 RAGaaS의 Milvus 컬렉션에 벡터를 저장합니다.
"""
from typing import List, Dict, Any, Optional
from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
)

from app.core.config import settings


class MilvusConnector:
    """Milvus Vector Store Connector"""
    
    def __init__(self):
        self.host = settings.MILVUS_HOST
        self.port = settings.MILVUS_PORT
        self._connected = False
    
    def connect(self):
        """Milvus 연결"""
        if not self._connected:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port
            )
            self._connected = True
    
    def get_or_create_collection(self, kb_id: str) -> Collection:
        """KB별 컬렉션 가져오기 또는 생성"""
        self.connect()
        
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        
        if utility.has_collection(collection_name):
            return Collection(collection_name)
        
        # Create collection schema (RAGaaS 기존 스키마와 호환)
        fields = [
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128, is_primary=True),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="metadata", dtype=DataType.JSON),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=1536),  # OpenAI embedding dim
        ]
        
        schema = CollectionSchema(fields=fields, description=f"KB {kb_id}")
        collection = Collection(name=collection_name, schema=schema)
        
        # Create index for vector field
        index_params = {
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 16, "efConstruction": 256}
        }
        collection.create_index(field_name="vector", index_params=index_params)
        
        return collection
    
    async def insert_chunks(
        self,
        kb_id: str,
        doc_id: str,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]]
    ) -> int:
        """청크 및 벡터 삽입"""
        collection = self.get_or_create_collection(kb_id)
        
        # Prepare data
        doc_ids = [doc_id] * len(chunks)
        # node_id가 있으면 사용, 없으면 기존 방식 (doc_id_index)
        chunk_ids = []
        for i, chunk in enumerate(chunks):
            node_id = chunk.get("node_id")
            if node_id:
                chunk_ids.append(node_id)
            else:
                chunk_ids.append(f"{doc_id}_{i}")
        
        contents = [chunk.get("content", chunk.get("text", "")) for chunk in chunks]
        metadatas = [chunk.get("metadata", {}) for chunk in chunks]
        
        data = [doc_ids, chunk_ids, contents, metadatas, embeddings]
        
        # Insert
        print(f"[Milvus] Inserting {len(chunk_ids)} chunks for doc {doc_id} into {collection.name}...")
        collection.insert(data)
        print(f"[Milvus] Flushing data...")
        collection.flush()
        print(f"[Milvus] ✅ Inserted {len(chunks)} chunks.")
        
        return len(chunks)
    
    async def delete_by_doc_id(self, kb_id: str, doc_id: str) -> int:
        """문서 ID로 청크 삭제"""
        collection = self.get_or_create_collection(kb_id)
        
        expr = f'doc_id == "{doc_id}"'
        result = collection.delete(expr)
        collection.flush()
        
        return result.delete_count if hasattr(result, 'delete_count') else 0


# Singleton
milvus_connector = MilvusConnector()
