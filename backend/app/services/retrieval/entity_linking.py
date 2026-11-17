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
    """구분자를 모두 제거한 형태 ("micro-service" → "microservice").

    1글자 이름('줄', '암', '빛')은 tokens 가 버려 빈 문자열이 되면, 서로 다른 이름이 같은 키('')로
    충돌한다 (예: class 규칙 '줄 → Person' 이 1글자 엔티티 전부에 적용). 토큰이 없으면 구분자만 지운 원문.
    """
    out = "".join(tokens(text))
    if out:
        return out
    return re.sub(r"[\s_\-·.,/()\[\]]+", "", normalize_text(text))


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

    t_list, c_list = tokens(token), tokens(candidate)
    if t == c or (t_compact and t_compact == c_compact):
        base = 100.0
    elif t_list and len(c_list) > len(t_list) and c_list[-len(t_list):] == t_list:
        # 핵어 일치: 질문어가 후보의 마지막 토큰(들)과 같다 — '보어' ↔ '닐스_보어',
        # '아인슈타인' ↔ '알베르트_아인슈타인'. 한국어·영어 복합 명사는 핵어가 끝에 오므로
        # 후보가 곧 질문어가 가리키는 대상이다.
        base = 75.0
    elif t.startswith(c):
        # 질문어가 후보 + 조사 등 ('아인슈타인의' ↔ '아인슈타인')
        base = 60.0
    elif c.startswith(t):
        if t_list and c_list[:len(t_list)] == t_list:
            # 수식어 일치: 질문어가 복합어의 앞 토큰 — '보어_원자_모형' 은 보어가 아니라 모형이다
            base = 50.0
        else:
            # 질문어에 글자가 이어 붙음 (조사로 이어지는 문장 노드 '아인슈타인을_…', 다른 복합어)
            base = 35.0
    elif t_compact and c_compact and (c_compact.startswith(t_compact) or t_compact.startswith(c_compact)):
        base = 40.0
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


def degree_bonus(deg: int) -> float:
    """관계가 많이 달린 노드 선호 — 로그 스케일, 최대 18점.

    선형 8점 상한일 때는 성(姓)만 쓴 질문('아인슈타인')이 관계 21개짜리 인물 노드 대신
    관계 1~2개짜리 문장·복합어 노드에 연결됐다.
    """
    import math
    if deg <= 0:
        return 0.0
    return min(18.0, 4.0 * math.log2(1 + deg))


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


# ---------------------------------------------------------------------------
# 동일 엔티티 묶음 (검색 시) — docs/design/graph/design-graph-multihop-chain.md §7
# ---------------------------------------------------------------------------
# 텍스트 추출 그래프는 같은 대상을 여러 노드로 만든다: '볼츠만'(관계 17개) / '루트비히_볼츠만'(2개),
# '양자_전기역학' / '양자전기역학'. 앵커를 하나로만 잡으면 다른 노드에 달린 사실을 놓친다.
# 확실한 경우만 묶는다:
#   1. 구분자 제거 후 같은 이름 ('양자_전기역학' ≡ '양자전기역학')
#   2. 성(姓) ↔ 전체 이름: 한 토큰 이름이 2~3토큰 이름의 마지막 토큰과 같고, 둘 다 인물이 아닌
#      다른 유형으로 지정돼 있지 않으며, 숫자가 없고, 그런 전체 이름이 하나뿐일 때 ('플랑크' 는 막스·에르빈 둘이라 안 묶음)

PERSON_TYPE_HINTS = ("person", "인물", "사람", "scientist", "과학자")


def _is_person_type(types) -> bool:
    return any(any(h in str(t).lower() for h in PERSON_TYPE_HINTS) for t in types or ())


def _has_non_person_type(types) -> bool:
    return any(t and not any(h in str(t).lower() for h in PERSON_TYPE_HINTS) for t in types or ())


def equivalent_names(anchor: str, anchor_types, candidates) -> List[str]:
    """anchor 와 같은 대상으로 볼 수 있는 후보 이름들.

    candidates: {이름: 유형 집합}. anchor 자신은 결과에 넣지 않는다.
    """
    a_compact = _compact(anchor)
    a_toks = tokens(anchor)
    if not a_compact:
        return []
    out: List[str] = []
    surname_full: List[str] = []
    surname_single: List[str] = []
    for name, types in candidates.items():
        if name == anchor:
            continue
        c_toks = tokens(name)
        if _compact(name) == a_compact:
            out.append(name)
            continue
        if _has_non_person_type(anchor_types) or _has_non_person_type(types):
            continue
        if any(ch.isdigit() for ch in anchor + name):
            continue  # '1919년_일식' ↔ '일식' 은 성·이름 관계가 아니다
        if len(a_toks) == 1 and 2 <= len(c_toks) <= 3 and c_toks[-1] == a_toks[0] and len(a_toks[0]) >= 2:
            surname_full.append(name)
        elif len(c_toks) == 1 and 2 <= len(a_toks) <= 3 and a_toks[-1] == c_toks[0] and len(c_toks[0]) >= 2:
            surname_single.append(name)
    if len(surname_full) == 1:
        out.extend(surname_full)
    if len(surname_single) == 1:
        # 전체 이름 앵커 → 성 노드. 같은 성의 다른 전체 이름이 있으면 성 노드가 누구인지 모호하다.
        others = [n for n, t in candidates.items()
                  if n != anchor and 2 <= len(tokens(n)) <= 3 and tokens(n)[-1] == a_toks[-1]
                  and not _has_non_person_type(t)]
        if not others:
            out.extend(surname_single)
    return out


# 다단계 판정 보조: 관계를 서술하는 관형절(용언 + 관형형 어미)이 둘 이상 이어지는 질문
# "광전효과를 처음 발견한 사람의 박사 지도교수가 1847년에 제안한 법칙은?" → 발견한, 제안한
_RELATIVE_CLAUSE_RE = re.compile(r"(?<![가-힣])([가-힣]{2,}(?:한|된|던|친|닌|끈|준|받은))(?=\s|\(|$)")
_NOT_CLAUSE = {"같은", "다른", "모든", "어떤", "이러한", "그러한", "또한", "한", "단한"}


# 찾은 대상에 대해 이어서 묻는 질문: "…보정법은 무엇이며, 누가 몇 년에 제안했는가?" — 답(보정법)에서 한 홉 더 가야 한다.
# 뒤 질문이 '무엇' 이면 별개 질문일 수 있어 제외 (Q22 '…은 무엇이며, …개념은 무엇인가').
_FOLLOWUP_ASK_RE = re.compile(r"(무엇|누구|어디|어느\s*[가-힣]+|어떤\s*[가-힣]+)(이며|이고)\s*,?\s*(누가|언제|몇\s*년|어디서)")


def has_followup_ask(question: str) -> bool:
    """답으로 찾은 대상의 주체·시기·장소를 이어서 묻는가 (다단계 후보)."""
    return bool(_FOLLOWUP_ASK_RE.search(question or ""))


def relative_clause_count(question: str) -> int:
    """질문 안의 관계 서술 관형절 수 (대략). 2 이상이면 다단계 후보."""
    return sum(1 for w in _RELATIVE_CLAUSE_RE.findall(question or "") if w not in _NOT_CLAUSE)
