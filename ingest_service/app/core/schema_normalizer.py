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
# 트리플 리플레이 (텍스트/LLM 추출 그래프의 ABox 재구성 — docs/design-graph-promotion.md §3(c))
# ---------------------------------------------------------------------------

def apply_rules_to_triples(
    triples: List[Dict[str, Any]], rules: Optional[List[Dict[str, Any]]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """평면 트리플(LLM 추출)에 KB 규칙을 결정적으로 적용한 새 목록과 보고서.

    적용 순서: entity(엔티티 병합, 주어·목적어) → key(predicate, 마지막 세그먼트)
              → value(목적어 전체 일치, scope) → class(엔티티 → 클래스, subject_type/object_type)
    입력은 변경하지 않는다 (raw 사본에서 항상 다시 계산 → 멱등).
    """
    active = [r for r in (rules or []) if r.get("status", "active") == "active"]
    entity_map = {compact(r["source_value"]): r["target_value"] for r in active
                  if r.get("rule_type") == "entity" and r.get("source_value") and r.get("target_value")}
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
        if r.get("rule_type") == "triple" and r.get("pair") and len(r["pair"]) == 3:
            triple_map[tuple(compact(x) for x in r["pair"])] = r.get("target_path") or None

    counts = {"entity": 0, "key": 0, "value": 0, "class": 0, "triple_moved": 0, "triple_deleted": 0, "triple_flipped": 0}
    out: List[Dict[str, Any]] = []
    seen = set()
    for t in triples:
        n = dict(t)
        for side in ("subject", "object"):
            tgt = entity_map.get(compact(n.get(side)))
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
            cls = class_map.get(compact(n.get(side)))
            if cls:
                n[tkey] = cls
                counts["class"] += 1
        if compact(n.get("subject")) and compact(n.get("subject")) == compact(n.get("object")):
            continue  # 병합으로 생긴 자기 루프 제거
        key = (n.get("subject"), n.get("predicate"), n.get("object"), n.get("source_node_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out, {"counts": counts, "input": len(triples), "output": len(out)}
