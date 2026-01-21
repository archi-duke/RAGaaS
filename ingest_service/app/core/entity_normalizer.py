"""
Entity Normalizer Module

그래프 추출 후, 적재 직전에 엔티티 이름을 Canonical Form으로 정규화합니다.
"""
import re
from typing import List, Dict, Any, Optional


class EntityNormalizer:
    """엔티티 정규화 클래스"""
    
    def normalize_triples(self, triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        트리플 리스트의 subject/object를 정규화합니다.
        
        Args:
            triples: 원본 트리플 리스트
            
        Returns:
            정규화된 트리플 리스트
        """
        for t in triples:
            t["subject"] = self._to_canonical(t.get("subject", ""))
            t["object"] = self._to_canonical(t.get("object", ""))
            # predicate도 정리 (공백 등)
            t["predicate"] = self._normalize_predicate(t.get("predicate", ""))
        
        return triples
    
    def _to_canonical(self, name: str) -> str:
        """
        엔티티 이름을 Canonical Form으로 변환합니다.
        
        Args:
            name: 원본 엔티티 이름
            
        Returns:
            정규화된 엔티티 이름
        """
        if not name:
            return name
        
        # 1. 앞뒤 공백 제거
        name = name.strip()
        
        # 2. 따옴표/괄호 제거
        name = name.strip('"\'')
        
        # 3. 앞 번호 제거: "4. 성기훈" → "성기훈"
        name = re.sub(r'^\d+[\.\)\]]\s*', '', name)
        name = re.sub(r'^\([a-zA-Z0-9]\)\s*', '', name)
        
        # 4. 특수문자 정리 (언더스코어 유지)
        # 예: "성기훈_456" 같은 것은 유지
        
        # 5. 연속 공백 → 단일 공백
        name = ' '.join(name.split())
        
        # 6. 앞뒤 공백 재정리
        return name.strip()
    
    def _normalize_predicate(self, predicate: str) -> str:
        """
        관계 이름을 정규화합니다.
        
        Args:
            predicate: 원본 관계 이름
            
        Returns:
            정규화된 관계 이름
        """
        if not predicate:
            return predicate
        
        # 공백 정리
        predicate = predicate.strip()
        predicate = ' '.join(predicate.split())
        
        return predicate
    
    def resolve_duplicates(self, triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        중복 트리플을 제거합니다.
        (동일한 subject-predicate-object 조합)
        
        Args:
            triples: 트리플 리스트
            
        Returns:
            중복 제거된 트리플 리스트
        """
        seen = set()
        unique_triples = []
        
        for t in triples:
            key = (t.get("subject"), t.get("predicate"), t.get("object"))
            if key not in seen:
                seen.add(key)
                unique_triples.append(t)
        
        return unique_triples


# Singleton instance
entity_normalizer = EntityNormalizer()
