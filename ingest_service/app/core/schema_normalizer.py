"""KB 스키마 매핑 규칙 적용 — 구조화 문서 트리 정규화 (순수 함수).

설계: docs/design-schema-mismatch.md §5

규칙은 backend(Mongo)가 소유하고 인제스트 요청에 실어 보낸다. 여기서는 파싱된 트리의
레코드 루트마다 다음 순서로 적용한다 (트리에 적용해야 identity·구조 노드·청크 텍스트·
트리플이 모두 표준 키·값으로 일관되게 나온다):
  1. key 규칙 (source 경로가 긴 것부터) — 이름 변경, 중첩 이동
  2. 자동 표기 정규화(키) — KB 어휘와 compact 완전일치이면서 표기만 다른 키 (testingComplexity)
  3. value 규칙 — 스칼라 값 전체 일치만 (문장 속 '높음' 은 그대로)
  4. 자동 표기 정규화(값) — enum 어휘와 compact 완전일치이면서 표기만 다른 값 (High → high)
id/name/label/type 키는 자동 정규화 대상에서 제외한다.
"""

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

_SEP_RE = re.compile(r"[\s_\-/.,:;()\[\]{}\"'`]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
PROTECTED_KEYS = {"id", "name", "label", "type", "_type", "title"}


def _stem(token: str) -> str:
    if len(token) > 3 and token.isascii() and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def compact(text: Any) -> str:
    """backend entity_linking._compact 와 같은 규칙 + camelCase 분리."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = _CAMEL_RE.sub(" ", t).lower()
    t = _SEP_RE.sub(" ", t).strip()
    out = "".join(_stem(x) for x in t.split() if len(x) > 1)
    # 1글자 이름('줄')이 빈 키가 되어 서로 충돌하지 않도록 (backend _compact 와 같은 규칙)
    return out or t.replace(" ", "")


def _segs(path: str) -> List[str]:
    return [s for s in str(path or "").split(".") if s]


# ---------------------------------------------------------------------------
# 규칙 검증
# ---------------------------------------------------------------------------

def validate_rule(rule: Dict[str, Any]) -> Optional[str]:
    """규칙 형식 검증. 문제 없으면 None, 있으면 사유."""
    rt = rule.get("rule_type")
    if rt == "key":
        s, t = _segs(rule.get("source_path")), _segs(rule.get("target_path"))
        if not s or not t:
            return "source_path/target_path 필요"
        if s == t:
            return "source 와 target 이 같음"
        return None
    if rt == "value":
        if not str(rule.get("source_value") or "").strip() or not str(rule.get("target_value") or "").strip():
            return "source_value/target_value 필요"
        return None
    if rt == "ignore":
        return None
    return f"알 수 없는 rule_type: {rt}"


# ---------------------------------------------------------------------------
# 트리 연산
# ---------------------------------------------------------------------------

def _merge(existing: Any, incoming: Any) -> Any:
    """대상 키가 이미 있을 때 병합: 리스트 이어붙임, dict 재귀, 스칼라 → 리스트."""
    if isinstance(existing, dict) and isinstance(incoming, dict):
        out = dict(existing)
        for k, v in incoming.items():
            out[k] = _merge(out[k], v) if k in out else v
        return out
    a = existing if isinstance(existing, list) else [existing]
    b = incoming if isinstance(incoming, list) else [incoming]
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out


def _find_key(d: Dict[str, Any], seg: str) -> Optional[str]:
    """dict 에서 세그먼트에 해당하는 실제 키 (정확 일치 우선, 없으면 compact 일치)."""
    if seg in d:
        return seg
    c = compact(seg)
    for k in d:
        if compact(k) == c:
            return k
    return None


def _pop_path(node: Dict[str, Any], segs: List[str]) -> Tuple[bool, Any]:
    cur = node
    for s in segs[:-1]:
        k = _find_key(cur, s) if isinstance(cur, dict) else None
        if k is None or not isinstance(cur[k], dict):
            return False, None
        cur = cur[k]
    k = _find_key(cur, segs[-1]) if isinstance(cur, dict) else None
    if k is None:
        return False, None
    val = cur.pop(k)
    return True, val


def _prune_empty(node: Dict[str, Any], segs: List[str]) -> None:
    """이동 후 빈 부모 dict 제거 (평탄화)."""
    if len(segs) < 2:
        return
    chain = []
    cur = node
    for s in segs[:-1]:
        k = _find_key(cur, s) if isinstance(cur, dict) else None
        if k is None or not isinstance(cur.get(k), dict):
            return
        chain.append((cur, k))
        cur = cur[k]
    for parent, k in reversed(chain):
        if parent[k] == {}:
            del parent[k]
        else:
            break


def _set_path(node: Dict[str, Any], segs: List[str], value: Any) -> bool:
    cur = node
    for s in segs[:-1]:
        k = _find_key(cur, s)
        if k is None:
            cur[s] = {}
            k = s
        if not isinstance(cur[k], dict):
            return False
        cur = cur[k]
    k = _find_key(cur, segs[-1])
    if k is None:
        cur[segs[-1]] = value
        return False
    cur[k] = _merge(cur[k], value)
    return True


def _apply_key_rule(node: Any, src: List[str], tgt: List[str]) -> Tuple[int, int]:
    """key 규칙 적용. 공통 접두가 리스트를 지나면 리스트 항목마다 적용. (적용 수, 병합 수)"""
    applied = merged = 0
    if isinstance(node, list):
        for item in node:
            a, m = _apply_key_rule(item, src, tgt)
            applied += a
            merged += m
        return applied, merged
    if not isinstance(node, dict):
        return 0, 0
    # 같은 첫 세그먼트를 공유하고 그 값이 리스트면 리스트 안으로 내려가 적용 (배열 항목 내 키)
    if len(src) > 1 and len(tgt) > 1 and compact(src[0]) == compact(tgt[0]):
        k = _find_key(node, src[0])
        if k is not None and isinstance(node[k], list):
            return _apply_key_rule(node[k], src[1:], tgt[1:])
    found, val = _pop_path(node, src)
    if not found:
        return 0, 0
    _prune_empty(node, src)
    if _set_path(node, tgt, val):
        merged += 1
    return 1, merged


def _walk_keys(node: Any, prefix: List[str], visit) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_keys(item, prefix, visit)
    elif isinstance(node, dict):
        for k in list(node.keys()):
            new_k = visit(node, k, prefix)
            _walk_keys(node[new_k], prefix + [new_k], visit)


def _walk_values(node: Any, prefix: List[str], visit) -> None:
    if isinstance(node, list):
        for i, item in enumerate(node):
            if isinstance(item, (dict, list)):
                _walk_values(item, prefix, visit)
            else:
                node[i] = visit(item, prefix)
    elif isinstance(node, dict):
        for k in list(node.keys()):
            v = node[k]
            if isinstance(v, (dict, list)):
                _walk_values(v, prefix + [k], visit)
            else:
                node[k] = visit(v, prefix + [k])


# ---------------------------------------------------------------------------
# 정규화
# ---------------------------------------------------------------------------

def normalize_record(
    record: Dict[str, Any],
    rules: Optional[List[Dict[str, Any]]] = None,
    vocab: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """레코드(dict)를 제자리에서 정규화하고 보고서를 반환.

    vocab: {"paths": [표준 경로 키…], "enum_values": {경로키: [표준 값…]}}
    보고서: {"applied": [{rule_id, count}], "auto": [{kind, source, target}], "merged": [...]}
    """
    rules = [r for r in (rules or []) if r.get("status", "active") == "active" and not validate_rule(r)]
    vocab = vocab or {}
    report: Dict[str, Any] = {"applied": [], "auto": [], "merged": []}

    # 1. key 규칙 (긴 source 부터)
    key_rules = sorted([r for r in rules if r["rule_type"] == "key"],
                       key=lambda r: -len(_segs(r["source_path"])))
    for r in key_rules:
        n, m = _apply_key_rule(record, _segs(r["source_path"]), _segs(r["target_path"]))
        if n:
            report["applied"].append({"rule_id": r.get("id"), "count": n,
                                      "source": r["source_path"], "target": r["target_path"]})
        if m:
            report["merged"].append({"target": r["target_path"], "count": m})

    # 2. 자동 표기 정규화 (키)
    vocab_paths = list(vocab.get("paths") or [])
    by_parent: Dict[str, Dict[str, str]] = {}
    for p in vocab_paths:
        segs = _segs(p)
        by_parent.setdefault(".".join(segs[:-1]), {})[compact(segs[-1])] = segs[-1]

    def rename_key(parent: Dict[str, Any], k: str, prefix: List[str]) -> str:
        if k in PROTECTED_KEYS:
            return k
        canon = by_parent.get(".".join(prefix), {}).get(compact(k))
        if canon and canon != k and canon not in parent:
            parent[canon] = parent.pop(k)
            report["auto"].append({"kind": "key", "source": ".".join(prefix + [k]),
                                   "target": ".".join(prefix + [canon])})
            return canon
        return k

    if by_parent:
        _walk_keys(record, [], rename_key)

    # 3. value 규칙 (값 전체 일치만) + 4. 자동 표기 정규화 (값)
    value_rules = [r for r in rules if r["rule_type"] == "value"]
    enum_values = {k: {compact(v): v for v in vs} for k, vs in (vocab.get("enum_values") or {}).items()}
    counts: Dict[Any, int] = {}

    def fix_value(v: Any, path: List[str]) -> Any:
        if not isinstance(v, str) or not path or path[-1] in PROTECTED_KEYS:
            return v
        key = ".".join(path)
        cv = compact(v)
        if not cv:
            return v
        for r in value_rules:
            scope = r.get("scope_paths") or ["*"]
            if ("*" in scope or key in scope) and cv == compact(r["source_value"]):
                counts[r.get("id")] = counts.get(r.get("id"), 0) + 1
                return r["target_value"]
        canon = enum_values.get(key, {}).get(cv)
        if canon and canon != v:
            report["auto"].append({"kind": "value", "source": v, "target": canon, "path": key})
            return canon
        return v

    if value_rules or enum_values:
        _walk_values(record, [], fix_value)
    for r in value_rules:
        if counts.get(r.get("id")):
            report["applied"].append({"rule_id": r.get("id"), "count": counts[r.get("id")],
                                      "source": r["source_value"], "target": r["target_value"]})
    return report


def merge_reports(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"applied": [], "auto": [], "merged": []}
    for r in reports:
        for k in out:
            out[k].extend(r.get(k) or [])
    # auto 중복 제거
    seen, uniq = set(), []
    for a in out["auto"]:
        key = (a["kind"], a["source"], a["target"])
        if key not in seen:
            seen.add(key)
            uniq.append(a)
    out["auto"] = uniq
    return out


def apply_to_triples(triples: List[Dict[str, Any]], rules: Optional[List[Dict[str, Any]]]) -> int:
    """텍스트(LLM 추출) 문서: 단일 세그먼트 key 규칙만 predicate 에 적용."""
    mapping = {}
    for r in rules or []:
        if r.get("rule_type") == "key" and r.get("status", "active") == "active":
            s, t = _segs(r.get("source_path")), _segs(r.get("target_path"))
            if len(s) == 1 and len(t) == 1:
                mapping[compact(s[0])] = t[0]
    n = 0
    if not mapping:
        return 0
    for t in triples:
        tgt = mapping.get(compact(t.get("predicate")))
        if tgt and t.get("predicate") != tgt:
            t["predicate"] = tgt
            n += 1
    return n


# ---------------------------------------------------------------------------
# 연도 분리 (데이터 품질 D4 Y1 — docs/design-year-attributes.md §3.2)
# ---------------------------------------------------------------------------

_YEAR_MIN, _YEAR_MAX = 1000, 2100
# 'X (1933년)', 'X(1939)', '『…』 (1638년 출간)', '프린시페섬(1919년 일식)'
_RE_YEAR_PAREN = re.compile(r"^(?P<base>.+?)\s*\((?P<text>(?P<y>\d{4})년?(?:\s*[가-힣]{1,4})?)\)$")
# '기체 분자 속도 분포, 1860년'
_RE_YEAR_COMMA = re.compile(r"^(?P<base>.+?),\s*(?P<text>(?P<y>\d{4})년)$")
# '1908년 쾰른 강연', '1919년 11월 런던 …', '1900년 12월 14일 …'
_RE_YEAR_LEAD = re.compile(r"^(?P<text>(?P<y>\d{4})년(?:\s+\d{1,2}월(?:\s+\d{1,2}일)?)?)\s+(?P<base>.+)$")
# 앞 연도 뒤의 나머지가 시점 표현이면 떼지 않는다 ('1919년 발표 이후' → '발표 이후' 는 값이 아니다)
_LEAD_STOP = re.compile(r"(이후|이전|무렵|전후|경|부터|까지)$|^[(（]")
# 남는 값이 날짜·시점 조각뿐이면 값 전체가 시점이다 ('1900년 10월', '1610년 초', '1900년 12월 14일') → 떼지 않는다
_DATE_ONLY = re.compile(r"^(\d{1,2}월(\s*\d{1,2}일)?|\d{1,2}일|초|초반|중반|중순|말|말경|후반|하반기|상반기|봄|여름|가을|겨울)$")


def split_year(value: Any) -> Optional[Tuple[str, int, str]]:
    """값 끝·앞에 붙은 연도를 떼어 (기본값, 연도, 원문 연도 표기) 로 돌려준다. 해당 없으면 None.

    결정적 규칙만 쓴다 (LLM 없음). 연도 하나짜리 정확한 표기만 다룬다 — '1850년대', '1801~1803년',
    '1665년부터 1666년' 같은 범위·대략값은 건드리지 않는다 (Y2 범위).
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    for rx in (_RE_YEAR_PAREN, _RE_YEAR_COMMA, _RE_YEAR_LEAD):
        m = rx.match(v)
        if not m:
            continue
        base, y = m.group("base").strip(), int(m.group("y"))
        if not (_YEAR_MIN <= y <= _YEAR_MAX) or not base or re.search(r"\d{4}", base):
            return None
        if _DATE_ONLY.match(base):
            return None
        if rx is _RE_YEAR_LEAD and _LEAD_STOP.search(base):
            return None
        return base, y, m.group("text").strip()
    return None


def apply_year_split(t: Dict[str, Any]) -> bool:
    """트리플의 목적어에서 연도를 떼어 진술 연도(year·year_text)로 옮긴다. 이미 year 가 있으면 값만 정리한다."""
    r = split_year(t.get("object"))
    if not r:
        return False
    base, y, text = r
    if t.get("year") not in (None, y):
        return False   # 추출이 낸 연도와 다르면 손대지 않는다
    t["object_raw"] = t.get("object")
    t["object"], t["year"], t["year_text"] = base, y, text
    return True


# ---------------------------------------------------------------------------
# 트리플 리플레이 (텍스트/LLM 추출 그래프의 ABox 재구성 — docs/design-graph-promotion.md §3(c))
# ---------------------------------------------------------------------------

def _added_triples(rules: List[Dict[str, Any]], triples: List[Dict[str, Any]],
                   doc_id: Optional[str]) -> List[Dict[str, Any]]:
    """'트리플 추가' 규칙(@add) → 이 문서에 넣을 트리플. 사람이 원문(청크)을 확인해 고정한 사실이라
    추출 편차·도메인 검사로 빠져도 리플레이·재추출 뒤에 다시 들어간다.
    규칙: pair=[주어, 관계, 목적어], source_value=근거 청크 ID, scope_paths=[문서 ID], target_value=연도(선택)."""
    chunks = {t.get("source_node_id") for t in triples}
    out = []
    for r in rules:
        if r.get("rule_type") != "triple" or r.get("target_path") != "@add" or not r.get("pair") or len(r["pair"]) != 3:
            continue
        scope = [x for x in (r.get("scope_paths") or []) if x and x != "*"]
        if doc_id is not None and scope:
            if doc_id not in scope:
                continue
        elif r.get("source_value") not in chunks:
            continue
        s_, p_, o_ = r["pair"]
        t = {"subject": s_, "predicate": p_, "object": o_, "source_node_id": r.get("source_value"),
             "confidence": 1.0, "out_of_schema": False, "extraction": "user_added", "edited": "added"}
        if str(r.get("target_value") or "").isdigit():
            t["year"] = int(r["target_value"])
        out.append(t)
    return out


def apply_rules_to_triples(
    triples: List[Dict[str, Any]], rules: Optional[List[Dict[str, Any]]], doc_id: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """평면 트리플(LLM 추출)에 KB 규칙을 결정적으로 적용한 새 목록과 보고서.

    적용 순서: year(값에서 연도 분리) → entity(엔티티 병합, 주어·목적어) → key(predicate, 마지막 세그먼트)
              → value(목적어 전체 일치, scope) → class(엔티티 → 클래스, subject_type/object_type)
    입력은 변경하지 않는다 (raw 사본에서 항상 다시 계산 → 멱등).
    """
    active = [r for r in (rules or []) if r.get("status", "active") == "active"]
    entity_map = {compact(r["source_value"]): r["target_value"] for r in active
                  if r.get("rule_type") == "entity" and r.get("source_value") and r.get("target_value")}
    # 이름 규칙은 끝까지 따라간다 ('아르놀트 조머펠트 → 조머펠트' 뒤에 병합 '조머펠트 → 아르놀드 조머펠트' 가 생기면
    # 한 번만 적용해서는 '조머펠트' 에 멈춘다 — 2026-11-16 데이터 품질 D2). 순환은 끊는다.
    def _resolve(name: Any) -> Any:
        cur, seen = name, set()
        for _ in range(10):
            k = compact(cur)
            if k in seen:
                break
            seen.add(k)
            nxt = entity_map.get(k)
            if not nxt or nxt == cur:
                break
            cur = nxt               # 표기 바꾸기는 항상 적용 ('맥스웰' → 'J. C. 맥스웰' 은 정규화 키가 같아도)
            if compact(nxt) == k:   # 같은 키 안의 표기 변경이면 여기서 끝 (순환 방지)
                break
        return cur
    key_map = {}
    for r in active:
        if r.get("rule_type") == "key":
            s, t = _segs(r.get("source_path")), _segs(r.get("target_path"))
            if s and t:
                key_map[compact(s[-1])] = t[-1]
    value_rules = [r for r in active if r.get("rule_type") == "value" and r.get("source_value")]
    class_map = {compact(r["source_value"]): r["target_value"] for r in active
                 if r.get("rule_type") == "class" and r.get("source_value") and r.get("target_value")}
    # triple 규칙: 사람이 트리플 단위로 고친 것 (스키마 편집기 트리플 목록) — pair=[주어, 관계, 목적어] 는
    # entity·key·value 적용 뒤의 표기(화면에 보이는 그래프 표기)로 맞춘다. target_path=새 관계(이동), 없으면 삭제,
    # "@flip" 이면 같은 관계로 주어·목적어를 뒤집는다.
    triple_map = {}
    for r in active:
        if r.get("rule_type") == "triple" and r.get("pair") and len(r["pair"]) == 3 and r.get("target_path") != "@add":
            s_, p_, o_ = r["pair"]
            # 트리플 규칙의 주어·목적어도 이름 규칙을 거친 표기로 맞춘다 — 나중에 병합이 생겨도
            # 앞서 한 뒤집기·이동·삭제가 조용히 풀리지 않게 (예: 뒤집기 규칙 '파울리|지도교수_of|조머펠트' 뒤에
            # '조머펠트 → 아르놀드 조머펠트' 병합)
            triple_map[(compact(_resolve(s_)), compact(p_), compact(_resolve(o_)))] = r.get("target_path") or None

    added = _added_triples(active, triples, doc_id)
    triples = list(triples) + added
    counts = {"added": len(added), "year": 0, "entity": 0, "key": 0, "value": 0, "class": 0, "triple_moved": 0, "triple_deleted": 0, "triple_flipped": 0}
    out: List[Dict[str, Any]] = []
    seen = set()
    for t in triples:
        n = dict(t)
        # 연도 분리가 가장 먼저 (값 규칙·병합 대상 이름에 연도가 섞이지 않게 — 설계 D4 §5)
        if apply_year_split(n):
            counts["year"] += 1
        orig_names = {"subject": n.get("subject"), "object": n.get("object")}
        for side in ("subject", "object"):
            tgt = _resolve(n.get(side)) if compact(n.get(side)) in entity_map else None
            if tgt and n.get(side) != tgt:
                n[side] = tgt
                counts["entity"] += 1
        tgt = key_map.get(compact(n.get("predicate")))
        if tgt and n.get("predicate") != tgt:
            n["predicate"] = tgt
            counts["key"] += 1
        cv = compact(n.get("object"))
        for r in value_rules:
            scope = r.get("scope_paths") or ["*"]
            if cv and cv == compact(r["source_value"]) and ("*" in scope or n.get("predicate") in scope):
                n["object"] = r["target_value"]
                counts["value"] += 1
                break
        if triple_map:
            tk = (compact(n.get("subject")), compact(n.get("predicate")), compact(n.get("object")))
            if tk not in triple_map and n.get("object_raw"):
                # 연도 분리 전 표기로 만든 트리플 규칙 ('… | 수상함 | 노벨 물리학상 (1933년)') 도 계속 맞춘다
                tk = (tk[0], tk[1], compact(_resolve(n["object_raw"])))
            if tk in triple_map:
                tgt = triple_map[tk]
                if tgt is None:
                    counts["triple_deleted"] += 1
                    continue
                if tgt == "@flip":
                    # 방향 뒤집기 (관계는 그대로, 주어·목적어 교환) — 방향 검증(D1)에서 사람이 승인한 것
                    n["subject"], n["object"] = n.get("object"), n.get("subject")
                    n["subject_type"], n["object_type"] = n.get("object_type"), n.get("subject_type")
                    n["edited"] = "flipped"
                    counts["triple_flipped"] += 1
                else:
                    n["predicate"] = tgt
                    n["edited"] = "moved"
                    counts["triple_moved"] += 1
        for side, tkey in (("subject", "subject_type"), ("object", "object_type")):
            # 병합으로 이름이 바뀌면 새 이름에 클래스 규칙이 없을 수 있다 → 원래 이름의 클래스를 이어받는다
            # ('조머펠트'(Person) → '아르놀드 조머펠트' 병합 뒤 Person 에서 빠지던 문제, 2026-11-16 D2).
            # 뒤집기면 주어·목적어가 바뀌었으니 원래 이름도 맞바꿔 본다.
            src = orig_names["object" if side == "subject" else "subject"] if n.get("edited") == "flipped" else orig_names[side]
            cls = class_map.get(compact(n.get(side))) or class_map.get(compact(src))
            if cls:
                n[tkey] = cls
                counts["class"] += 1
        if compact(n.get("subject")) and compact(n.get("subject")) == compact(n.get("object")):
            continue  # 병합으로 생긴 자기 루프 제거
        key = (n.get("subject"), n.get("predicate"), n.get("object"), n.get("source_node_id"), n.get("year"))
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out, {"counts": counts, "input": len(triples), "output": len(out)}
