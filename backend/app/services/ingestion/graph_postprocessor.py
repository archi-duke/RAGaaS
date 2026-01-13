"""
그래프 트리플 후처리 유틸리티

정밀도 향상을 위한 필터링 및 정규화 기능 제공
"""
from typing import List, Dict, Any, Set
import re


# 노이즈 Predicate 블랙리스트
PREDICATE_BLACKLIST = {
    "관계", "Relation", "Domain", "Range",
    "특성", "종류", "유형", "타입", "Type",
    "속성", "Property", "Attribute",
    "편집",  # 위키 편집 관련
}

# 한국어 조사 목록
KOREAN_JOSAS = [
    "의", "은", "는", "이", "가", "을", "를", 
    "에", "에서", "에게", "께", "으로", "로",
    "와", "과", "랑", "이랑",
    "부터", "까지", "도", "만", "조차", "마저"
]


def normalize_entity(text: str) -> str:
    """
    엔티티 정규화: 조사 제거, 공백 정리
    
    Args:
        text: 원본 엔티티 텍스트
    
    Returns:
        정규화된 엔티티
    """
    if not text or not isinstance(text, str):
        return text
    
    # 1. 앞뒤 공백 제거
    text = text.strip()
    
    # 2. 조사 제거 (긴 것부터 매칭)
    for josa in sorted(KOREAN_JOSAS, key=len, reverse=True):
        if text.endswith(josa):
            # 조사 제거 후 남은 부분이 너무 짧으면 제거하지 않음
            stem = text[:-len(josa)]
            if len(stem) >= 2:  # 최소 2글자 이상
                text = stem
                break
    
    # 3. 연속된 공백을 하나로
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def is_noise_predicate(predicate: str) -> bool:
    """
    노이즈 predicate 판별
    
    Args:
        predicate: 관계 타입
    
    Returns:
        노이즈 여부
    """
    if not predicate:
        return True
    
    # 블랙리스트 체크 (대소문자 무시)
    pred_lower = predicate.lower().strip()
    for noise in PREDICATE_BLACKLIST:
        if noise.lower() == pred_lower:
            return True
    
    # 너무 짧은 predicate (1글자)
    if len(predicate.strip()) <= 1:
        return True
    
    return False


def is_valid_entity(entity: str) -> bool:
    """
    유효한 엔티티인지 검증
    
    Args:
        entity: 엔티티 텍스트
    
    Returns:
        유효 여부
    """
    if not entity or not isinstance(entity, str):
        return False
    
    entity = entity.strip()
    
    # 너무 짧음
    if len(entity) < 2:
        return False
    
    # "Unknown" 같은 플레이스홀더
    if entity.lower() in ["unknown", "none", "null", "n/a"]:
        return False
    
    # 대명사만 있는 경우
    pronouns = ["그", "그녀", "이", "그것", "저", "저것", "이것"]
    if entity in pronouns:
        return False
    
    return True


def deduplicate_triples(triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    중복 트리플 제거 (S-P-O 기준)
    
    Args:
        triples: 트리플 리스트
    
    Returns:
        중복 제거된 트리플 리스트
    """
    seen: Set[tuple] = set()
    unique_triples = []
    
    for triple in triples:
        # S-P-O 키 생성 (정규화 후)
        key = (
            normalize_entity(triple.get("subject", "")),
            triple.get("predicate", "").strip(),
            normalize_entity(triple.get("object", ""))
        )
        
        if key not in seen and all(key):  # 모든 요소가 비어있지 않아야 함
            seen.add(key)
            unique_triples.append(triple)
    
    return unique_triples


def post_process_triples(
    triples: List[Dict[str, Any]], 
    confidence_threshold: float = 0.0,
    normalize: bool = True
) -> List[Dict[str, Any]]:
    """
    트리플 후처리: 필터링 + 정규화 + 중복 제거
    
    Args:
        triples: 원본 트리플 리스트
        confidence_threshold: 최소 신뢰도 (0.0 ~ 1.0)
        normalize: 엔티티 정규화 수행 여부
    
    Returns:
        후처리된 트리플 리스트
    """
    processed = []
    
    for triple in triples:
        # 1. 신뢰도 필터링
        confidence = triple.get("confidence", 1.0)
        if confidence < confidence_threshold:
            continue
        
        # 2. 노이즈 predicate 제거
        predicate = triple.get("predicate", "")
        if is_noise_predicate(predicate):
            continue
        
        # 3. 유효한 엔티티 검증
        subject = triple.get("subject", "")
        obj = triple.get("object", "")
        
        if not is_valid_entity(subject) or not is_valid_entity(obj):
            continue
        
        # 4. 엔티티 정규화
        if normalize:
            triple["subject"] = normalize_entity(subject)
            triple["object"] = normalize_entity(obj)
            triple["predicate"] = predicate.strip()
        
        processed.append(triple)
    
    # 5. 중복 제거
    unique = deduplicate_triples(processed)
    
    return unique


def add_inverse_relations(
    triples: List[Dict[str, Any]], 
    inverse_map: Dict[str, str] = None
) -> List[Dict[str, Any]]:
    """
    역관계 자동 생성
    
    Args:
        triples: 원본 트리플 리스트
        inverse_map: 역관계 매핑 딕셔너리 (기본값: 내장 매핑)
    
    Returns:
        역관계가 추가된 트리플 리스트
    """
    if inverse_map is None:
        # 기본 역관계 매핑
        inverse_map = {
            "스승": "제자",
            "제자": "스승",
            "부모": "자식",
            "자식": "부모",
            "선배": "후배",
            "후배": "선배",
            "형": "동생",
            "동생": "형",
            "언니": "동생",
            "누나": "동생",
            "오빠": "동생",
            "남편": "아내",
            "아내": "남편",
        }
    
    result = list(triples)  # 원본 복사
    
    for triple in triples:
        predicate = triple.get("predicate", "")
        
        if predicate in inverse_map:
            # 역관계 트리플 생성
            inverse_triple = {
                "subject": triple["object"],
                "predicate": inverse_map[predicate],
                "object": triple["subject"],
                "confidence": triple.get("confidence", 1.0),
                "source_chunk_id": triple.get("source_chunk_id"),
                "auto_generated": True  # 자동 생성 표시
            }
            result.append(inverse_triple)
    
    # 중복 제거 (역관계 추가 후)
    return deduplicate_triples(result)
