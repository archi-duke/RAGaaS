"""entity_linking 정규화/랭킹 회귀 테스트.

배경: 구조화(YAML) 문서의 snake_case 노드('micro_frontend')가 자연어 질문 엔티티
('Micro Frontend Architecture')와 연결되지 않아 그래프 검색이 0건이 되던 문제.
"""
from app.services.retrieval.entity_linking import (
    best_candidate,
    is_sentence_like,
    normalize_text,
    score_candidate,
)


def test_normalize_ignores_case_and_separators():
    assert normalize_text("Micro-Frontend") == "micro frontend"
    assert normalize_text("micro_frontend") == "micro frontend"
    assert normalize_text("  Single-SPA / Module Federation ") == "single spa module federation"


def test_natural_language_links_to_snake_case_node():
    assert score_candidate("Micro Frontend Architecture", "micro_frontend") > 0
    assert score_candidate("micro frontend", "micro_frontend") >= 100


def test_hyphen_and_plural_are_equivalent():
    assert score_candidate("micro-service", "microservices") >= 100


def test_unrelated_partial_overlap_rejected():
    # 토큰 하나만 겹치는 다른 개념은 매칭하지 않는다
    assert score_candidate("micro-service architecture", "micro_frontend") == 0.0


def test_exact_beats_longer_noise_candidates():
    cands = ["성기훈의 어머니", "성기훈", "기훈에게 사람의 본성으로 인해 생긴 일"]
    assert best_candidate("성기훈", cands) == "성기훈"


def test_sentence_like_node_is_demoted():
    sentence = "프론트엔드를 독립 배포 가능한 여러 애플리케이션으로 분할하는 구조."
    assert is_sentence_like(sentence)
    assert score_candidate("프론트엔드", sentence) < score_candidate("프론트엔드", "프론트엔드 팀")


def test_reference_title_loses_to_concept_node():
    cands = ["Geers, Micro Frontends in Action", "micro_frontend"]
    assert best_candidate("Micro Frontend Architecture", cands) == "micro_frontend"


def test_function_words_never_link():
    # 'of' ⊂ 'tradeoffs', 'are' ⊂ 'shared' — 글자 단위 포함으로 연결되면 안 된다
    assert score_candidate("of", "root_0_tradeoffs_22") == 0.0
    assert score_candidate("are", "shared_routing") == 0.0
    assert score_candidate("architecture", "root_0_tradeoffs_22") == 0.0


def test_english_substring_requires_word_boundary():
    assert score_candidate("routing", "shared_routing") > 0      # 단어 단위 포함은 허용
    assert score_candidate("outing", "shared_routing") == 0.0    # 단어 중간 조각은 불허


def test_korean_short_name_partial_match_kept():
    # 한글은 조사가 붙으므로 글자 단위 포함을 유지 (2글자 이름 포함)
    assert score_candidate("성기훈", "기훈") > 0
    assert score_candidate("장풍", "장풍의 고수") > 0


# --- 성(姓)만 쓴 질문의 링킹 (물리학사 평가 Q07·Q13·Q14·Q27·Q32) ---

def test_surname_links_to_full_name_not_compound_or_sentence():
    assert best_candidate("아인슈타인", ["아인슈타인을_게으른_개_라고_불렀다", "알베르트_아인슈타인"]) == "알베르트_아인슈타인"
    assert best_candidate("보어", ["보어_원자_모형", "닐스_보어"]) == "닐스_보어"
    assert best_candidate("슈뢰딩거", ["슈뢰딩거_방정식", "에르빈_슈뢰딩거"]) == "에르빈_슈뢰딩거"
    assert best_candidate("뉴턴", ["뉴턴_역학", "아이작_뉴턴"]) == "아이작_뉴턴"
    assert best_candidate("플랑크", ["플랑크_복사_법칙", "막스_플랑크"]) == "막스_플랑크"


def test_compound_still_links_when_no_person_node():
    # 인물 노드가 없으면 복합어라도 연결은 된다 (수식어 일치)
    assert score_candidate("보어", "보어_원자_모형") >= 25


def test_question_word_with_particle_links():
    assert score_candidate("아인슈타인의", "아인슈타인") >= 60


def test_degree_bonus_log_scale():
    from app.services.retrieval.entity_linking import degree_bonus
    assert degree_bonus(0) == 0.0
    assert degree_bonus(1) < degree_bonus(3) < degree_bonus(21) <= 18.0


# --- 동일 엔티티 묶음 ---

def test_equivalent_compact_and_surname():
    from app.services.retrieval.entity_linking import equivalent_names as eq
    assert eq("양자_전기역학", {"TheoryOrConcept"}, {"양자전기역학": {"TheoryOrConcept"}, "재규격화된_양자전기역학": set()}) == ["양자전기역학"]
    assert eq("볼츠만", {"Person"}, {"루트비히_볼츠만": set(), "맥스웰_볼츠만_분포": set(), "볼츠만_엔트로피_공식": set()}) == ["루트비히_볼츠만"]
    assert eq("루트비히_볼츠만", set(), {"볼츠만": {"Person"}}) == ["볼츠만"]
    assert eq("드브로이", set(), {"루이_드브로이": set()}) == ["루이_드브로이"]


def test_equivalent_rejects_ambiguous_or_typed_mismatch():
    from app.services.retrieval.entity_linking import equivalent_names as eq
    # 막스·에르빈 플랑크 둘 → 성 노드는 묶지 않음
    assert eq("플랑크", {"Person"}, {"막스_플랑크": {"Person"}, "에르빈_플랑크": set()}) == []
    assert eq("막스_플랑크", {"Person"}, {"플랑크": {"Person"}, "에르빈_플랑크": set()}) == []
    # 개념 유형은 성 규칙 대상 아님
    assert eq("전기역학", set(), {"양자_전기역학": {"TheoryOrConcept"}}) == []


def test_equivalent_skips_names_with_digits():
    from app.services.retrieval.entity_linking import equivalent_names as eq
    assert eq("1919년_일식", set(), {"일식": set()}) == []


def test_relative_clause_count():
    from app.services.retrieval.entity_linking import relative_clause_count as rc
    assert rc("광전효과를 처음 발견한 사람의 박사 지도교수가 1847년에 제안한 법칙은 무엇인가?") == 2
    assert rc("『알마게스트』를 저술한 사람은 누구인가?") == 1
    assert rc("슈뢰딩거와 같은 해에 상을 받은 사람은?") <= 1   # "같은" 은 관형절로 세지 않음
