"""엔티티 링킹 랭킹 유틸리티.

그래프 백엔드(Neo4j/Fuseki)가 질문 토큰을 그래프의 실제 노드/라벨에 연결할 때,
CONTAINS 부분매칭은 후보를 여러 개 만든다(예: "성기훈" → "성기훈", "기훈",
"성기훈의 어머니", "기훈에게 사람의 본성으로 인해 …" 등). 임의 첫 매치(LIMIT 1)를
고르면 긴 노이즈 노드가 앵커로 잡혀 검색 정확도가 무너진다.

여기서는 후보를 다음 우선순위로 점수화해 가장 좋은 후보를 고른다:
  1. 정규화 완전일치               (가장 강함)
  2. 접두 일치(어느 쪽이 다른 쪽으로 시작)
  3. 토큰 단위 포함 / 양방향 부분 포함
  4. 토큰 겹침(Jaccard) — 어순·부가어가 달라도 핵심 토큰이 겹치면 약하게 매칭
동점이면 토큰과 길이가 가까운(=노이즈가 적은) 후보를 선호한다.

정규화: 대소문자, '_' / '-' / 공백 / 구두점 차이, 영어 단순 복수형(-s)을 무시한다.
  예) "Micro Frontend Architecture" ↔ "micro_frontend"   (토큰 포함)
      "micro-service"              ↔ "microservices"    (구분자·복수형 무시)
구조화(JSON/YAML) 문서는 키·id 가 snake_case/kebab-case 로 들어오므로 이 정규화가
없으면 자연어 질문의 엔티티가 거의 연결되지 않는다.
"""

import re
import unicodedata
from typing import List, Optional, Set, Tuple

_SEP_RE = re.compile(r"[\s_\-/.,:;()\[\]{}\"'`]+")

# 문장형 노드(서술문이 노드로 승격된 경우)를 앵커로 잡지 않기 위한 기준 길이.
SENTENCE_LIKE_LEN = 40

# 엔티티로 연결하면 안 되는 영어 기능어/의문사. ('of' 가 'tradeoffs' 에, 'are' 가
# 'shared' 에 글자 단위로 포함돼 엉뚱한 노드가 앵커로 잡히던 문제 방지)
STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "by", "with", "from", "and", "or",
    "is", "are", "was", "were", "be", "been", "do", "does", "did", "what", "which", "who",
    "whom", "whose", "when", "where", "why", "how", "it", "its", "this", "that", "these",
    "those", "about", "tell", "me", "list", "give", "show", "can", "could", "should", "would",
    "there", "any", "some", "all",
}


def normalize_text(text: str) -> str:
    """대소문자·구분자 차이를 없앤 비교용 문자열 ("Micro-Frontend" → "micro frontend")."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower()
    return _SEP_RE.sub(" ", t).strip()


def _stem(token: str) -> str:
    # 영어 단순 복수형만 처리 (services→service, frontends→frontend). 한글은 그대로.
    if len(token) > 3 and token.isascii() and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str) -> List[str]:
    """정규화 + 어간화된 토큰 목록 (1글자 토큰 제외)."""
    return [_stem(t) for t in normalize_text(text).split() if len(t) > 1]


def _compact(text: str) -> str:
    """구분자를 모두 제거한 형태 ("micro-service" → "microservice")."""
    return "".join(tokens(text))


def is_sentence_like(label: str) -> bool:
    """서술문이 노드 라벨이 된 경우 (예: summary/description 값)."""
    if not label:
        return False
    stripped = label.strip()
    return len(stripped) > SENTENCE_LIKE_LEN or "\n" in stripped or stripped.endswith(".")


def is_linkable(token: str) -> bool:
    """링킹 대상이 될 수 있는 토큰인가 (기능어·너무 짧은 영어 토큰 제외)."""
    t = normalize_text(token)
    if not t or t in STOPWORDS:
        return False
    if t.isascii() and len(t.replace(" ", "")) < 3:
        return False
    return True


def _contains(outer: str, inner: str) -> bool:
    """부분 포함. ASCII(영어)는 단어 경계 기준, 한글 등은 글자 단위(조사 붙음 대응)."""
    if inner.isascii():
        return f" {inner} " in f" {outer} "
    return inner in outer


def score_candidate(token: str, candidate: str) -> float:
    """질문 토큰과 후보 문자열의 링킹 점수. 매칭 안 되면 0.0."""
    if not token or not candidate:
        return 0.0
    if not is_linkable(token):
        return 0.0

    t = normalize_text(token)
    c = normalize_text(candidate)
    if not t or not c:
        return 0.0

    t_tokens: Set[str] = set(tokens(token))
    c_tokens: Set[str] = set(tokens(candidate))
    t_compact, c_compact = _compact(token), _compact(candidate)

    if t == c or (t_compact and t_compact == c_compact):
        base = 100.0
    elif c.startswith(t) or t.startswith(c) or (
        t_compact and c_compact and (c_compact.startswith(t_compact) or t_compact.startswith(c_compact))
    ):
        base = 60.0
    elif c_tokens and t_tokens and (c_tokens <= t_tokens or t_tokens <= c_tokens):
        # 토큰 단위 포함: "micro frontend architecture" ⊇ "micro frontend"
        base = 40.0
    elif _contains(c, t) or ((not c.isascii() or len(c) >= 3) and _contains(t, c)):
        base = 30.0
    else:
        inter = t_tokens & c_tokens
        union = t_tokens | c_tokens
        jaccard = len(inter) / len(union) if union else 0.0
        if jaccard < 0.5:
            return 0.0
        base = 20.0 * jaccard

    # 길이 근접 보너스: 후보가 토큰보다 길수록(노이즈 노드일수록) 감점.
    # 최대 20점 범위에서 길이 차에 비례해 차감한다.
    len_gap = abs(len(c) - len(t))
    proximity = max(0.0, 20.0 - len_gap)
    score = base + proximity
    if is_sentence_like(candidate):
        # 서술문 노드는 앵커로 부적합 — 다른 후보가 있으면 밀리도록 크게 감점
        score *= 0.3
    return score


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
