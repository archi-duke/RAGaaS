"""근거 검증 범위 확대 (추출 품질 후속 B, 2026-11-25) — 근거 문장 선택·자동 제외 조건."""
from app.services.schema_alignment.direction_audit import _object_in_text, _sentences

TEXT = ("# Event-Driven Architecture\n"
        "Event-Driven Architecture는 확장성과 결합도 분리에는 강한 긍정 효과가 있다. "
        "감사 가능성과 가용성에는 중간 정도의 긍정 효과가 있다. "
        "한편 일관성에는 중간 정도의 부정 효과가 있다.")
AL = {"availability": ["가용성"]}


def test_alias_finds_original_sentence():
    # 11/25 첫 실행: 'Availability' 가 원문(가용성)에 없어 엉뚱한 문장만 보고 '근거 없음' 으로 뺐다
    ev = _sentences(TEXT, "Event-Driven Architecture", "Availability", AL)
    assert any("가용성" in s for s in ev)
    assert "가용성" in ev[0]          # 목적어가 나오는 문장이 먼저


def test_object_in_text_uses_aliases():
    t = {"subject": "Event-Driven Architecture", "object": "Availability"}
    assert _object_in_text(t, TEXT, AL)
    assert not _object_in_text(t, TEXT, {})


def test_hallucinated_object_is_absent():
    # cqrs.md 점수 규칙 청크에는 가용성 얘기가 없다 (11/24 CQRS→Availability)
    cqrs = "- 단순 CRUD 성격이 강하면 -3점.\n- 감사 가능성 요구가 높으면 +2점."
    assert not _object_in_text({"subject": "CQRS", "object": "Availability"}, cqrs, AL)
