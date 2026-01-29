"""
Text Cleaner Module

청크 생성 전에 문서 텍스트에서 노이즈(번호, 불릿, 레이아웃 문자)를 제거합니다.
"""
import re
from typing import Optional


class TextCleaner:
    """텍스트 전처리 클래스"""
    
    def clean(self, text: str, options: Optional[dict] = None) -> str:
        """
        텍스트에서 형식 문자를 제거합니다.
        
        Args:
            text: 원본 텍스트
            options: 정제 옵션 (향후 확장용)
            
        Returns:
            정제된 텍스트
        """
        if not text:
            return text
            
        # 1. 줄 시작 번호 제거: "1. ", "2) ", "3] ", "(a) ", "(1) "
        # 예: "4. 성기훈" -> "성기훈"
        text = re.sub(r'^\s*\d+[\.\)\]]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\([a-zA-Z0-9가-힣]\)\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[a-zA-Z][\.\)\]]\s+', '', text, flags=re.MULTILINE)
        
        # 2. 불릿 포인트 제거: •, -, *, ▪, ▸, →, ○, ●, ◆, ◇
        text = re.sub(r'^\s*[•\-\*▪▸→○●◆◇■□]\s+', '', text, flags=re.MULTILINE)
        
        # 3. 과도한 공백/줄바꿈 정리
        text = re.sub(r'\n{3,}', '\n\n', text)  # 3개 이상 줄바꿈 -> 2개
        text = re.sub(r' {2,}', ' ', text)       # 2개 이상 공백 -> 1개
        text = re.sub(r'\t+', ' ', text)         # 탭 -> 공백
        
        # 4. 줄 앞뒤 공백 정리
        lines = text.split('\n')
        lines = [line.strip() for line in lines]
        text = '\n'.join(lines)
        
        return text.strip()
    
    def clean_entity_name(self, name: str) -> str:
        """
        엔티티 이름에서 잔여 번호/형식 문자를 제거합니다.
        (Graph Extraction 후 추가 정제용)
        
        Args:
            name: 엔티티 이름
            
        Returns:
            정제된 엔티티 이름
        """
        if not name:
            return name
            
        # 앞뒤 공백, 따옴표 제거
        name = name.strip().strip('"\'')
        
        # 앞 번호 제거: "4. 성기훈" -> "성기훈"
        name = re.sub(r'^\d+[\.\)\]]\s*', '', name)
        name = re.sub(r'^\([a-zA-Z0-9]\)\s*', '', name)
        
        # 앞뒤 공백 다시 정리
        return name.strip()


# Singleton instance
text_cleaner = TextCleaner()
