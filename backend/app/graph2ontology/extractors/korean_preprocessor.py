"""한국어 전처리 모듈 (스텁)"""

from abc import ABC, abstractmethod
from typing import Union, Optional,  Optional, Union
from dataclasses import dataclass


@dataclass
class Token:
    """형태소 분석 결과 토큰"""
    surface: str  # 표층형
    pos: str  # 품사 태그
    lemma: Optional[str] = None  # 기본형
    reading: Optional[str] = None  # 읽기


@dataclass
class NamedEntity:
    """개체명 인식 결과"""
    text: str  # 텍스트
    label: str  # 개체명 유형 (PERSON, ORG, LOC, etc.)
    start: int  # 시작 오프셋
    end: int  # 끝 오프셋


class KoreanPreprocessor:
    """한국어 전처리 스텁
    
    실제 구현 시 이 클래스를 상속하거나 교체하여 KoNLPy, mecab-ko 등 연결
    """
    
    def __init__(self, use_ner: bool = True):
        """
        Args:
            use_ner: 개체명 인식 사용 여부
        """
        self.use_ner = use_ner
        self._initialized = False
    
    def initialize(self) -> None:
        """형태소 분석기 초기화 (스텁: 아무것도 안 함)
        
        실제 구현 시:
            from konlpy.tag import Mecab
            self.tagger = Mecab()
        """
        self._initialized = True
    
    def tokenize(self, text: str) -> list[Token]:
        """형태소 분석 (스텁: 공백 기준 분할)
        
        실제 구현 시:
            result = self.tagger.pos(text)
            return [Token(surface=w, pos=p) for w, p in result]
        """
        if not self._initialized:
            self.initialize()
        
        # 스텁: 공백 기준 분할
        words = text.split()
        return [Token(surface=w, pos="NNP") for w in words]
    
    def extract_nouns(self, text: str) -> list[str]:
        """명사 추출 (스텁: 2글자 이상 단어)
        
        실제 구현 시:
            return self.tagger.nouns(text)
        """
        if not self._initialized:
            self.initialize()
        
        # 스텁: 2글자 이상 단어
        words = text.split()
        return [w for w in words if len(w) >= 2]
    
    def extract_entities(self, text: str) -> list[NamedEntity]:
        """개체명 인식 (스텁: 빈 리스트)
        
        실제 구현 시:
            from pororo import Pororo
            ner = Pororo(task="ner", lang="ko")
            result = ner(text)
            return [NamedEntity(...) for ...]
        """
        if not self.use_ner:
            return []
        
        # 스텁: 빈 리스트
        return []
    
    def normalize(self, text: str) -> str:
        """텍스트 정규화 (스텁: 그대로 반환)
        
        실제 구현 시:
            - 유니코드 정규화 (NFC)
            - 특수문자 처리
            - 띄어쓰기 교정
        """
        return text.strip()
    
    def sentence_split(self, text: str) -> list[str]:
        """문장 분리 (스텁: 마침표 기준)
        
        실제 구현 시:
            from kss import split_sentences
            return split_sentences(text)
        """
        import re
        sentences = re.split(r'(?<=[.!?다요])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
