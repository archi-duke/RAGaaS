"""TriG 파일 생성 모듈"""

from pathlib import Path
from typing import Union, Optional,  Optional, Union
from datetime import datetime

from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD, SKOS, PROV

from app.graph2ontology.models.candidate import CandidateExtractionResult, Triple
from app.graph2ontology.models.chunk import RAGChunk
from app.graph2ontology.models.entity import EntityRegistry


# 커스텀 네임스페이스
EX = Namespace("http://example.org/onto/")
EVIDENCE = Namespace("http://example.org/evidence/")


class TriGBuilder:
    """TriG 파일 생성기"""
    
    def __init__(
        self,
        base_uri: str = "http://example.org/onto/",
        base_graph_uri: str = "urn:onto:base",
        evidence_graph_prefix: str = "urn:ragchunk:",
    ):
        """
        Args:
            base_uri: 온톨로지 베이스 URI
            base_graph_uri: 베이스 그래프 URI
            evidence_graph_prefix: Evidence 그래프 URI 접두사
        """
        self.base_uri = base_uri
        self.base_graph_uri = base_graph_uri
        self.evidence_graph_prefix = evidence_graph_prefix
        
        self.onto_ns = Namespace(base_uri)
        self.base_graph = Graph(identifier=URIRef(base_graph_uri))
        self.evidence_graphs: dict[str, Graph] = {}
        
        # 네임스페이스 바인딩
        self._bind_namespaces(self.base_graph)
    
    def _bind_namespaces(self, graph: Graph) -> None:
        """네임스페이스 바인딩"""
        graph.bind("ex", self.onto_ns)
        graph.bind("owl", OWL)
        graph.bind("rdfs", RDFS)
        graph.bind("skos", SKOS)
        graph.bind("prov", PROV)
        graph.bind("evidence", EVIDENCE)
    
    def _to_uri(self, label: str, prefix: str = "") -> URIRef:
        """라벨을 URI로 변환"""
        # 간단한 변환: 공백/특수문자 제거, CamelCase
        safe_label = "".join(
            c if c.isalnum() else "_" for c in label
        ).strip("_")
        return URIRef(f"{self.base_uri}{prefix}{safe_label}")
    
    def add_class(self, label: str, parent_uri: Optional[URIRef] = None) -> URIRef:
        """클래스 추가"""
        uri = self._to_uri(label, "class/")
        self.base_graph.add((uri, RDF.type, OWL.Class))
        self.base_graph.add((uri, RDFS.label, Literal(label, lang="ko")))
        if parent_uri:
            self.base_graph.add((uri, RDFS.subClassOf, parent_uri))
        return uri
    
    def add_property(
        self, 
        label: str, 
        domain_uri: Optional[URIRef] = None,
        range_type: str = "xsd:string"
    ) -> URIRef:
        """데이터 속성 추가"""
        uri = self._to_uri(label, "prop/")
        self.base_graph.add((uri, RDF.type, OWL.DatatypeProperty))
        self.base_graph.add((uri, RDFS.label, Literal(label, lang="ko")))
        if domain_uri:
            self.base_graph.add((uri, RDFS.domain, domain_uri))
        return uri
    
    def add_relation(
        self,
        label: str,
        domain_uri: Optional[URIRef] = None,
        range_uri: Optional[URIRef] = None,
    ) -> URIRef:
        """객체 속성(관계) 추가"""
        uri = self._to_uri(label, "rel/")
        self.base_graph.add((uri, RDF.type, OWL.ObjectProperty))
        self.base_graph.add((uri, RDFS.label, Literal(label, lang="ko")))
        if domain_uri:
            self.base_graph.add((uri, RDFS.domain, domain_uri))
        if range_uri:
            self.base_graph.add((uri, RDFS.range, range_uri))
        return uri
    
    def add_instance(
        self,
        label: str,
        class_uri: URIRef,
    ) -> URIRef:
        """인스턴스 추가"""
        uri = self._to_uri(label, "inst/")
        self.base_graph.add((uri, RDF.type, class_uri))
        self.base_graph.add((uri, RDFS.label, Literal(label, lang="ko")))
        return uri
    
    def build_from_candidates(
        self,
        result: CandidateExtractionResult,
        registry: Optional[EntityRegistry] = None,
    ) -> None:
        """추출 결과로부터 베이스 그래프 생성"""
        # 클래스 추가
        for cls in result.classes:
            parent_uri = None
            if cls.parent_class:
                parent_uri = self._to_uri(cls.parent_class, "class/")
            uri = self.add_class(cls.label, parent_uri)
            if cls.description:
                self.base_graph.add((uri, RDFS.comment, Literal(cls.description, lang="ko")))
        
        # 속성 추가
        for prop in result.properties:
            domain_uri = self._to_uri(prop.domain_class, "class/") if prop.domain_class else None
            self.add_property(prop.label, domain_uri, prop.range_type)
        
        # 관계 추가
        for rel in result.relations:
            domain_uri = self._to_uri(rel.domain_class, "class/") if rel.domain_class else None
            range_uri = self._to_uri(rel.range_class, "class/") if rel.range_class else None
            self.add_relation(rel.label, domain_uri, range_uri)

        # 인스턴스 추가
        for inst in result.instances:
            class_uri = self._to_uri(inst.class_label, "class/") if inst.class_label else OWL.Thing
            uri = self.add_instance(inst.label, class_uri)
            if inst.source_text:
                self.base_graph.add((uri, RDFS.comment, Literal(inst.source_text, lang="ko")))
    
    def add_evidence_triple(
        self,
        triple: Triple,
        chunk: RAGChunk,
        run_id: str,
    ) -> None:
        """Evidence 그래프에 트리플 + 메타데이터 추가 (RDF-star 스타일)
        
        Named Graph: urn:ragchunk:{doc_id}:{doc_ver}:{chunk_idx}
        """
        graph_uri = chunk.graph_uri
        
        if graph_uri not in self.evidence_graphs:
            g = Graph(identifier=URIRef(graph_uri))
            self._bind_namespaces(g)
            self.evidence_graphs[graph_uri] = g
        
        g = self.evidence_graphs[graph_uri]
        
        # 트리플 생성
        subj = self._to_uri(triple.subject, "inst/")
        # 술어 URI 생성 (Literal이면 prop/, 아니면 rel/)
        pred_prefix = "prop/" if triple.object_is_literal else "rel/"
        pred = self._to_uri(triple.predicate, pred_prefix)
        if triple.object_is_literal:
            obj = Literal(triple.object)
        else:
            obj = self._to_uri(triple.object, "inst/")
        
        g.add((subj, pred, obj))
        
        # RDF-star 메타데이터를 위한 reification (RDF 1.1 호환)
        # 실제 RDF-star 지원 시 << subj pred obj >> 구문 사용
        stmt = BNode()
        g.add((stmt, RDF.type, RDF.Statement))
        g.add((stmt, RDF.subject, subj))
        g.add((stmt, RDF.predicate, pred))
        g.add((stmt, RDF.object, obj))
        
        # 메타데이터
        g.add((stmt, EVIDENCE.confidence, Literal(triple.confidence, datatype=XSD.float)))
        g.add((stmt, EVIDENCE.evidenceText, Literal(triple.source_text, lang="ko")))
        g.add((stmt, PROV.wasDerivedFrom, URIRef(chunk.milvus_uri)))
        g.add((stmt, EVIDENCE.chunkHash, Literal(chunk.chunk_hash)))
        g.add((stmt, EVIDENCE.runId, Literal(run_id)))
    
    def serialize_base(self, output_path: Union[str, Path]) -> None:
        """베이스 그래프를 TriG로 저장"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# Base Ontology Graph\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n\n")
            f.write(self.base_graph.serialize(format="trig"))
    
    def serialize_evidence(self, output_path: Union[str, Path]) -> None:
        """Evidence 그래프들을 TriG로 저장"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# Evidence Graphs (RDF-star style)\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")
            f.write(f"# Total graphs: {len(self.evidence_graphs)}\n\n")
            
            for graph_uri, g in self.evidence_graphs.items():
                f.write(f"\n# Graph: {graph_uri}\n")
                f.write(g.serialize(format="trig"))
