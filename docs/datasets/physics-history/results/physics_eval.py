"""물리학사 질문 세트 평가 — /chat 호출 결과를 정답지와 대조.

지표 (질문별):
  answer_hit   : 답변 텍스트에 정답 항목이 모두(또는 일부) 포함되는가 (별칭 정규화 포함 문자열 일치)
  evidence_hit : 근거 청크의 문서가 정답 사실(fact_ids)이 들어 있는 문서와 겹치는가
  mode         : 그래프 경로 (A/B/P/C/overview/none)
  negative     : 없는 사실 질문은 "없음/모름" 계열 응답이면 정답
사전지식 판별: answer_hit=True 인데 evidence_hit=False 면 '기억으로 맞힘' 의심.
"""
import json
import os
import re
import sys
import time
import urllib.request

BASE = os.getenv("RAGAAS_BASE", "http://localhost:44300/ragaas/api/v2/knowledge-bases/")
D = "/private/tmp/claude-501/-Users-dukekimm-Works-RAGaaS/503152e9-a23b-429e-ac1f-71a13cb65ae9/scratchpad/physics/"
NEG_PAT = re.compile(r"(없습니다|없다|포함되어 있지 않|찾을 수 없|언급되어 있지 않|알 수 없|정보가 없|couldn't find|not)", re.I)


def norm(s):
    return re.sub(r"[\s\-_·.,()\[\]'\"]", "", str(s)).lower()


def strip_note(a):
    """정답 항목의 괄호 주석 제거: '플랑크 복사 법칙(확인)' → '플랑크 복사 법칙'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(a))


def get(url):
    return json.load(urllib.request.urlopen(url, timeout=120))


def _trace(rs):
    """추론 과정 요약 (링킹·라우팅·홉) — 실패 원인 분석용."""
    tg = rs.get("targeting") or {}
    return {"linking": [{k: l.get(k) for k in ("entity", "uri", "equivalents") if l.get(k)}
                        for l in rs.get("linking") or []],
            "reason": tg.get("reason"), "paths": tg.get("selected_paths"),
            "warnings": tg.get("warnings"), "adjustments": tg.get("adjustments"),
            "n_triples": len(rs.get("triples") or [])}


def main(kb_id, label, only=None):
    facts = {f["id"]: f for f in json.load(open(D + "facts.json"))["facts"]}
    qs = json.load(open(D + "questions.json"))
    docs = get(BASE + kb_id + "/documents")
    docs = docs if isinstance(docs, list) else docs.get("documents", [])
    id_by_name = {d["filename"]: d["id"] for d in docs}
    rows = []
    for q in qs:
        if only and q["id"] not in only:
            continue
        t = time.time()
        req = urllib.request.Request(BASE + kb_id + "/chat", data=json.dumps({"query": q["question"]}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=900))
        except Exception as e:
            rows.append({"id": q["id"], "type": q["type"], "error": str(e)[:200]})
            continue
        ans = d.get("answer", "")
        chunks = d.get("chunks") or []
        g = (chunks[0].get("graph_metadata") or {}) if chunks else {}
        mode = ((g.get("reasoning") or {}).get("targeting") or {}).get("mode")
        if q["type"] == "negative":
            answer_hit = bool(NEG_PAT.search(ans))
            partial = answer_hit
        else:
            hits = [a for a in q["answer"] if norm(strip_note(a)) and norm(strip_note(a)) in norm(ans)]
            answer_hit = len(hits) == len(q["answer"])
            partial = len(hits) > 0
        want_docs = {id_by_name.get(n) for fid in q.get("fact_ids", []) for n in facts.get(fid, {}).get("docs", [])}
        want_docs.discard(None)
        got_docs = {(c.get("metadata") or {}).get("doc_id") for c in chunks if c.get("chunk_id") != "GRAPH_METADATA_ONLY"}
        evidence_hit = bool(want_docs & got_docs) if want_docs else None
        rows.append({"id": q["id"], "type": q["type"], "hops": q.get("hops"), "mode": mode,
                     "answer_hit": answer_hit, "partial": partial, "evidence_hit": evidence_hit,
                     "sec": round(time.time() - t, 1), "q": q["question"], "expected": q["answer"],
                     "answer": ans[:300], "trace": _trace(g.get("reasoning") or {})})
        r = rows[-1]
        print(f"{r['id']:4} {r['type']:10} mode={str(r['mode']):9} ans={'O' if r['answer_hit'] else ('△' if r['partial'] else 'X')} "
              f"evid={'O' if r['evidence_hit'] else ('-' if r['evidence_hit'] is None else 'X')} {r['sec']}s | {q['question'][:50]}",
              flush=True)
    out = D + f"eval_{label}.json"
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=1)
    by = {}
    for r in rows:
        if "error" in r:
            continue
        b = by.setdefault(r["type"], {"n": 0, "ans": 0, "partial": 0, "evid": 0, "mem": 0})
        b["n"] += 1
        b["ans"] += r["answer_hit"]
        b["partial"] += r["partial"]
        b["evid"] += bool(r["evidence_hit"])
        b["mem"] += bool(r["answer_hit"] and r["evidence_hit"] is False)
    print("\n유형별: 정답 / 부분 / 근거 적중 / 기억 의심")
    tot = {"n": 0, "ans": 0, "partial": 0, "evid": 0, "mem": 0}
    for k, b in by.items():
        print(f"  {k:10} {b['ans']}/{b['n']}  부분 {b['partial']}  근거 {b['evid']}  기억의심 {b['mem']}")
        for x in tot:
            tot[x] += b[x]
    print(f"  {'합계':10} {tot['ans']}/{tot['n']}  부분 {tot['partial']}  근거 {tot['evid']}  기억의심 {tot['mem']}")
    print("저장:", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3].split(",") if len(sys.argv) > 3 else None)
