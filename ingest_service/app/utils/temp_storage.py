"""
임시 파일 저장 관리 유틸리티 (수정됨: Raw Data 저장)

중간 처리 결과물(엔티티 사전, 청크, 트리플 등)을 백엔드 문서 저장소와 동일한 위치에 직접 저장합니다.
프론트엔드 호환성을 위해 Wrapper 포맷이 아닌 Raw Data 포맷으로 저장합니다.
"""
import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime


class TempStorage:
    """파일 저장 관리"""
    
    def __init__(self, base_path: str = None):
        # 기본 경로: 프로젝트 루트의 data/uploads (백엔드 저장소와 일치)
        if base_path is None:
            # ingest_service/app/utils/temp_storage.py -> ingest_service/ -> RAGaaS/
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            base_path = os.path.join(project_root, "data", "uploads")
        
        self.base_path = base_path
        try:
            os.makedirs(base_path, exist_ok=True)
            print(f"[TempStorage] Initialized with base_path: {base_path}")
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to create base_path {base_path}: {e}")
    
    def get_kb_path(self, kb_id: str) -> str:
        """지식 베이스(KB)별 저장 경로 반환"""
        path = os.path.join(self.base_path, kb_id)
        os.makedirs(path, exist_ok=True)
        return path
    
    # 하위 호환성을 위해 남겨두되, kb_path를 반환하도록 변경
    def get_doc_path(self, kb_id: str, doc_id: str) -> str:
        return self.get_kb_path(kb_id)
    
    def _get_file_path(self, kb_id: str, doc_id: str, suffix: str) -> str:
        """파일 전체 경로 생성 헬퍼"""
        path = self.get_kb_path(kb_id)
        filename = f"{doc_id}{suffix}"
        return os.path.join(path, filename)

    async def save_entity_dictionary(
        self, 
        kb_id: str, 
        doc_id: str, 
        dictionary: Dict[str, Any]
    ) -> str:
        """엔티티 사전 저장 (Raw Dict)"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_dictionary.json")
            
            # Wrapper 제거, Raw Dictionary 저장
            data = dictionary
            
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"[TempStorage] ✅ Saved entity dictionary: {file_path} ({len(dictionary)} entities)")
            return file_path
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to save entity dictionary: {e}")
            return ""
    
    async def save_chunks(
        self, 
        kb_id: str, 
        doc_id: str, 
        chunks: List[Dict[str, Any]]
    ) -> str:
        """청크 목록 저장 (Raw List)"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_chunks.json")
            
            # 청크 데이터를 간소화
            simplified_chunks = []
            for i, chunk in enumerate(chunks):
                simplified_chunks.append({
                    "index": i,
                    "content": chunk.get("content", ""),
                    "metadata": chunk.get("metadata", {}),
                    "node_id": chunk.get("node_id", "")
                })
            
            # 청크는 배열이므로 리스트로 저장
            data = simplified_chunks
            
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"[TempStorage] ✅ Saved chunks: {file_path} ({len(chunks)} chunks)")
            return file_path
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to save chunks: {e}")
            return ""
    
    async def save_triples(
        self, 
        kb_id: str, 
        doc_id: str, 
        triples: List[Dict[str, Any]]
    ) -> str:
        """트리플 목록 저장 (Raw List)"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_triples.json")
            
            # Raw Triples List 저장
            data = triples
            
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"[TempStorage] ✅ Saved triples: {file_path} ({len(triples)} triples)")
            return file_path
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to save triples: {e}")
            return ""
    
    async def save_metadata(
        self, 
        kb_id: str, 
        doc_id: str, 
        metadata: Dict[str, Any]
    ) -> str:
        """메타데이터 저장 (Raw Dict)"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_metadata.json")
            
            # 메타데이터에 생성일자만 추가하고 저장
            data = metadata.copy()
            if "created_at" not in data:
                data["created_at"] = datetime.utcnow().isoformat()
            
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"[TempStorage] ✅ Saved metadata: {file_path}")
            return file_path
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to save metadata: {e}")
            return ""
    
    async def load_entity_dictionary(self, kb_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
        """엔티티 사전 로드"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_dictionary.json")
            
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            print(f"[TempStorage] ✅ Loaded entity dictionary: {file_path}")
            # Raw 포맷이므로 바로 반환 (만약 wrapper라면 .get('dictionary') 등이 필요했음)
            return data
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to load entity dictionary: {e}")
            return None
    
    async def load_triples(self, kb_id: str, doc_id: str) -> Optional[List[Dict[str, Any]]]:
        """트리플 목록 로드"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_triples.json")
            
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            print(f"[TempStorage] ✅ Loaded triples: {file_path}")
            return data
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to load triples: {e}")
            return None
    
    async def save_embeddings(
        self,
        kb_id: str,
        doc_id: str,
        embeddings: Dict[str, List[float]]
    ) -> str:
        """임베딩 데이터 저장"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_embeddings.json")
            
            data = embeddings
            
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"[TempStorage] ✅ Saved embeddings: {file_path} ({len(embeddings)} embeddings)")
            return file_path
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to save embeddings: {e}")
            return ""
    
    async def load_embeddings(self, kb_id: str, doc_id: str) -> Optional[Dict[str, List[float]]]:
        """임베딩 데이터 로드"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_embeddings.json")
            
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            print(f"[TempStorage] ✅ Loaded embeddings: {file_path}")
            return data
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to load embeddings: {e}")
            return None
    
    async def load_chunks(self, kb_id: str, doc_id: str) -> Optional[List[Dict[str, Any]]]:
        """청크 목록 로드"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_chunks.json")
            
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            print(f"[TempStorage] ✅ Loaded chunks: {file_path}")
            return data
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to load chunks: {e}")
            return None
    
    async def load_metadata(self, kb_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
        """메타데이터 로드"""
        try:
            file_path = self._get_file_path(kb_id, doc_id, "_metadata.json")
            
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            print(f"[TempStorage] ✅ Loaded metadata: {file_path}")
            return data
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to load metadata: {e}")
            return None
    
    def get_file_path(self, kb_id: str, doc_id: str, filename: str):
        """특정 파일의 전체 경로 반환 (Path 객체)"""
        from pathlib import Path
        path = self.get_kb_path(kb_id)
        return Path(os.path.join(path, filename))
    
    async def cleanup(self, kb_id: str, doc_id: str):
        """임시 파일 정리"""
        try:
            suffixes = ["_dictionary.json", "_triples.json", "_chunks.json", "_metadata.json", "_embeddings.json"]
            path = self.get_kb_path(kb_id)
            for suffix in suffixes:
                file_path = os.path.join(path, f"{doc_id}{suffix}")
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"[TempStorage] Deleted: {file_path}")
            print(f"[TempStorage] ✅ Cleanup completed for doc {doc_id}")
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to cleanup: {e}")
    
    def exists(self, kb_id: str, doc_id: str) -> bool:
        """파일이 존재하는지 확인"""
        file_path = self._get_file_path(kb_id, doc_id, "_metadata.json")
        return os.path.exists(file_path)


# Singleton instance
temp_storage = TempStorage()
