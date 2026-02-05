"""
Fuseki SPARQL Store Connector

기존 RAGaaS의 Fuseki에 RDF 트리플을 저장합니다.
"""
import json
from typing import List, Dict, Any, Optional
import re
import urllib.parse
import httpx

from app.core.config import settings


class FusekiConnector:
    """Fuseki SPARQL Store Connector"""
    
    def __init__(self):
        self.base_url = settings.FUSEKI_URL
        self.namespace_entity = "http://rag.local/inst/"
        self.namespace_relation = "http://rag.local/rel/"
    
    def _sanitize_uri(self, text: str) -> str:
        """URI에 사용할 수 있도록 텍스트 정리"""
        clean = re.sub(r'[^a-zA-Z0-9_\uAC00-\uD7A3\u0400-\u04FF]+', '_', text.strip())
        return clean
    
    def _convert_triples_to_rdf(
        self,
        triples: List[Dict[str, Any]],
        kb_id: str,
        doc_id: str
    ) -> List[str]:
        """구조화된 트리플을 RDF N-Triples 형식으로 변환"""
        rdf_lines = []
        
        for idx, t in enumerate(triples):
            subj_clean = self._sanitize_uri(t.get("subject", ""))
            pred_clean = self._sanitize_uri(t.get("predicate", ""))
            obj_clean = self._sanitize_uri(t.get("object", ""))
            
            if not all([subj_clean, pred_clean, obj_clean]):
                continue
            
            s_uri = f"<{self.namespace_entity}{subj_clean}>"
            p_uri = f"<{self.namespace_relation}{pred_clean}>"
            o_uri = f"<{self.namespace_entity}{obj_clean}>"
            
            # 메인 트리플 추가
            rdf_lines.append(f"{s_uri} {p_uri} {o_uri} .")
            
            # Label 추가 (검색 성능 향상) - json.dumps로 안전하게 이스케이프
            subj_label = json.dumps(t.get("subject", ""), ensure_ascii=False)
            pred_label = json.dumps(t.get("predicate", ""), ensure_ascii=False)
            obj_label = json.dumps(t.get("object", ""), ensure_ascii=False)
            
            rdf_lines.append(f'{s_uri} <http://www.w3.org/2000/01/rdf-schema#label> {subj_label} .')
            rdf_lines.append(f'{p_uri} <http://www.w3.org/2000/01/rdf-schema#label> {pred_label} .')
            rdf_lines.append(f'{o_uri} <http://www.w3.org/2000/01/rdf-schema#label> {obj_label} .')
            
            # ✅ 메타데이터 트리플 추가: source_node_id를 별도 트리플로 저장
            # 트리플 statement URI 생성
            source_node_id = t.get("source_node_id", "")
            if source_node_id:
                # 트리플을 고유하게 식별할 수 있는 URI 생성
                import hashlib
                triple_key = f"{t.get('subject', '')}|{t.get('predicate', '')}|{t.get('object', '')}"
                triple_hash = hashlib.sha256(triple_key.encode()).hexdigest()[:16]
                stmt_uri = f"<http://rag.local/stmt/{triple_hash}>"
                
                # Reification: 트리플을 리소스로 표현
                rdf_lines.append(f'{stmt_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/1999/02/22-rdf-syntax-ns#Statement> .')
                rdf_lines.append(f'{stmt_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject> {s_uri} .')
                rdf_lines.append(f'{stmt_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate> {p_uri} .')
                rdf_lines.append(f'{stmt_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#object> {o_uri} .')
                
                # 메타데이터 속성 추가
                source_node_id_literal = json.dumps(source_node_id, ensure_ascii=False)
                rdf_lines.append(f'{stmt_uri} <http://rag.local/meta/sourceNodeId> {source_node_id_literal} .')
                rdf_lines.append(f'{stmt_uri} <http://rag.local/meta/docId> "{doc_id}" .')
                
                # Confidence 추가
                confidence = t.get("confidence")
                if confidence is not None:
                    rdf_lines.append(f'{stmt_uri} <http://rag.local/meta/confidence> "{confidence}" .')
        
        return rdf_lines
    
    async def ensure_dataset(self, kb_id: str) -> bool:
        """데이터셋 존재 확인 및 생성"""
        dataset_name = f"kb_{kb_id.replace('-', '_')}"
        
        async with httpx.AsyncClient() as client:
            # Check if dataset exists
            try:
                response = await client.get(
                    f"{self.base_url}/$/datasets/{dataset_name}",
                    auth=("admin", "admin")
                )
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            
            # Create dataset
            try:
                response = await client.post(
                    f"{self.base_url}/$/datasets",
                    data={
                        "dbName": dataset_name,
                        "dbType": "tdb2"
                    },
                    auth=("admin", "admin")
                )
                return response.status_code in [200, 201]
            except Exception as e:
                print(f"Error creating Fuseki dataset: {e}")
                return False
    
    async def insert_triples(
        self,
        kb_id: str,
        doc_id: str,
        triples: List[Dict[str, Any]],
        generate_inverse: bool = True
    ) -> int:
        """트리플 삽입"""
        await self.ensure_dataset(kb_id)
        
        # 역관계 추가
        all_triples = list(triples)
        if generate_inverse:
            inverse_mapping = {
                "스승": "제자", "제자": "스승",
                "부모": "자녀", "자녀": "부모",
                "선생": "학생", "학생": "선생",
                "상사": "부하", "부하": "상사",
            }
            
            for t in triples:
                if t.get("is_inverse", False):
                    continue
                    
                pred = t.get("predicate", "")
                if pred in inverse_mapping:
                    inverse = {
                        "subject": t.get("object"),
                        "predicate": inverse_mapping[pred],
                        "object": t.get("subject"),
                        "source_node_id": t.get("source_node_id"),
                        "is_inverse": True,
                        "confidence": t.get("confidence", 0.7)
                    }
                    all_triples.append(inverse)
                else:
                    # 매핑이 없는 경우, 기계적 역관계 생성 (inverse_접두사)
                    # 사용자가 원치 않을 수 있으나, 일단 기존 로직 유지하되 구분
                    inverse = {
                        "subject": t.get("object"),
                        "predicate": f"inverse_{pred}",
                        "object": t.get("subject"),
                        "source_node_id": t.get("source_node_id"),
                        "is_inverse": True,
                        "confidence": t.get("confidence", 0.7)
                    }
                    all_triples.append(inverse)
        
        # RDF로 변환
        rdf_lines = self._convert_triples_to_rdf(all_triples, kb_id, doc_id)
        
        if not rdf_lines:
            return 0
        
        # Named Graph에 삽입
        dataset_name = f"kb_{kb_id.replace('-', '_')}"
        graph_uri = f"urn:doc:{doc_id}"
        
        ntriples_data = "\n".join(rdf_lines)
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/{dataset_name}/data",
                    params={"graph": graph_uri},
                    content=ntriples_data,
                    headers={"Content-Type": "application/n-triples"},
                    auth=("admin", "admin")
                )
                
                if response.status_code in [200, 201, 204]:
                    return len(all_triples)
                else:
                    print(f"Fuseki insert error: {response.status_code} - {response.text}")
                    return 0
                    
            except Exception as e:
                print(f"Error inserting to Fuseki: {e}")
                return 0
    
    async def delete_by_doc_id(self, kb_id: str, doc_id: str) -> bool:
        """문서 ID로 Named Graph 삭제"""
        dataset_name = f"kb_{kb_id.replace('-', '_')}"
        graph_uri = f"urn:doc:{doc_id}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.delete(
                    f"{self.base_url}/{dataset_name}/data",
                    params={"graph": graph_uri},
                    auth=("admin", "admin")
                )
                return response.status_code in [200, 204]
            except Exception as e:
                print(f"Error deleting from Fuseki: {e}")
                return False


# Singleton
fuseki_connector = FusekiConnector()
