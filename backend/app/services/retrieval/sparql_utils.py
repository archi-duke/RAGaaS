"""SPARQL 쿼리 f-string 삽입 시 사용하는 이스케이프 유틸리티.

graph_backends/fuseki.py 등에서 사용자 입력(엔티티 텍스트, 질문 등)을
SPARQL 쿼리 문자열에 f-string으로 직접 삽입할 때 인젝션/구문 파괴를
방지하기 위해 사용한다.
"""


def escape_sparql_literal(s: str) -> str:
    """SPARQL 문자열 리터럴(따옴표로 감싼 값)에 안전하게 삽입하도록 이스케이프.

    SPARQL 1.1 문자열 리터럴 이스케이프 규칙에 따라 백슬래시를 가장 먼저
    이스케이프한 뒤 큰따옴표, 개행, 캐리지리턴, 탭을 순서대로 처리한다.
    None이 들어오면 빈 문자열을 반환한다.
    """
    if s is None:
        return ""
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return s


def escape_sparql_regex(s: str) -> str:
    """SPARQL REGEX FILTER에 삽입할 정규식 메타문자를 이스케이프.

    `regex(?label, "(패턴)", "i")` 형태의 FILTER에 사용자 유래 문자열을
    넣을 때, 정규식 메타문자(`.*+?^${}()|[]\\`)가 의도치 않게 해석되지
    않도록 각 메타문자 앞에 백슬래시를 붙인다. (re.escape는 지나치게
    많은 문자를 이스케이프하므로 사용하지 않는다.)
    """
    chars_to_escape = r".*+?^${}()|[]\\"
    for char in chars_to_escape:
        s = s.replace(char, "\\" + char)
    return s
