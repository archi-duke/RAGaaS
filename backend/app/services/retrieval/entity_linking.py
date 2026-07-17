"""엔티티 링킹 랭킹 유틸리티.

그래프 백엔드(Neo4j/Fuseki)가 질문 토큰을 그래프의 실제 노드/라벨에 연결할 때,
CONTAINS 부분매칭은 후보를 여러 개 만든다(예: "성기훈" → "성기훈", "기훈",
"성기훈의 어머니", "기훈에게 사람의 본성으로 인해 …" 등). 임의 첫 매치(LIMIT 1)를
고르면 긴 노이즈 노드가 앵커로 잡혀 검색 정확도가 무너진다.

여기서는 후보를 다음 우선순위로 점수화해 가장 좋은 후보를 고른다:
  1. 대소문자 무시 완전일치        (가장 강함)
  2. 접두 일치(어느 쪽이 다른 쪽으로 시작)
  3. 양방향 부분 포함
동점이면 토큰과 길이가 가까운(=노이즈가 적은) 후보를 선호한다.
"""

from typing import List, Optional, Tuple


def score_candidate(token: str, candidate: str) -> float:
    """질문 토큰과 후보 문자열의 링킹 점수. 매칭 안 되면 0.0."""
    if not token or not candidate:
        return 0.0

    t = token.strip().lower()
    c = candidate.strip().lower()
    if not t or not c:
        return 0.0

    if t == c:
        base = 100.0
    elif c.startswith(t) or t.startswith(c):
        base = 60.0
    elif t in c or c in t:
        base = 30.0
    else:
        return 0.0

    # 길이 근접 보너스: 후보가 토큰보다 길수록(노이즈 노드일수록) 감점.
    # 최대 20점 범위에서 길이 차에 비례해 차감한다.
    len_gap = abs(len(candidate) - len(token))
    proximity = max(0.0, 20.0 - len_gap)
    return base + proximity


def rank_candidates(token: str, candidates: List[str]) -> List[Tuple[str, float]]:
    """후보들을 점수 내림차순으로 정렬해 (후보, 점수) 리스트 반환 (점수 0 제외)."""
    scored = [(c, score_candidate(token, c)) for c in candidates]
    scored = [(c, s) for c, s in scored if s > 0.0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def best_candidate(token: str, candidates: List[str]) -> Optional[str]:
    """가장 점수가 높은 후보 문자열 반환. 매칭 후보가 없으면 None."""
    ranked = rank_candidates(token, candidates)
    return ranked[0][0] if ranked else None
