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
