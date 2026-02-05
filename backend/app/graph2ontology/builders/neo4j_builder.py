"""Neo4j Cypher 빌더 - TriG → Cypher 변환"""

from pathlib import Path
from typing import Union, Optional,  Optional, Union
from datetime import datetime

from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL


class Neo4jBuilder:
    """TriG 파일을 Neo4j Cypher로 변환"""
    
    def __init__(self):
        self.nodes: dict[str, dict] = {}  # iri -> node props
        self.relationships: list[dict] = []
        self.chunks: list[dict] = []
    
    def _safe_label(self, text: str) -> str:
        """Neo4j 안전한 라벨로 변환"""
        if not text:
            return "Unknown"
        # 특수문자 제거
        safe = "".join(c if c.isalnum() or c in "_가-힣" else "_" for c in text)
        return safe[:50] if safe else "Unknown"
    
    def _escape(self, text: str) -> str:
        """Cypher 문자열 이스케이프"""
        if not text:
            return ""
        return text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    
    def _extract_label(self, g: Graph, uri: URIRef) -> str:
        """URI에서 라벨 추출"""
        # rdfs:label 먼저 확인
        for label in g.objects(uri, RDFS.label):
            return str(label)
        # URI 마지막 부분 사용
        uri_str = str(uri)
        if "/" in uri_str:
            return uri_str.split("/")[-1]
        if "#" in uri_str:
            return uri_str.split("#")[-1]
        return uri_str
    
    def load_trig(self, trig_path: Union[str, Path]) -> int:
        """TriG 파일 로드 및 변환"""
        from rdflib import Dataset
        
        trig_path = Path(trig_path)
        ds = Dataset()
        ds.parse(trig_path, format="trig")
        
        triple_count = 0
        
        # 모든 Named Graph 순회
        for graph in ds.graphs():
            for s, p, o in graph:
                if isinstance(s, URIRef):
                    s_iri = str(s)
                    if s_iri not in self.nodes:
                        self.nodes[s_iri] = {
                            "iri": s_iri,
                            "label_ko": self._extract_label(graph, s),
                            "entity_type": "Entity",
                        }
                
                if isinstance(o, URIRef):
                    o_iri = str(o)
                    if o_iri not in self.nodes:
                        self.nodes[o_iri] = {
                            "iri": o_iri,
                            "label_ko": self._extract_label(graph, o),
                            "entity_type": "Entity",
                        }
                    
                    # 관계 추가
                    rel_type = self._safe_label(self._extract_label(graph, p)).upper()
                    self.relationships.append({
                        "from_iri": str(s),
                        "to_iri": str(o),
                        "type": rel_type,
                        "predicate": str(p),
                    })
                    triple_count += 1
                
                elif isinstance(o, Literal):
                    # 리터럴은 노드 속성으로 추가
                    if str(s) in self.nodes:
                        prop_name = self._safe_label(self._extract_label(graph, p))
                        self.nodes[str(s)][prop_name] = str(o)
        
        return triple_count
    
    def load_chunks(self, chunks_path: Union[str, Path]) -> int:
        """chunks.jsonl 로드"""
        import json
        chunks_path = Path(chunks_path)
        
        if not chunks_path.exists():
            return 0
        
        count = 0
        with open(chunks_path, "r", encoding="utf-8") as f:
            for line in f:
                chunk = json.loads(line)
                self.chunks.append({
                    "chunk_id": chunk.get("chunk_id", ""),
                    "doc_id": chunk.get("doc_id", ""),
                    "doc_ver": chunk.get("doc_ver", "v1"),
                    "chunk_hash": chunk.get("chunk_hash", ""),
                    "section_path": chunk.get("section_path", ""),
                    "text": chunk.get("text", "")[:200],  # 처음 200자만
                })
                count += 1
        
        return count
    
    def generate_cypher(self) -> str:
        """Cypher 스크립트 생성"""
        lines = [
            f"// Neo4j Knowledge Graph Load Script",
            f"// Generated: {datetime.now().isoformat()}",
            f"// Nodes: {len(self.nodes)}, Relationships: {len(self.relationships)}, Chunks: {len(self.chunks)}",
            "",
            "// === Constraints ===",
            "CREATE CONSTRAINT entity_iri IF NOT EXISTS FOR (e:Entity) REQUIRE e.iri IS UNIQUE;",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE;",
            "",
            "// === Entity Nodes ===",
        ]
        
        # Entity 노드 생성
        for iri, node in self.nodes.items():
            props = {
                "iri": self._escape(node.get("iri", "")),
                "label_ko": self._escape(node.get("label_ko", "")),
                "entity_type": self._escape(node.get("entity_type", "Entity")),
            }
            props_str = ", ".join(f'{k}: "{v}"' for k, v in props.items() if v)
            lines.append(f"MERGE (e:Entity {{{props_str}}});")
        
        lines.append("")
        lines.append("// === Chunk Nodes ===")
        
        # Chunk 노드 생성
        for chunk in self.chunks:
            props = {
                "chunk_id": self._escape(chunk.get("chunk_id", "")),
                "doc_id": self._escape(chunk.get("doc_id", "")),
                "doc_ver": self._escape(chunk.get("doc_ver", "")),
                "chunk_hash": self._escape(chunk.get("chunk_hash", "")),
                "section_path": self._escape(chunk.get("section_path", "")),
            }
            props_str = ", ".join(f'{k}: "{v}"' for k, v in props.items() if v)
            lines.append(f"MERGE (c:Chunk {{{props_str}}});")
        
        lines.append("")
        lines.append("// === Relationships ===")
        
        # 관계 생성
        for rel in self.relationships:
            rel_type = rel.get("type", "RELATED_TO")
            if not rel_type or rel_type == "TYPE":
                rel_type = "RELATED_TO"
            
            lines.append(
                f"MATCH (a:Entity {{iri: \"{self._escape(rel['from_iri'])}\"}})"
            )
            lines.append(
                f"MATCH (b:Entity {{iri: \"{self._escape(rel['to_iri'])}\"}})"
            )
            lines.append(f"MERGE (a)-[:{rel_type}]->(b);")
            lines.append("")
        
        return "\n".join(lines)
    
    def serialize(self, output_path: Union[str, Path]) -> dict:
        """Cypher 스크립트 저장"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        cypher = self.generate_cypher()
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(cypher)
        
        return {
            "path": str(output_path),
            "nodes": len(self.nodes),
            "relationships": len(self.relationships),
            "chunks": len(self.chunks),
        }
