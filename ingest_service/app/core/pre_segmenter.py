import re
from typing import List

class PreSegmenter:
    """
    문서를 문맥 분석을 위한 대형 세그먼트(Pre-segment)로 분할합니다.
    청크 크기보다 훨씬 큰 단위(예: 3000~5000 토큰)를 사용합니다.
    """
    
    def __init__(self, segment_size: int = 4000, overlap: int = 500):
        self.segment_size = segment_size
        self.overlap = overlap

    def segment(self, text: str) -> List[str]:
        """
        텍스트를 대형 세그먼트로 분할합니다.
        가능하면 문단이나 헤더 단위로 끊으려 노력하지만, 기본적으로는 문자 수 기반 슬라이딩 윈도우를 사용합니다.
        (토크나이저를 쓰면 더 정확하지만 속도를 위해 문자 수 대략 환산 사용: 한글/영문 혼용 시 1토큰 ≈ 1~2 chars)
        여기서는 1 char = 0.5 token 가정 (넉넉하게) -> 4000 tokens ≈ 8000 chars
        """
        
        # 간단한 문자 수 기반 슬라이딩 윈도우 (안전하게 1 char = 1 token으로 가정하고 나중에 튜닝)
        # 실제 모델 컨텍스트는 큽니다 (GPT-4o 128k). 
        # 하지만 너무 크면 Attention이 흐려지므로 적당히 자릅니다.
        
        char_limit = self.segment_size * 2  # 대략적인 문자 수 변환
        overlap_chars = self.overlap * 2
        
        segments = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = start + char_limit
            
            # 마지막이 아니면 overlap 적용하여 다음 start 위치 계산
            if end >= text_len:
                end = text_len
                next_start = text_len  # 종료
            else:
                # 문단 단위 절단을 위해 뒤에서부터 개행 문자 탐색
                search_range = 500  # 뒤로 500자 내에서 개행 찾기
                cut_point = -1
                
                # 1. 이중 개행 (\n\n) 우선 검색 (문단 구분)
                last_double_newline = text.rfind('\n\n', start, end)
                if last_double_newline != -1 and last_double_newline > end - search_range:
                    cut_point = last_double_newline + 2
                
                # 2. 단일 개행 (\n) 차선 검색
                if cut_point == -1:
                    last_newline = text.rfind('\n', start, end)
                    if last_newline != -1 and last_newline > end - search_range:
                        cut_point = last_newline + 1
                
                # 3. 마침표 (. ) 검색
                if cut_point == -1:
                    last_period = text.rfind('. ', start, end)
                    if last_period != -1 and last_period > end - search_range:
                        cut_point = last_period + 2

                # 적절한 절단 지점을 찾았으면 거기서 자름
                if cut_point != -1:
                    end = cut_point
                
                next_start = end - overlap_chars
                if next_start <= start: # 무한 루프 방지: 최소 진행 보장
                    next_start = start + (char_limit // 2)

            segment = text[start:end].strip()
            if segment:
                segments.append(segment)
            
            start = int(next_start)
            
        print(f"[PreSegmenter] Split text into {len(segments)} segments (size ~{char_limit} chars)")
        return segments
