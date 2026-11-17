"""저장된 답변 다시 채점 (LLM·검색 호출 없음) — physics_eval.py 와 같은 규칙.

사용: python3 regrade.py <결과.json> [...]
  결과 파일은 [{"id": "Q01", "answer": "..."}, ...] 형식 (파이프라인 eval_*.json, 에이전트 답변 모두).
  채점 규칙을 바꾼 뒤 이전 결과와 같은 기준으로 비교할 때 쓴다.
  11/17 이전 파이프라인 결과는 답변을 300자만 저장했다 → 저장된 answer_hit 이 참이면 그대로 정답으로 본다
  (새 규칙은 기존 규칙보다 넓기만 하므로 '기존 정답 ∪ 새 규칙 정답' 이 새 기준 점수의 하한이다).
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__)) + "/"
spec = importlib.util.spec_from_file_location("physics_eval", HERE + "physics_eval.py")
pe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pe)

qs = {q["id"]: q for q in json.load(open(pe.D + "questions.json", encoding="utf-8"))}


def score(path):
    rows = json.load(open(path, encoding="utf-8"))
    ans = {r["id"]: r.get("answer", "") for r in rows}
    prev = {r["id"]: bool(r.get("answer_hit")) for r in rows}
    ok, by_type, wrong = 0, {}, []
    for qid, q in qs.items():
        a = ans.get(qid, "")
        hit = prev.get(qid, False) or (bool(pe.NEG_PAT.search(a)) if q["type"] == "negative"
                                        else all(pe.item_hit(x, a) for x in q["answer"]))
        ok += hit
        b = by_type.setdefault(q["type"], [0, 0])
        b[0] += hit
        b[1] += 1
        if not hit:
            wrong.append(qid)
    return ok, by_type, wrong


if __name__ == "__main__":
    for p in sys.argv[1:]:
        ok, by_type, wrong = score(p)
        print(f"{os.path.basename(p)}: {ok}/{len(qs)} | " + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in by_type.items())
              + f" | 오답 {' '.join(wrong)}")
