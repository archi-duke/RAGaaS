"""용어 사전 평가 (docs/design/agent/design-kb-lexicon.md §6).

사용: python backend/scripts/eval_lexicon.py [--base http://localhost:44300/ragaas/api/v2] [--kb test-ontology2]
에이전트가 실제로 받는 결과(/agent/values + /agent/entities)로 잰다.
"""
import argparse
import json
import os
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "docs", "datasets", "lexicon-eval.json")


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:44300/ragaas/api/v2")
    ap.add_argument("--kb", default=None)
    ap.add_argument("--data", default=DATA, help="평가 세트 (기본 lexicon-eval.json, 홀드아웃은 lexicon-eval-holdout.json)")
    ap.add_argument("--min-score", type=float, default=80.0, help="이 점수 이상만 '일치' 로 셈 (번역 대체 단계 80 포함)")
    a = ap.parse_args()
    data = json.load(open(a.data))
    by_kb = defaultdict(list)
    for it in data["items"]:
        if not a.kb or it["kb"] == a.kb:
            by_kb[it["kb"]].append(it)
    stats = defaultdict(lambda: [0, 0])     # type → [ok, n]
    fp_total = 0
    for kb, items in by_kb.items():
        kb_id = data["kbs"][kb]
        terms = [it["term"] for it in items]
        base = f"{a.base}/knowledge-bases/{kb_id}/agent"
        # API 는 한 번에 20개까지 — 나눠 보낸다
        vals = {"matches": {}, "narrower": {}, "elapsed_ms": 0}
        ents = {"entities": {}, "elapsed_ms": 0}
        for i in range(0, len(terms), 20):
            part = terms[i:i + 20]
            en = {it["term"]: it["term_en"] for it in items if it.get("term_en") and it["term"] in part}
            v = post(f"{base}/values", {"terms": part, "limit": 20, "terms_en": en})
            e = post(f"{base}/entities", {"names": part, "limit": 10, "names_en": en})
            vals["matches"].update(v["matches"]); vals["narrower"].update(v.get("narrower", {}))
            vals["elapsed_ms"] = max(vals["elapsed_ms"], v["elapsed_ms"]); vals["lexicon_entries"] = v.get("lexicon_entries")
            ents["entities"].update(e["entities"]); ents["elapsed_ms"] = max(ents["elapsed_ms"], e["elapsed_ms"])
        print(f"\n== {kb} (사전 항목 {vals.get('lexicon_entries')}) values {vals['elapsed_ms']}ms entities {ents['elapsed_ms']}ms")
        for it in items:
            t = it["term"]
            hits = {m["value"] for m in vals["matches"].get(t, []) if m.get("score", 0) >= a.min_score}
            hits |= {e["label"] for e in ents["entities"].get(t, []) if e.get("score", 0) >= a.min_score}
            nar = {n["value"] for n in vals.get("narrower", {}).get(t, [])}
            exp, exp_n = set(it["expect"]), set(it.get("narrower", []))
            if it["type"] == "negative":
                ok = not hits
                fp = len(hits)
            elif exp_n:
                ok = bool(nar & exp_n)
                fp = 0
            else:
                ok = bool(hits & exp)
                fp = len(hits - exp)
            fp_total += fp
            stats[it["type"]][0] += ok
            stats[it["type"]][1] += 1
            mark = "✔" if ok else "✘"
            extra = f" 오일치 {sorted(hits - exp)[:3]}" if fp and it["type"] != "negative" else ""
            shown = sorted(nar)[:5] if exp_n else sorted(hits)[:4]
            print(f"  {mark} [{it['type']:8s}] {t:28s} → {shown}{extra}")
    ok = sum(v[0] for v in stats.values())
    n = sum(v[1] for v in stats.values())
    print("\n유형별:", ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(stats.items())))
    print(f"전체 {ok}/{n} ({ok / max(n, 1):.0%}) | 오일치 {fp_total}건")
    return 0 if ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
