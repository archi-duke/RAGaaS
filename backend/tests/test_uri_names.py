"""URI local name 의 숫자 부호 보존 (ingest_service fuseki_connector 와 같은 규칙, 2026-11-24)."""
from app.core.uri_names import sign_words


def test_sign_words():
    assert sign_words("+3점") == "plus3점"
    assert sign_words("높으면 -2점") == "높으면 minus2점"
    assert sign_words("3-5년") == "3-5년"
    assert sign_words("Micro-Frontend") == "Micro-Frontend"
