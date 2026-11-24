"""엔티티 이름 → URI local name 정리 보조 (ingest_service/app/core/fuseki_connector.py 와 같은 규칙)."""
import re

# 숫자 앞 부호는 뜻이 있다 ('+3점' ≠ '-3점'). URI 정리에서 '_' 로 뭉개지지 않게 먼저 단어로 바꾼다 (2026-11-24).
_SIGN_RE = re.compile(r"(?<![0-9A-Za-z\uAC00-\uD7A3])([+\-\u2212])(?=\d)")


def sign_words(text: str) -> str:
    return _SIGN_RE.sub(lambda m: "plus" if m.group(1) == "+" else "minus", text)
