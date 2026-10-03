"""问收藏检索评测：只读、只检索，不调生成回答的模型。

走生产同一条路：ask.recall（原词 BM25 + 语义 + 扩词表 + 小模型扩词，各路 RRF；含追问处理）→ 候选池前 ask.POOL_MAX 篇 →
按字数预算送进作答模型的前 N 篇（ask.primary_count）。「挑选材料」那一步要调作答模型，评测不跑——第 10 批起它只调顺序、
不再丢候选，所以候选池和页面上能看到的来源不受它影响。

每题打印：应命中的篇在候选池里排第几、词法 / 语义各自排第几、扩出了哪些词、recall@8 / recall@20 / 候选池覆盖率。

用法（题目和笔记 ID 是私人收藏，不进仓库，路径用参数或环境变量传）：

    python tests/tools/ask_eval.py --cases <题目.json> [--vault <收藏库>] [--qvec-cache <向量缓存.json>]
                                   [--expand-cache <扩词缓存.json>] [--no-expand-llm] [--lexical] [--out <结果.json>]

  --cases         或环境变量 LWA_ASK_EVAL_CASES
  --vault         或环境变量 LINK_BRAIN_VAULT（不传就按程序平时的规则找收藏库）
  --qvec-cache    查询向量缓存：同一句只调一次 embedding 接口，改前改后复跑不再花钱；不传 = 每次都现查
  --expand-cache  小模型扩词的缓存文件（不传 = 系统临时目录里的一个文件；评测从不写收藏库里的那份）
  --no-expand-llm 不调小模型扩词（只用扩词表）
  --lexical       不用语义层（不调 embedding），只看词法

题目格式：[{"question": "...", "history": ["上一问", ...], "expected": ["item id", ...], "must_pool": [...], "note": "..."}]
  history = 同一会话里这一问之前她问过的话（按顺序），用来复现追问场景。
  recall@k = 前 k 条里命中的应命中篇数 / min(k, 应命中篇数)；pool = 候选池（页面上「主要依据」+「其他相关」）里命中的比例。
  must_pool = 一定要出现在候选池里的篇（如问国家要带出只写了城市名的篇）。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
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


def _count_model_calls(counter: list) -> None:
    """text_stream.call 包一层：记扩词小模型真调了几次、各花多久（缓存命中不经过这里）。"""
    from link_brain import text_stream
    original = text_stream.call

    def counted(*args, **kwargs):
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            counter.append(round(time.perf_counter() - start, 2))

    text_stream.call = counted


def _positions(ids, expected):
    return [i for i, x in enumerate(ids, 1) if x in expected]


def _recall(ids, want, k):
    return round(len(set(ids[:k]) & want) / min(k, len(want)), 3) if want else None


def evaluate(cases, items=None, k=8, use_semantic=True, expand_llm=True):
    """逐题跑检索，返回 {summary, results}。items 不传就读当前收藏库的 catalog-data.json。"""
    from link_brain import ai_config, ask, retrieval
    items = ask.load_items() if items is None else items
    titles = {it.get("id"): it.get("title") or "" for it in items}
    settings = ai_config.load()
    limits = settings.get("retrieval") or {}
    cap = max(500, int(limits.get("totalCharLimit", 8000)))
    top_k = max(1, int(limits.get("topK", 8)))
    original_sem = retrieval.semantic_hits
    if not use_semantic:
        retrieval.semantic_hits = lambda q: None
    rows = []
    try:
        for case in cases:
            question = case["question"]
            expected = list(dict.fromkeys(case.get("expected") or []))
            history = []
            for prev in case.get("history") or []:
                history += [{"role": "user", "content": prev}, {"role": "assistant", "content": "（略）"}]
            start = time.perf_counter()
            found = ask.recall(question, items, settings, history, allow_expand_call=expand_llm)
            took = round(time.perf_counter() - start, 2)
            pool = [it["id"] for it in found["matches"][:ask.POOL_MAX]]
            n = ask.primary_count(cap, top_k, len(pool))
            lexical = [it["id"] for _, it in retrieval.rank(items, found["terms"])]
            sem = retrieval.semantic_hits(question)  # 同一句有缓存，不再调接口
            semantic = retrieval.sem_order(sem)
            want = set(expected)
            must = list(case.get("must_pool") or [])
            rows.append({
                "question": question, "history": case.get("history") or [], "note": case.get("note", ""), "set": case.get("set", ""),
                "mode": found["mode"], "terms": found["terms"], "expanded": found["expansion"]["terms"],
                "expand_status": found["expansion"].get("status"), "expected": expected, "seconds": took,
                f"recall_at_{k}": _recall(pool, want, k), "recall_at_20": _recall(pool, want, 20),
                "recall_primary": _recall(pool, want, n), "primary": n, "pool_size": len(pool),
                "pool_coverage": round(len(set(pool) & want) / len(want), 3) if want else None,
                "must_pool": f"{len(set(pool) & set(must))}/{len(must)}" if must else "",
                "must_pool_rank": [pool.index(x) + 1 if x in pool else None for x in must],
                "final_rank": _positions(pool, want), "lexical_rank": _positions(lexical, want),
                "semantic_rank": _positions(semantic, want) if sem is not None else None,
                "selection_step": ask.selection_wanted(question, pool, n),
                "top": [{"id": i, "title": titles.get(i, "")[:40], "expected": i in want} for i in pool[:k]],
            })
    finally:
        retrieval.semantic_hits = original_sem

    def mean(key, subset=None):
        vals = [r[key] for r in rows if r[key] is not None and (subset is None or r["set"] == subset)]
        return round(statistics.mean(vals), 3) if vals else None

    summary = {f"recall_at_{k}": mean(f"recall_at_{k}"), "recall_at_20": mean("recall_at_20"),
               "recall_primary": mean("recall_primary"), "pool_coverage": mean("pool_coverage"),
               "questions": len(rows), "semantic_active": any(r["semantic_rank"] is not None for r in rows),
               "seconds_mean": round(statistics.mean(r["seconds"] for r in rows), 2) if rows else None}
    for subset in sorted({r["set"] for r in rows if r["set"]}):
        summary[f"set_{subset}"] = {f"recall_at_{k}": mean(f"recall_at_{k}", subset), "recall_at_20": mean("recall_at_20", subset),
                                    "pool_coverage": mean("pool_coverage", subset)}
    return {"summary": summary, "results": rows}


def _print(report, k):
    for r in report["results"]:
        hist = f"（接在 {' → '.join(r['history'])} 之后）" if r["history"] else ""
        print(f"\n■ {r['question']}{hist}  [{r['mode']}]  recall@{k}={r[f'recall_at_{k}']} · @20={r['recall_at_20']}"
              f" · 池覆盖={r['pool_coverage']} · 池 {r['pool_size']} 篇、送模型 {r['primary']} 篇 · {r['seconds']}s")
        print(f"  应命中 {len(r['expected'])} 篇 · 候选池排名 {r['final_rank'][:12]} · 词法 {r['lexical_rank'][:10]}"
              f" · 语义 {r['semantic_rank'][:10] if r['semantic_rank'] is not None else '未启用'}"
              + (f" · 必须在池里 {r['must_pool']} 排 {r['must_pool_rank']}" if r["must_pool"] else ""))
        print(f"  扩词（{r['expand_status']}）：{'、'.join(r['expanded']) or '无'}")
        for i, row in enumerate(r["top"], 1):
            print(f"   {i}. {'✓' if row['expected'] else ' '} {row['title']}")
    print("\n" + json.dumps(report["summary"], ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=os.environ.get("LWA_ASK_EVAL_CASES"))
    parser.add_argument("--vault")
    parser.add_argument("--qvec-cache")
    parser.add_argument("--expand-cache")
    parser.add_argument("--no-expand-llm", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--lexical", action="store_true")
    args = parser.parse_args(argv)
    if not args.cases:
        parser.error("要 --cases 或环境变量 LWA_ASK_EVAL_CASES")
    if args.vault:
        os.environ["LINK_BRAIN_VAULT"] = args.vault
    # 评测只读收藏库：扩词缓存永远写到库外
    os.environ["LINK_BRAIN_EXPAND_CACHE"] = args.expand_cache or str(Path(tempfile.gettempdir()) / "lwa-ask-eval-expand-cache.json")
    calls = [0]
    if args.qvec_cache and not args.lexical:
        _install_qvec_cache(Path(args.qvec_cache), calls)
    model_calls: list = []
    _count_model_calls(model_calls)
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    report = evaluate(cases, k=args.k, use_semantic=not args.lexical, expand_llm=not args.no_expand_llm)
    report["summary"]["embedding_calls"] = calls[0] if args.qvec_cache else "未记录（没给 --qvec-cache）"
    report["summary"]["expand_model_calls"] = len(model_calls)
    report["summary"]["expand_model_seconds"] = model_calls
    _print(report, args.k)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
