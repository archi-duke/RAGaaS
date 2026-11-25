"""추출·검색 품질 회귀 측정 (2026-11-25, 추출 품질 후속 A).

두 세트를 운영 구성(config=live)으로 돌리고 점수·틀린 문항을 저장한다. 다음 단계(B LLM 근거 검증,
C 답변 근거 검사)를 넣을 때마다 다시 돌려 이전 결과와 비교한다.

  - physics   : 물리학사 39문항 (test-ontology3) — physics-history/results/physics_eval.py 를 그대로 쓴다
  - arch      : 아키텍처 스타일 14문항 (test-ontology2) — architecture.json. forbid(원문에 없는 사실)를 함께 본다

사용:
  python3 docs/datasets/regression/run.py LABEL [--only arch|physics] [--compare 이전LABEL]
결과: docs/datasets/regression/results/LABEL.json (+ physics 는 physics-history/results/eval_LABEL.json)
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)) + "/"
OUT = HERE + "results/"
BASE = os.getenv("RAGAAS_BASE", "http://localhost:44300/ragaas/api/v2/knowledge-bases/")
NEG_PAT = re.compile(r"(없습니다|없다|포함되어 있지 않|찾을 수 없|찾지 못|언급되어 있지 않|언급이 없|알 수 없|정보가 없|나와 있지 않)")


def norm(s):
    return re.sub(r"[\s\-_·.,()\[\]'\"*]", "", str(s)).lower()


def get(url):
    return json.load(urllib.request.urlopen(url, timeout=120))


def kb_id(name):
    for k in get(BASE):
        if k["name"] == name:
            return k["id"]
    raise SystemExit(f"KB 없음: {name}")


def any_in(alts, ans):
    """별칭 중 하나라도 답변에 있는가. 숫자가 든 표기('+3점', '-3점')는 부호를 살려 공백만 빼고 비교한다."""
    na, raw = norm(ans), re.sub(r"\s", "", ans)
    return any((re.sub(r"\s", "", a) in raw) if re.search(r"\d", a) else (norm(a) in na) for a in alts)


def run_arch():
    suite = json.load(open(HERE + "architecture.json", encoding="utf-8"))
    kid = kb_id(suite["kb_name"])
    rows = []
    for q in suite["questions"]:
        t = time.time()
        req = urllib.request.Request(BASE + kid + "/chat", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"query": q["question"], "config": "live"}).encode())
        try:
            d = json.load(urllib.request.urlopen(req, timeout=900))
        except Exception as e:
            rows.append({"id": q["id"], "type": q["type"], "ok": False, "error": str(e)[:200], "q": q["question"]})
            print(f"{q['id']} 오류 {e}", flush=True)
            continue
        ans = d.get("answer", "")
        if q["type"] == "negative":
            hits, missing = [], []
            ok = bool(NEG_PAT.search(ans))
        else:
            hits = [a[0] for a in q.get("expect", []) if any_in(a, ans)]
            missing = [a[0] for a in q.get("expect", []) if not any_in(a, ans)]
            ok = not missing
        forbidden = [f[0] for f in q.get("forbid", []) if any_in(f, ans)]
        ok = ok and not forbidden
        g = ((d.get("chunks") or [{}])[0].get("graph_metadata") or {}) if d.get("chunks") else {}
        rows.append({"id": q["id"], "type": q["type"], "ok": ok, "missing": missing, "forbidden": forbidden,
                     "mode": ((g.get("reasoning") or {}).get("targeting") or {}).get("mode"),
                     "has_error": d.get("has_error"), "stage_failures": d.get("stage_failures"),
                     "sec": round(time.time() - t, 1), "q": q["question"], "answer": ans})
        r = rows[-1]
        print(f"{r['id']} {'O' if ok else 'X'} mode={r['mode']} {r['sec']}s | {q['question'][:40]}"
              + (f" | 빠짐 {missing}" if missing else "") + (f" | 금지 {forbidden}" if forbidden else ""), flush=True)
    return rows


def run_physics(label):
    sys.path.insert(0, os.path.join(HERE, "..", "physics-history", "results"))
    import physics_eval
    physics_eval.main(kb_id("test-ontology3"), label)
    rows = json.load(open(os.path.join(HERE, "..", "physics-history", "results", f"eval_{label}.json")))
    return [{"id": r["id"], "type": r["type"], "ok": bool(r.get("answer_hit")), "partial": r.get("partial"),
             "evidence_hit": r.get("evidence_hit"), "mode": r.get("mode"), "q": r.get("q"),
             "error": r.get("error")} for r in rows]


def summary(res):
    return {k: f"{sum(r['ok'] for r in v)}/{len(v)}" for k, v in res.items()}


def compare(cur, prev):
    """이전 결과 대비: 새로 틀린 문항 / 새로 맞힌 문항."""
    out = {}
    for k in cur:
        if k not in prev:
            continue
        p = {r["id"]: r["ok"] for r in prev[k]}
        out[k] = {"새로 틀림": [r["id"] for r in cur[k] if p.get(r["id"]) and not r["ok"]],
                  "새로 맞힘": [r["id"] for r in cur[k] if p.get(r["id"]) is False and r["ok"]]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--only", choices=["arch", "physics"])
    ap.add_argument("--compare")
    a = ap.parse_args()
    res = {}
    if a.only in (None, "arch"):
        print("== arch (test-ontology2)")
        res["arch"] = run_arch()
    if a.only in (None, "physics"):
        print("== physics (test-ontology3)")
        res["physics"] = run_physics(f"reg_{a.label}")
    os.makedirs(OUT, exist_ok=True)
    doc = {"label": a.label, "at": time.strftime("%Y-%m-%d %H:%M"), "summary": summary(res), "results": res}
    if a.compare:
        prev = json.load(open(OUT + f"{a.compare}.json"))["results"]
        doc["compare"] = {"with": a.compare, **compare(res, prev)}
    json.dump(doc, open(OUT + f"{a.label}.json", "w"), ensure_ascii=False, indent=1)
    print("\n요약:", doc["summary"])
    if a.compare:
        print("비교:", json.dumps(doc["compare"], ensure_ascii=False))
    print("저장:", OUT + f"{a.label}.json")


if __name__ == "__main__":
    main()
