"""Milvus 로더"""

import json
from pathlib import Path
from typing import Union, Optional,  Optional, Union, Generator


class MilvusLoader:
    """Milvus에 청크 적재"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        collection: str = "doc2onto_chunks",
    ):
        """
        Args:
            host: Milvus 호스트
            port: Milvus 포트
            collection: 컬렉션 이름
        """
        self.host = host
        self.port = port
        self.collection = collection
        self._client = None
    
    @property
    def uri(self) -> str:
        return f"{self.host}:{self.port}"
    
    def connect(self, dry_run: bool = False) -> dict:
        """Milvus 연결
        
        Args:
            dry_run: True면 실제 연결 없이 반환
        """
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Dry-run: would connect to {self.uri}",
            }
        
        try:
            from pymilvus import connections
            connections.connect(host=self.host, port=self.port)
            return {
                "success": True,
                "message": f"Connected to {self.uri}",
            }
        except ImportError:
            return {
                "success": False,
                "message": "pymilvus not installed",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {e}",
            }
    
    def create_collection(self, dim: int = 768, dry_run: bool = False) -> dict:
        """컬렉션 생성
        
        Args:
            dim: 임베딩 차원
            dry_run: True면 실제 생성 없이 반환
        """
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Dry-run: would create collection '{self.collection}' with dim={dim}",
            }
        
        try:
            from pymilvus import (
                Collection, FieldSchema, CollectionSchema, DataType
            )
            
            fields = [
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="doc_ver", dtype=DataType.VARCHAR, max_length=32),
                FieldSchema(name="chunk_idx", dtype=DataType.INT64),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="chunk_hash", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="section_path", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
            ]
            
            schema = CollectionSchema(fields=fields, description="Doc2Onto RAG chunks")
            collection = Collection(name=self.collection, schema=schema)
            
            return {
                "success": True,
                "message": f"Collection '{self.collection}' created",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Collection creation failed: {e}",
            }
    
    def _iter_jsonl(self, jsonl_path: Path) -> Generator[dict, None, None]:
        """JSONL 파일 순회"""
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
    
    def load(
        self,
        chunks_path: Union[str, Path],
        embedding_fn=None,
        batch_size: int = 100,
        dry_run: bool = False,
    ) -> dict:
        """청크 적재
        
        Args:
            chunks_path: chunks.jsonl 파일 경로
            embedding_fn: 임베딩 함수 (text -> list[float])
            batch_size: 배치 크기
            dry_run: True면 실제 적재 없이 반환
            
        Returns:
            적재 결과
        """
        chunks_path = Path(chunks_path)
        
        if not chunks_path.exists():
            return {
                "success": False,
                "message": f"File not found: {chunks_path}",
            }
        
        # 레코드 수 카운트
        total = 0
        for _ in self._iter_jsonl(chunks_path):
            total += 1
        
        if dry_run or embedding_fn is None:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Dry-run: would load {total} chunks to {self.collection}",
                "total_chunks": total,
                "file": str(chunks_path),
            }
        
        try:
            from pymilvus import Collection
            
            collection = Collection(self.collection)
            loaded = 0
            batch = []
            
            for record in self._iter_jsonl(chunks_path):
                # 임베딩 생성
                embedding = embedding_fn(record["text"])
                record["embedding"] = embedding
                batch.append(record)
                
                if len(batch) >= batch_size:
                    collection.insert(batch)
                    loaded += len(batch)
                    batch = []
            
            if batch:
                collection.insert(batch)
                loaded += len(batch)
            
            return {
                "success": True,
                "message": f"Loaded {loaded} chunks to {self.collection}",
                "total_loaded": loaded,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Load failed: {e}",
            }
    
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        dry_run: bool = False,
    ) -> dict:
        """벡터 검색
        
        Args:
            query_embedding: 쿼리 임베딩
            top_k: 반환할 결과 수
            dry_run: True면 실제 검색 없이 반환
        """
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Dry-run: would search top-{top_k} in {self.collection}",
            }
        
        try:
            from pymilvus import Collection
            
            collection = Collection(self.collection)
            collection.load()
            
            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"nprobe": 10}},
                limit=top_k,
                output_fields=["chunk_id", "text", "doc_id", "section_path"],
            )
            
            hits = []
            for hit in results[0]:
                hits.append({
                    "chunk_id": hit.entity.get("chunk_id"),
                    "text": hit.entity.get("text"),
                    "doc_id": hit.entity.get("doc_id"),
                    "section_path": hit.entity.get("section_path"),
                    "score": hit.score,
                })
            
            return {
                "success": True,
                "hits": hits,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Search failed: {e}",
            }
