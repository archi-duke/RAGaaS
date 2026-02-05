"""Doc2Onto Extractors - 후보 추출 모듈"""

from app.graph2ontology.extractors.base import BaseExtractor
from app.graph2ontology.extractors.llm_stub import LLMStubExtractor
from app.graph2ontology.extractors.korean_preprocessor import KoreanPreprocessor

__all__ = ["BaseExtractor", "LLMStubExtractor", "KoreanPreprocessor"]
