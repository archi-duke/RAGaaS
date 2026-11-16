"""관계 방향 검증(D1) — 근거 문장 추출."""
from app.services.schema_alignment.direction_audit import _sentences


def test_sentences_prefers_both_ends():
    text = ("아인슈타인은 뉴턴 역학의 한계를 지적했다. 아인슈타인은 젊은 시절 뉴턴의 저작에서 큰 영향을 받았다.\n"
            "보어는 코펜하겐에서 연구했다.")
    s = _sentences(text, "아인슈타인", "뉴턴")
    assert s[0].startswith("아인슈타인은 뉴턴 역학") or "영향을 받았다" in s[0]
    assert all("보어" not in x for x in s)          # 양끝과 무관한 문장 제외
    assert len(s) <= 3


def test_sentences_matches_name_tokens():
    # 라벨 '알베르트 아인슈타인' 의 토큰 '아인슈타인' 으로도 찾는다
    s = _sentences("아인슈타인이 뉴턴에게서 영향을 받았다.", "알베르트 아인슈타인", "아이작 뉴턴")
    assert s and "영향" in s[0]
