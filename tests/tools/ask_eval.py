"""问收藏检索评测：只读、只检索，不调生成模型。

走生产同一条路：ask.query_terms → retrieval.semantic_hits → ask.qa_matches（含追问处理）。
每题打印：应命中的篇在最终候选里排第几、词法 / 语义各自排第几、前 k 条里命中几篇、会不会进「挑选材料」那步。

用法（题目和笔记 ID 是私人收藏，不进仓库，路径用参数或环境变量传）：

    python tests/tools/ask_eval.py --cases <题目.json> [--vault <收藏库>] [--qvec-cache <向量缓存.json>] [--out <结果.json>]

  --cases       或环境变量 LWA_ASK_EVAL_CASES
  --vault       或环境变量 LINK_BRAIN_VAULT（不传就按程序平时的规则找收藏库）
  --qvec-cache  查询向量缓存：同一句只调一次 embedding 接口，改前改后复跑不再花钱；不传 = 每次都现查
  --lexical     不用语义层（不调 embedding），只看词法

题目格式：[{"question": "...", "history": ["上一问", ...], "expected": ["item id", ...], "note": "..."}]
  history = 同一会话里这一问之前她问过的话（按顺序），用来复现追问场景。
  recall@k = 前 k 条里命中的应命中篇数 / min(k, 应命中篇数)。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _install_qvec_cache(path: Path, counter: list[int]) -> None:
    """semantic.query_vector 包一层文件缓存（只缓存成功的向量）；counter[0] 记真调了几次接口。"""
    import numpy as np
    from link_brain import semantic
    cache = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    original = semantic.query_vector

    def cached(question):
        key = (question or "").strip()
        if key in cache:
            return np.asarray(cache[key], dtype=np.float32)
        counter[0] += 1
        vec = original(question)
        if vec is not None:
            cache[key] = [float(x) for x in vec]
            path.write_text(json.dumps(cache), encoding="utf-8")
        return vec

    semantic.query_vector = cached


def _positions(ids, expected):
    return [i for i, x in enumerate(ids, 1) if x in expected]


def evaluate(cases, items=None, k=8, use_semantic=True):
    """逐题跑检索，返回 {summary, results}。items 不传就读当前收藏库的 catalog-data.json。"""
    from link_brain import ask, retrieval
    items = ask.load_items() if items is None else items
    titles = {it.get("id"): it.get("title") or "" for it in items}
    rows = []
    for case in cases:
        question = case["question"]
        expected = list(dict.fromkeys(case.get("expected") or []))
        history = []
        for prev in case.get("history") or []:
            history += [{"role": "user", "content": prev}, {"role": "assistant", "content": "（略）"}]
        terms = ask.query_terms(question)
        sem = retrieval.semantic_hits(question) if use_semantic else None
        matches, mode, _ = ask.qa_matches(question, items, terms, sem, history)
        final = [it["id"] for it in matches]
        lexical = [it["id"] for _, it in retrieval.rank(items, terms)]
        semantic = [i for i, _ in sorted((sem or {}).items(), key=lambda kv: -kv[1]["score"])]
        want = set(expected)
        got = len(set(final[:k]) & want)
        rows.append({
            "question": question, "history": case.get("history") or [], "note": case.get("note", ""),
            "mode": mode, "terms": terms, "expected": expected,
            f"recall_at_{k}": round(got / min(k, len(want)), 3) if want else None,
            "final_rank": _positions(final, want), "lexical_rank": _positions(lexical, want),
            "semantic_rank": _positions(semantic, want) if sem is not None else None,
            "selection_step": ask.selection_wanted(question, matches, k),
            "in_selection_pool": len(set(final[:40]) & want),
            "top": [{"id": i, "title": titles.get(i, "")[:40], "expected": i in want} for i in final[:k]],
        })
    scored = [r[f"recall_at_{k}"] for r in rows if r[f"recall_at_{k}"] is not None]
    summary = {f"recall_at_{k}": round(statistics.mean(scored), 3) if scored else None,
               "questions": len(rows), "semantic_active": any(r["semantic_rank"] is not None for r in rows)}
    return {"summary": summary, "results": rows}


def _print(report, k):
    for r in report["results"]:
        hist = f"（接在 {' → '.join(r['history'])} 之后）" if r["history"] else ""
        print(f"\n■ {r['question']}{hist}  [{r['mode']}]  recall@{k}={r[f'recall_at_{k}']}")
        print(f"  应命中 {len(r['expected'])} 篇 · 最终排名 {r['final_rank'][:10]} · 词法 {r['lexical_rank'][:10]}"
              f" · 语义 {r['semantic_rank'][:10] if r['semantic_rank'] is not None else '未启用'}"
              f" · 挑选材料 {'会' if r['selection_step'] else '不'}（前 40 条里有 {r['in_selection_pool']} 篇）")
        for i, row in enumerate(r["top"], 1):
            print(f"   {i}. {'✓' if row['expected'] else ' '} {row['title']}")
    print("\n" + json.dumps(report["summary"], ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=os.environ.get("LWA_ASK_EVAL_CASES"))
    parser.add_argument("--vault")
    parser.add_argument("--qvec-cache")
    parser.add_argument("--out")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--lexical", action="store_true")
    args = parser.parse_args(argv)
    if not args.cases:
        parser.error("要 --cases 或环境变量 LWA_ASK_EVAL_CASES")
    if args.vault:
        os.environ["LINK_BRAIN_VAULT"] = args.vault
    calls = [0]
    if args.qvec_cache and not args.lexical:
        _install_qvec_cache(Path(args.qvec_cache), calls)
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    report = evaluate(cases, k=args.k, use_semantic=not args.lexical)
    report["summary"]["embedding_calls"] = calls[0] if args.qvec_cache else "未记录（没给 --qvec-cache）"
    _print(report, args.k)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
