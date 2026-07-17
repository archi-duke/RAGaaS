"""생성 쿼리의 스키마 정합성 검증 — 재시도 피드백 강화용.

LLM 이 생성한 Cypher/SPARQL 이 그래프에 존재하지 않는 관계/predicate 를
참조하면 실행은 되지만 0건이 나온다. 이 모듈은 쿼리가 참조한 도메인
관계/predicate 를 추출해 라이브 스키마 allow-list 와 대조하고, 없는 것이
있으면 사람이 읽을 수 있는 힌트 문자열을 만든다.

**설계 원칙: 차단하지 않는다.** 이 힌트는 QueryGenerationLoop 이 이미
실패(0건/예외)한 시도에 대해 재시도 프롬프트를 만들 때만 주입된다. 정상
동작하는 쿼리를 막지 않으므로 오탐으로 인한 회귀 위험이 없다. allow-list 가
비어 있거나(스키마 없음) 추출 실패 시엔 힌트를 만들지 않는다(추측 금지).
"""

import re
from typing import List, Optional, Set

# 항상 허용되는 표준 vocabulary prefix (도메인 predicate 가 아니므로 검증 제외)
_STANDARD_PREFIXES = {"rdf", "rdfs", "owl", "xsd", "skos", "dc", "dcterms", "foaf"}
# 검증 대상 도메인 predicate prefix
_DOMAIN_PREFIXES = {"rel", "prop"}


def _local_name(term: str) -> str:
    """prefix:local / <...#local> / <.../local> / local → local (소문자)."""
    t = term.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1]
    if "#" in t:
        t = t.rsplit("#", 1)[-1]
    elif "/" in t:
        t = t.rsplit("/", 1)[-1]
    elif ":" in t:
        t = t.split(":", 1)[-1]
    return t.strip().lower()


def extract_sparql_predicates(query: str) -> Set[str]:
    """SPARQL 에서 참조된 도메인 predicate 의 로컬네임 집합 추출.

    rel:xxx / prop:xxx (property path ^rel:a|rel:b 포함) 및
    <http://rag.local/rel/xxx> / <.../prop/xxx> 형태를 잡는다.
    표준 vocabulary(rdf:, rdfs: 등)와 변수(?x), 'a'(rdf:type 약어)는 제외.
    """
    found: Set[str] = set()

    # prefixed: rel:has_가족, prop:나이 등
    for m in re.finditer(r"\b([A-Za-z][\w]*)\s*:\s*([A-Za-z0-9_가-힣\-]+)", query):
        prefix, local = m.group(1).lower(), m.group(2)
        if prefix in _DOMAIN_PREFIXES:
            found.add(local.lower())

    # full URI: <http://rag.local/rel/xxx>, <.../prop/xxx>
    for m in re.finditer(r"<https?://[^>]*/(rel|prop)/([^>#/]+)>", query):
        found.add(m.group(2).lower())

    return found


def extract_cypher_rel_types(query: str) -> Set[str]:
    """Cypher 에서 참조된 관계 타입명 집합 추출 (소문자).

    [:TYPE], [r:TYPE], [:`TYPE`], [r:TYPE1|TYPE2] 형태를 잡는다.
    타입 없는 [r] / [] 는 검증 대상 아님(무시).
    """
    found: Set[str] = set()
    # [ optional-var : type (| type)* ] — 백틱/한글/영문/언더스코어 허용
    for m in re.finditer(r"\[\s*\w*\s*:\s*([^\]]+?)\s*\]", query):
        body = m.group(1)
        for part in body.split("|"):
            # 대체표기 [r:A|:B] 의 선행 콜론, 백틱, 공백 제거
            name = part.strip().lstrip(":").strip().strip("`").strip()
            # 방향/길이 지정자(*1..2) 등 제거
            name = re.sub(r"\*.*$", "", name).strip()
            if name:
                found.add(name.lower())
    return found


def find_unknown(referenced: Set[str], allowed: List[str]) -> List[str]:
    """참조된 로컬네임 중 allow-list 에 없는 것들 반환 (allow-list 비면 빈 리스트)."""
    if not allowed:
        return []
    allowed_locals = {_local_name(a) for a in allowed}
    return sorted(r for r in referenced if r not in allowed_locals)


def build_schema_hint(unknown: List[str], allowed: List[str], kind: str = "predicate", sample: int = 25) -> Optional[str]:
    """없는 관계/predicate 목록과 사용 가능 목록으로 재시도 힌트 문자열 생성.

    unknown 이 비어 있으면 None (힌트 불필요).
    """
    if not unknown or not allowed:
        return None
    allowed_sample = ", ".join(allowed[:sample])
    label = "관계 타입" if kind == "cypher" else "predicate"
    return (
        f"[스키마 검증] 위 쿼리는 그래프에 없는 {label} 를 참조했다: {', '.join(unknown)}\n"
        f"사용 가능한 {label} (일부): {allowed_sample}\n"
        f"위 목록에 있는 {label} 만 사용해 다시 생성하라. 이름을 추측하지 말 것."
    )


def sparql_schema_hint(query: str, allowed_predicates: List[str]) -> Optional[str]:
    """SPARQL 쿼리에 대한 스키마 힌트 (없으면 None). 예외 안전."""
    try:
        unknown = find_unknown(extract_sparql_predicates(query or ""), allowed_predicates)
        return build_schema_hint(unknown, allowed_predicates, kind="sparql")
    except Exception:
        return None


def cypher_schema_hint(query: str, allowed_rel_types: List[str]) -> Optional[str]:
    """Cypher 쿼리에 대한 스키마 힌트 (없으면 None). 예외 안전."""
    try:
        unknown = find_unknown(extract_cypher_rel_types(query or ""), allowed_rel_types)
        return build_schema_hint(unknown, allowed_rel_types, kind="cypher")
    except Exception:
        return None
