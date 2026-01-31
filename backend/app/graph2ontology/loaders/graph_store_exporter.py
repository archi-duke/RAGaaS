"""Graph Store (Fuseki/Neo4j)에서 TriG 파일 추출

이 모듈은 Graph Store에 저장된 트리플을 TriG 형식으로 변환하여
OntologyPromoter가 사용할 수 있도록 합니다.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from rdflib import Graph, Dataset, Namespace, URIRef, Literal, RDF, RDFS
import logging

logger = logging.getLogger(__name__)


class GraphStoreExporter:
    """Graph Store → TriG 파일 변환기
    
    단일 책임: Graph Store에서 데이터를 읽어 TriG 파일로 변환
    """
    
    def __init__(self):
        self.namespace_inst = "http://rag.local/inst/"
        self.namespace_rel = "http://rag.local/rel/"
        self.namespace_prop = "http://rag.local/prop/"
        self.namespace_class = "http://rag.local/class/"
    
    async def export_from_fuseki(
        self, 
        kb_id: str, 
        output_dir: Path
    ) -> Dict[str, Any]:
        """Fuseki에서 모든 트리플을 TriG로 추출
        
        Args:
            kb_id: Knowledge Base ID
            output_dir: 출력 디렉토리 (data/uploads/{kb_id}/promotion/)
            
        Returns:
            {
                "base_path": Path,
                "evidence_path": Optional[Path],
                "triple_count": int,
                "graph_count": int
            }
        """
        from app.core.fuseki import fuseki_client
        
        logger.info(f"[GraphStoreExporter] Starting Fuseki export for KB: {kb_id}")
        
        try:
            # UnionGraph에서 모든 트리플 조회
            # UnionGraph는 모든 Named Graph의 합집합을 제공합니다
            # Note: 온톨로지 그래프는 별도 그래프로 관리되므로 자동으로 제외됨
            construct_query = """
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            
            CONSTRUCT { ?s ?p ?o }
            FROM <urn:x-arq:UnionGraph>
            WHERE {
                ?s ?p ?o .
            }
            """
            
            logger.info(f"[GraphStoreExporter] Querying UnionGraph for all triples...")
            
            # Fuseki에서 CONSTRUCT 실행
            graph_triples_ttl = await self._construct_query_fuseki(kb_id, construct_query)
            
            if not graph_triples_ttl:
                logger.warning(f"[GraphStoreExporter] No triples found in Fuseki for KB {kb_id}")
                return {
                    "base_path": None,
                    "evidence_path": None,
                    "triple_count": 0,
                    "graph_count": 0
                }
            
            # RDF Graph로 파싱
            g = Graph()
            g.parse(data=graph_triples_ttl, format="turtle")
            total_triple_count = len(g)
            
            logger.info(f"[GraphStoreExporter] Extracted {total_triple_count} triples from UnionGraph")
            
            # TriG 파일로 저장
            output_dir.mkdir(parents=True, exist_ok=True)
            base_path = output_dir / "base.trig"
            
            with open(base_path, "w", encoding="utf-8") as f:
                f.write("# Base Knowledge Graph\n")
                f.write(f"# Exported from Fuseki KB: {kb_id}\n")
                f.write(f"# Total Triples: {total_triple_count}\n\n")
                f.write(g.serialize(format="trig"))
            
            logger.info(f"[GraphStoreExporter] ✅ Exported {total_triple_count} triples to {base_path}")
            
            return {
                "base_path": base_path,
                "evidence_path": None,  # Fuseki는 Evidence를 별도로 구분하지 않음
                "triple_count": total_triple_count,
                "graph_count": 1  # UnionGraph 사용
            }
            
        except Exception as e:
            logger.error(f"[GraphStoreExporter] Failed to export from Fuseki: {e}")
            raise
    
    async def _construct_query_fuseki(self, kb_id: str, query: str) -> Optional[str]:
        """Fuseki CONSTRUCT 쿼리 실행
        
        Args:
            kb_id: Knowledge Base ID
            query: SPARQL CONSTRUCT 쿼리
            
        Returns:
            Turtle 형식의 트리플 문자열
        """
        import httpx
        from app.core.config import settings
        
        # KB ID를 Fuseki 데이터셋 이름으로 변환 (fuseki_client와 동일한 방식)
        safe_name = f"kb_{kb_id.replace('-', '_')}"
        fuseki_url = f"{settings.FUSEKI_URL}/{safe_name}/sparql"
        
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    fuseki_url,
                    data={"query": query},
                    headers={
                        "Accept": "text/turtle",
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    auth=("admin", "admin")  # Fuseki default credentials
                )
                
                if response.status_code == 200:
                    return response.text
                else:
                    logger.error(f"[GraphStoreExporter] Fuseki CONSTRUCT failed: {response.status_code}, URL: {fuseki_url}")
                    logger.error(f"[GraphStoreExporter] Response: {response.text[:200]}")
                    return None
                    
        except Exception as e:
            logger.error(f"[GraphStoreExporter] HTTP request failed: {e}")
            return None
    
    async def export_from_neo4j(
        self,
        kb_id: str,
        output_dir: Path
    ) -> Dict[str, Any]:
        """Neo4j에서 모든 관계를 TriG로 추출
        
        Args:
            kb_id: Knowledge Base ID
            output_dir: 출력 디렉토리
            
        Returns:
            {
                "base_path": Path,
                "evidence_path": None,
                "triple_count": int,
                "graph_count": 1
            }
        """
        from app.core.neo4j_client import neo4j_client
        
        logger.info(f"[GraphStoreExporter] Starting Neo4j export for KB: {kb_id}")
        
        try:
            # 1. Neo4j에서 모든 Entity와 Relationship 조회
            query = """
            MATCH (s:Entity)-[r]->(o:Entity)
            WHERE s.kb_id = $kb_id
            RETURN 
                s.id AS subject, 
                s.name AS subject_name,
                type(r) AS predicate, 
                o.id AS object,
                o.name AS object_name,
                r.source_node_id AS source_chunk
            LIMIT 100000
            """
            
            results = neo4j_client.execute_query(query, {"kb_id": kb_id})
            
            if not results:
                logger.warning(f"[GraphStoreExporter] No triples found in Neo4j for KB {kb_id}")
                return {
                    "base_path": None,
                    "evidence_path": None,
                    "triple_count": 0,
                    "graph_count": 0
                }
            
            # 2. RDF Graph 생성
            g = Graph()
            
            # 네임스페이스 바인딩
            INST = Namespace(self.namespace_inst)
            REL = Namespace(self.namespace_rel)
            
            g.bind("inst", INST)
            g.bind("rel", REL)
            g.bind("rdfs", RDFS)
            
            # 3. Neo4j 결과를 RDF 트리플로 변환
            for record in results:
                # Subject URI
                subject_id = record["subject"]
                s = URIRef(INST + self._sanitize_uri_component(subject_id))
                
                # Subject에 label 추가
                if record.get("subject_name"):
                    g.add((s, RDFS.label, Literal(record["subject_name"], lang="ko")))
                
                # Predicate URI
                predicate_name = record["predicate"]
                p = URIRef(REL + self._sanitize_uri_component(predicate_name))
                
                # Object URI
                object_id = record["object"]
                o = URIRef(INST + self._sanitize_uri_component(object_id))
                
                # Object에 label 추가
                if record.get("object_name"):
                    g.add((o, RDFS.label, Literal(record["object_name"], lang="ko")))
                
                # 트리플 추가
                g.add((s, p, o))
            
            # 4. TriG 파일로 저장
            output_dir.mkdir(parents=True, exist_ok=True)
            base_path = output_dir / "base.trig"
            
            with open(base_path, "w", encoding="utf-8") as f:
                f.write("# Base Knowledge Graph\n")
                f.write(f"# Exported from Neo4j KB: {kb_id}\n")
                f.write(f"# Total Triples: {len(g)}\n\n")
                f.write(g.serialize(format="trig"))
            
            logger.info(f"[GraphStoreExporter] ✅ Exported {len(g)} triples to {base_path}")
            
            return {
                "base_path": base_path,
                "evidence_path": None,
                "triple_count": len(g),
                "graph_count": 1
            }
            
        except Exception as e:
            logger.error(f"[GraphStoreExporter] Failed to export from Neo4j: {e}")
            raise
    
    def _sanitize_uri_component(self, text: str) -> str:
        """URI 컴포넌트로 사용 가능하도록 텍스트 정리
        
        Args:
            text: 원본 텍스트
            
        Returns:
            URI-safe 문자열
        """
        from urllib.parse import quote
        
        # 공백을 언더스코어로, 특수문자 인코딩
        sanitized = text.replace(" ", "_").replace("/", "_")
        return quote(sanitized, safe="")
