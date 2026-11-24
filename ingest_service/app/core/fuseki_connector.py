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

# 숫자 앞 부호는 뜻이 있다 ('+3점' ≠ '-3점'). 아래 정리에서 '_' 로 뭉개지지 않게 먼저 단어로 바꾼다 (2026-11-24).
_SIGN_RE = re.compile(r"(?<![0-9A-Za-z\uAC00-\uD7A3])([+\-\u2212])(?=\d)")


def _sign_words(text: str) -> str:
    return _SIGN_RE.sub(lambda m: "plus" if m.group(1) == "+" else "minus", text)


class FusekiConnector:
    """Fuseki SPARQL Store Connector"""

    # [NEW][B안] 인제스트 시점 엔티티 타입(rdf:type) 네임스페이스.
    # enable_entity_typing이 활성일 때만 triple dict에 subject_type/object_type이 붙으므로,
    # 비활성 시(필드 없음/None)에는 아래 로직이 아무 것도 방출하지 않아 기존 동작과 동일하다.
    CLASS_NS = "http://rag.local/class/"

    def __init__(self):
        self.base_url = settings.FUSEKI_URL
        self.namespace_entity = "http://rag.local/inst/"
        self.namespace_relation = "http://rag.local/rel/"

    def _sanitize_uri(self, text: str) -> str:
        """URI에 사용할 수 있도록 텍스트 정리"""
        clean = re.sub(r'[^a-zA-Z0-9_\uAC00-\uD7A3\u0400-\u04FF]+', '_', _sign_words(text.strip()))
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

            # [NEW][B안, opt-in] rdf:type 엣지 추가
            # subject_type/object_type은 enable_entity_typing이 활성일 때만 트리플 dict에 존재한다.
            # "Entity"(안전 폴백)는 의미 없는 잡음이므로 방출하지 않는다.
            subject_type = t.get("subject_type")
            if subject_type and subject_type != "Entity":
                subj_cls = self._sanitize_uri(subject_type)
                if subj_cls:
                    rdf_lines.append(
                        f'{s_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{self.CLASS_NS}{subj_cls}> .'
                    )
            object_type = t.get("object_type")
            if object_type and object_type != "Entity":
                obj_cls = self._sanitize_uri(object_type)
                if obj_cls:
                    rdf_lines.append(
                        f'{o_uri} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{self.CLASS_NS}{obj_cls}> .'
                    )

            # ✅ 메타데이터 트리플 추가: source_node_id를 별도 트리플로 저장
            # 트리플 statement URI 생성
            source_node_id = t.get("source_node_id", "")
            if source_node_id:
                # 트리플을 고유하게 식별할 수 있는 URI 생성
                import hashlib
                triple_key = f"{t.get('subject', '')}|{t.get('predicate', '')}|{t.get('object', '')}"
                year = t.get("year")
                if year is not None:
                    triple_key += f"|{int(year)}"   # 연도가 다르면 진술 노드를 따로 둔다 (D4 §3.1)
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
                
                # 진술 연도 (D4): 정수 연도 + 원문 표기
                if year is not None:
                    rdf_lines.append(f'{stmt_uri} <http://rag.local/meta/year> "{int(year)}"^^<http://www.w3.org/2001/XMLSchema#integer> .')
                    if t.get("year_text"):
                        rdf_lines.append(f'{stmt_uri} <http://rag.local/meta/yearText> {json.dumps(str(t["year_text"]), ensure_ascii=False)} .')

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
        
        # 여러 문서를 동시에 인제스트하면 Fuseki 쓰기가 httpx 기본 타임아웃(5초)을 넘겨
        # 메시지 없는 ReadTimeout 으로 실패했고, 예외를 삼켜 작업이 COMPLETED 로 끝나
        # 그래프만 비는 문서가 생겼다. 넉넉한 타임아웃 + 재시도, 최종 실패는 예외로 올려
        # 작업을 FAILED 로 표시한다.
        import asyncio as _asyncio
        last_err = ""
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                    response = await client.post(
                        f"{self.base_url}/{dataset_name}/data",
                        params={"graph": graph_uri},
                        content=ntriples_data,
                        headers={"Content-Type": "application/n-triples"},
                        auth=("admin", "admin")
                    )
                if response.status_code in [200, 201, 204]:
                    return len(all_triples)
                last_err = f"HTTP {response.status_code} - {response.text[:300]}"
            except Exception as e:
                last_err = repr(e)
            print(f"Fuseki insert attempt {attempt}/3 for doc {doc_id} did not succeed: {last_err}")
            await _asyncio.sleep(2 * attempt)
        raise RuntimeError(f"Fuseki insert for doc {doc_id} did not succeed after 3 attempts: {last_err}")
    
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
