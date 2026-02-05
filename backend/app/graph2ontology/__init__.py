"""Doc2Onto: 한국어 문서 → 온톨로지(OWL/RDF) + RAG 근거 연결 파이프라인"""

__version__ = "0.1.0"
__author__ = "Doc2Onto Team"

from app.graph2ontology.config import Config, load_config

__all__ = ["Config", "load_config", "__version__"]
