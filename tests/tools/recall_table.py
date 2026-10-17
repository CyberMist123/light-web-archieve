"""召回表评测（1017 阶段 1）：对一题或一份题集，走生产那条选材路把候选摆成表，并记录金标在哪一层、模型怎么判。只读收藏库。

    python tests/tools/recall_table.py --vault <收藏库> --out <目录> --question "晚上吃什么"
    python tests/tools/recall_table.py --vault <收藏库> --out <目录> --cases <题集.json> [--only T11,T19] [--no-judge] [--model <下拉名>]

题集：顶层数组，或 {cases: [...]}；每题 {id, question, history?, expected?: [金标 id…], must_not_titles?: […]}
（和 tests/tools/ask_answer_eval.py 同一份题集格式；expected 带不带 xhs- 前缀都认）。

写保护和 ask_answer_eval 一样：答案缓存 / 轮次登记 / 扩词缓存全在内存或临时目录，往收藏库的原子写一律拒绝。
每题落一份 <id>.md（召回表）+ 汇总 summary.json / summary.md：
  金标在首屏窗口里排第几（没进=漏召回）· 生产会不会把它送读（primary）· 模型判它什么 · 送读里无关篇占比（按模型判 reject 算）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ask_answer_eval as aae  # noqa: E402  写保护 / 用量计数复用


def _norm_id(i: str) -> str:
    i = str(i or "")
    return i if i.startswith("xhs-") or not re.fullmatch(r"[0-9a-f]{24}", i) else f"xhs-{i}"


def _load_cases(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases", data) if isinstance(data, dict) else data
    return [c for c in cases if isinstance(c, dict) and c.get("question")]


def _history(case):
    out = []
    for prev in case.get("history") or []:
        out.append({"role": "user", "content": prev})
        out.append({"role": "assistant", "content": "（上一答略）"})
    return out


def run_case(case, settings, items, *, judge=True):
    from link_brain import recall_table
    start = time.perf_counter()
    result = recall_table.gather(case["question"], items, settings, _history(case))
    if judge:
        recall_table.judge(result, settings)
    result["seconds"] = round(time.perf_counter() - start, 1)
    rows = result["rows"]
    by_id = {r["id"]: r for r in rows}
    gold = [_norm_id(i) for i in case.get("expected") or []]
    gold_rows = []
    for g in gold:
        r = by_id.get(g)
        gold_rows.append({"id": g, "in_window": r is not None, "rank": r["rank"] if r else None,
                          "production": r["production"] if r else None, "verdict": (r.get("verdict") if r else None),
                          "title": r["title"] if r else ""})
    primary = [r for r in rows if r["production"] == "primary"]
    deep = [r for r in rows if r.get("verdict") == "deep_read"]
    bad_titles = [r["title"] for r in primary if any(re.search(rx, r["title"]) for rx in case.get("must_not_titles") or [])]
    result["eval"] = {
        "gold": gold_rows,
        "gold_in_window": sum(1 for g in gold_rows if g["in_window"]), "gold_total": len(gold),
        "gold_primary": sum(1 for g in gold_rows if g["production"] == "primary"),
        "gold_deep_read": sum(1 for g in gold_rows if g["verdict"] == "deep_read"),
        "primary_n": len(primary), "primary_reject": sum(1 for r in primary if r.get("verdict") == "reject"),
        "deep_read_n": len(deep), "deep_read_gold": sum(1 for r in deep if r["id"] in set(gold)),
        "bad_titles_in_primary": bad_titles,
    }
    return result


def _row_of(case_id, result):
    e = result["eval"]
    p = result["production"]
    return {"id": case_id, "task": result.get("task"), "question": result["question"], "seconds": result.get("seconds"),
            "mode": p.get("mode"), "primary_n": p.get("primary_n"), "select_reason": p.get("select_reason"),
            "window": result["window"], "judge": (result.get("judge") or {}).get("status"),
            "judge_model": (result.get("judge") or {}).get("model"), **e}


def summarize(out: Path, rows, usage=None, blocked=()):
    """按 rows 写 summary.json / summary.md。`--summarize-only` 时 rows 从目录里现有的 <id>.json 重建（补跑过的题以最新文件为准）。"""
    scored = [r for r in rows if "error" not in r and r.get("gold_total")]
    ok_rows = [r for r in rows if "error" not in r]
    judged = [r for r in ok_rows if r.get("judge") == "ok"]
    summary = {
        "cases": len(rows), "errors": sum(1 for r in rows if "error" in r), "scored_with_gold": len(scored),
        "judge_ok": len(judged), "judge_failed": len(ok_rows) - len(judged),
        "gold_in_window_rate": round(sum(r["gold_in_window"] for r in scored) / max(1, sum(r["gold_total"] for r in scored)), 3),
        "gold_primary_rate": round(sum(r["gold_primary"] for r in scored) / max(1, sum(r["gold_total"] for r in scored)), 3),
        "gold_deep_read_rate": round(sum(r["gold_deep_read"] for r in scored if r.get("judge") == "ok")
                                     / max(1, sum(r["gold_total"] for r in scored if r.get("judge") == "ok")), 3),
        "primary_reject_rate": round(sum(r["primary_reject"] for r in judged) / max(1, sum(r["primary_n"] for r in judged)), 3),
        "toc_cases": sum(1 for r in rows if r.get("mode") == "toc"),
        "tokens": ({"prompt": usage["prompt"], "completion": usage["completion"], "calls": usage["calls"]} if usage else None),
        "blocked_writes": list(blocked),
    }
    (out / "summary.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 召回表汇总", "", f"- 题数 {summary['cases']}（有金标 {summary['scored_with_gold']}，崩 {summary['errors']}；模型判定成功 {summary['judge_ok']} / 失败 {summary['judge_failed']}）",
          f"- 金标进首屏窗口 {summary['gold_in_window_rate']:.0%} · 金标被生产送读 {summary['gold_primary_rate']:.0%} · 金标被模型判深读 {summary['gold_deep_read_rate']:.0%}（只算判定成功的题）",
          f"- 生产送读里被模型判无关的占 {summary['primary_reject_rate']:.0%} · 出目录的题 {summary['toc_cases']}"]
    if summary["tokens"]:
        md.append(f"- 本次调模型 {summary['tokens']['calls']} 次，token {summary['tokens']['prompt']}+{summary['tokens']['completion']}；拒绝的写库 {len(summary['blocked_writes'])} 次")
    md += ["", "| 题 | 档位 | 送读 | 金标名次（漏=没进窗口） | 金标送读 | 模型深读（金） | 送读无关 | 判定 | 问题 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            md.append(f"| {r['id']} | 崩 | | | | | | | {r['question'][:40]} |")
            continue
        gold_txt = "、".join(("漏" if not g["in_window"] else str(g["rank"])) for g in r["gold"]) or "-"
        jd = (r.get("judge_model") or "") if r.get("judge") == "ok" else f"失败"
        md.append(f"| {r['id']} | {r['mode']} | {r['primary_n']} | {gold_txt} | {r['gold_primary']}/{r['gold_total']} | "
                  f"{r['deep_read_n']}（{r['deep_read_gold']}） | {r['primary_reject']} | {jd} | {r['question'][:40]} |")
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--question")
    ap.add_argument("--cases")
    ap.add_argument("--only")
    ap.add_argument("--model", default="")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--summarize-only", action="store_true", help="不跑题，按 out 目录里现有的 <id>.json 重算汇总（补跑后合并用）")
    ap.add_argument("--code")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.summarize_only:
        rows = []
        order = [c.get("id") for c in _load_cases(args.cases)] if args.cases else None
        files = {p.stem: p for p in out.glob("*.json") if p.name != "summary.json"}
        for cid in (order or sorted(files)):
            if cid in files:
                rows.append(_row_of(cid, json.loads(files[cid].read_text(encoding="utf-8"))))
        print(json.dumps(summarize(out, rows), ensure_ascii=False, indent=1))
        return 0
    if not args.question and not args.cases:
        ap.error("要 --question 或 --cases")
    link_brain, blocked, _ = aae._setup(args)
    usage = aae._usage_counter()
    from link_brain import ai_config, ask, recall_table
    settings = ai_config.with_model(ai_config.load(), args.model)
    judge_model = str((settings.get("textAI") or {}).get("model") or (settings.get("textAI") or {}).get("command") or "")[:60]
    items = ask.load_items()
    out.mkdir(parents=True, exist_ok=True)
    cases = [{"id": "Q", "question": args.question}] if args.question else _load_cases(args.cases)
    if args.only:
        want = set(args.only.split(","))
        cases = [c for c in cases if c.get("id") in want]
    rows = []
    for case in cases:
        try:
            result = run_case(case, settings, items, judge=not args.no_judge)
        except Exception as exc:  # noqa: BLE001 - 一题崩了照样跑完
            rows.append({"id": case.get("id"), "question": case["question"], "error": f"{type(exc).__name__}: {exc}"})
            print(f"{case.get('id'):>5} 崩 {type(exc).__name__}: {exc}", flush=True)
            continue
        result["task"] = case.get("task")
        if result.get("judge"):
            result["judge"]["model"] = judge_model
        (out / f"{case.get('id')}.md").write_text(recall_table.markdown(result), encoding="utf-8")
        (out / f"{case.get('id')}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        e, p = result["eval"], result["production"]
        rows.append(_row_of(case.get("id"), result))
        gold_txt = "/".join(f"{g['rank'] or '漏'}" for g in e["gold"]) or "-"
        print(f"{case.get('id'):>5} {p.get('mode'):<6} 送读{p.get('primary_n'):>2} 金标名次 {gold_txt:<12} 深读{e['deep_read_n']:>2}(金{e['deep_read_gold']}) "
              f"送读无关{e['primary_reject']} 判定{(result.get('judge') or {}).get('status')} {result['seconds']:>5}s {case['question'][:28]}", flush=True)
    print(json.dumps(summarize(out, rows, usage, blocked), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
