"""
임시 파일 저장 관리 유틸리티

중간 처리 결과물(엔티티 사전, 청크, 트리플 등)을 파일 시스템에 저장하여
디버깅 및 재개 기능을 지원합니다.
"""
import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime


class TempStorage:
    """임시 파일 저장 관리"""
    
    def __init__(self, base_path: str = None):
        # 기본 경로: 프로젝트 루트의 data/uploads/.temp
        if base_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            base_path = os.path.join(project_root, "data", "uploads", ".temp")
        
        self.base_path = base_path
        try:
            os.makedirs(base_path, exist_ok=True)
            print(f"[TempStorage] Initialized with base_path: {base_path}")
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to create base_path {base_path}: {e}")
    
    def get_doc_path(self, kb_id: str, doc_id: str) -> str:
        """문서별 임시 저장 경로 반환"""
        path = os.path.join(self.base_path, kb_id, doc_id)
        os.makedirs(path, exist_ok=True)
        return path
    
    async def save_entity_dictionary(
        self, 
        kb_id: str, 
        doc_id: str, 
        dictionary: Dict[str, Any]
    ) -> str:
        """엔티티 사전 저장"""
        try:
            path = self.get_doc_path(kb_id, doc_id)
            file_path = os.path.join(path, "entity_dictionary.json")
            
            data = {
                "created_at": datetime.utcnow().isoformat(),
                "entity_count": len(dictionary),
                "dictionary": dictionary
            }
            
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
        """청크 목록 저장"""
        try:
            path = self.get_doc_path(kb_id, doc_id)
            file_path = os.path.join(path, "chunks.json")
            
            # 청크 데이터를 간소화 (메타데이터만 저장, 전체 content는 너무 클 수 있음)
            simplified_chunks = []
            for i, chunk in enumerate(chunks):
                simplified_chunks.append({
                    "index": i,
                    "content_length": len(chunk.get("content", "")),
                    "content_preview": chunk.get("content", "")[:200],  # 처음 200자만
                    "metadata": chunk.get("metadata", {}),
                    "node_id": chunk.get("node_id", "")
                })
            
            data = {
                "created_at": datetime.utcnow().isoformat(),
                "chunk_count": len(chunks),
                "chunks": simplified_chunks
            }
            
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
        """트리플 목록 저장"""
        try:
            path = self.get_doc_path(kb_id, doc_id)
            file_path = os.path.join(path, "triples.json")
            
            data = {
                "created_at": datetime.utcnow().isoformat(),
                "triple_count": len(triples),
                "triples": triples
            }
            
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
        """메타데이터 저장"""
        try:
            path = self.get_doc_path(kb_id, doc_id)
            file_path = os.path.join(path, "metadata.json")
            
            data = {
                "created_at": datetime.utcnow().isoformat(),
                **metadata
            }
            
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
            path = self.get_doc_path(kb_id, doc_id)
            file_path = os.path.join(path, "entity_dictionary.json")
            
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            print(f"[TempStorage] ✅ Loaded entity dictionary: {file_path}")
            return data.get("dictionary")
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to load entity dictionary: {e}")
            return None
    
    async def load_triples(self, kb_id: str, doc_id: str) -> Optional[List[Dict[str, Any]]]:
        """트리플 목록 로드"""
        try:
            path = self.get_doc_path(kb_id, doc_id)
            file_path = os.path.join(path, "triples.json")
            
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            print(f"[TempStorage] ✅ Loaded triples: {file_path}")
            return data.get("triples")
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to load triples: {e}")
            return None
    
    async def cleanup(self, kb_id: str, doc_id: str):
        """임시 파일 정리"""
        try:
            import shutil
            path = self.get_doc_path(kb_id, doc_id)
            if os.path.exists(path):
                shutil.rmtree(path)
                print(f"[TempStorage] ✅ Cleaned up: {path}")
        except Exception as e:
            print(f"[TempStorage] ⚠️ Failed to cleanup: {e}")
    
    def exists(self, kb_id: str, doc_id: str) -> bool:
        """임시 파일이 존재하는지 확인"""
        path = self.get_doc_path(kb_id, doc_id)
        return os.path.exists(path) and len(os.listdir(path)) > 0


# Singleton instance
temp_storage = TempStorage()
