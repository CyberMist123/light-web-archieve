"""问收藏答案级验收（1015 第二批）：跑真入口 ask.answer，按规则给每题判分。会调作答模型（花钱），只读收藏库。

和 tests/tools/ask_eval.py（只测召回、不调作答模型）互补：这里看「她最后看到的那一答」对不对、全不全、有没有塞无关的、档位对不对。
LLM 评审（4 维）不在这里——评审模型不能和作答模型同一家，按 docs/BENCH.md 的口径另跑。

用法（题目里是私人笔记 id，不进仓库，用参数传）：

    python tests/tools/ask_answer_eval.py --cases <answer-cases.json> --vault <收藏库> --out <结果.json>
                                          [--code <另一份 link_brain 的上一级目录>] [--only F01,F02] [--model DeepSeek]

  --code   跑别的版本（例如改前的 main：git archive 出来的目录）；不给 = 本仓库这份
  --model  问答页下拉里的模型名（ai_config.with_model）；不给 = 设置里当前那个

只读保证（真库）：答案缓存 lookup / record、问题登记、轮次登记、扩词缓存全换成内存 / 临时文件；
storage 的原子写一旦指向收藏库就拒绝（记进结果的 blocked_writes），所以跑一轮不会往库里写任何东西。

题目格式：[{id, question, history?: [上一问…], goal, tier: direct|toc|none|any, expected: [主答, …], min_cover?,
           must_have?: [正则…], must_not_ids?: [id 前缀…], must_not_titles?: [正则…], must_not_text?: [正则…], allow_none?}]

规则（docs/BENCH.md「答案级验收」）：
  R1 主答命中   direct 档：引用到的第一个来源 == expected[0]；toc 档：expected[0] 在目录前 3 条
  R2 金标覆盖   引用 / 目录里含 expected 的篇数 ≥ min_cover（默认 1；toc 档默认全部，最多 8）
  R3 不许出现帖 引用 / 目录里没有 must_not_ids（前缀）/ must_not_titles（标题正则）
  R4 不许出现字 回答里没有 must_not_text 正则
  R5 必含要点   must_have 每条正则都中（命中比例记进结果；全中才算过）
  R6 档位       mode 与 tier 一致（改前没有 mode 字段 = direct）；none 档 = 回答说没找到、且不引用 expected 以外的硬凑帖
  R8 出处       direct 档回答里至少一个 [来源N]
  R9–R12 自检   引用对齐 / 无假缺口 / 无模板泄漏 / 说话人（1017 阶段 1，读 result["checks"]）
  R13–R16 v2.1  防御句（允许的那 1 句除外、无「缺口」标题）/ 搬运度 ≤25%（howto ≤45%）/ 无逐篇流水账 / 来源导读覆盖 100% 且定位有效（1018）
题过 pass_core = R1–R8 全过（BENCH 主口径）；pass = R1–R16 全过。tier=any 的题只记录不计分。结果每题标 cached（撞到答案缓存）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

CORE_RULES = ("R1", "R2", "R3", "R4", "R5", "R6", "R8")
ALL_RULES = CORE_RULES + ("R9", "R10", "R11", "R12", "R13", "R14", "R15", "R16")
NONE_RE = re.compile(r"没(?:有)?找到|没有(?:找到|相关|这方面|收藏)|未找到|收藏里没有|库里没有|没搜到|没有.{0,6}(?:相关|提到)")


def _setup(args):
    if args.code:
        sys.path.insert(0, str(Path(args.code).resolve()))
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ["LINK_BRAIN_VAULT"] = str(Path(args.vault).resolve())
    tmp = Path(tempfile.mkdtemp(prefix="lwa-answer-eval-"))
    os.environ["LINK_BRAIN_EXPAND_CACHE"] = str(tmp / "expand-cache.json")
    os.environ["LINK_BRAIN_ASK_TURNS"] = str(tmp / "ask-turns.json")
    import link_brain
    from link_brain import answer_cache, storage
    vault = Path(args.vault).resolve()
    blocked: list[str] = []

    def guard(fn):
        def wrapped(path, *a, **k):
            try:
                Path(path).resolve().relative_to(vault)
            except ValueError:
                return fn(path, *a, **k)
            blocked.append(str(path))
            raise PermissionError(f"评测只读：不写收藏库 {path}")
        return wrapped

    storage.atomic_write_text = guard(storage.atomic_write_text)
    if hasattr(storage, "write_json"):
        storage.write_json = guard(storage.write_json)
    answer_cache.lookup = lambda *a, **k: None
    answer_cache.record = lambda *a, **k: None
    try:
        from link_brain import problems
        problems.report = lambda *a, **k: {"written": False}
    except Exception:  # noqa: BLE001
        pass
    try:
        from link_brain import ask_turns
        mem: dict = {}
        ask_turns.record = lambda tid, entry: mem.__setitem__(tid, entry) or True
        ask_turns.get = lambda tid: mem.get(tid)
    except ImportError:
        pass  # 改前的版本没有轮次登记
    try:
        storage.file_lock = _null_lock
    except Exception:  # noqa: BLE001
        pass
    return link_brain, blocked, Path(link_brain.__file__).parent


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _null_lock(*a, **k):
    return _NullLock()


def _usage_counter():
    from link_brain import text_stream
    box = {"calls": 0, "prompt": 0, "completion": 0, "unknown_calls": 0}
    original = text_stream.call

    def counted(*a, **k):
        res = original(*a, **k)
        box["calls"] += 1
        u = (res or {}).get("usage") or {}
        p, c = int(u.get("prompt_tokens") or u.get("input_tokens") or 0), int(u.get("completion_tokens") or u.get("output_tokens") or 0)
        if not (p or c):
            box["unknown_calls"] += 1
        box["prompt"] += p
        box["completion"] += c
        return res

    text_stream.call = counted
    return box


def cited(result):
    """回答实际引用到的来源 id（按 [来源N] 出现顺序）；目录档 = 目录顺序。"""
    if result.get("mode") == "toc":
        return [e.get("id") for e in result.get("toc") or []]
    by_n = {}
    for s in result.get("sources") or []:
        try:
            by_n[int(s.get("citation"))] = s
        except (TypeError, ValueError):
            continue
    order = []
    for n in re.findall(r"来源\s*(\d+)", result.get("markdown") or ""):
        s = by_n.get(int(n))
        if s and s.get("id") not in order:
            order.append(s.get("id"))
    return order


def titles_of(result, ids):
    by_id = {s.get("id"): s.get("title") or "" for s in (result.get("sources") or []) + (result.get("related") or [])}
    for e in result.get("toc") or []:
        by_id[e.get("id")] = e.get("title") or ""
    return [by_id.get(i, "") for i in ids]


def judge(case, result):
    md = result.get("markdown") or ""
    mode = result.get("mode") or "direct"
    ids = cited(result)
    exp = list(case.get("expected") or [])
    tier = case.get("tier", "direct")
    checks = {}
    none_said = bool(NONE_RE.search(md[:400]))
    if tier == "none":
        checks["R1"] = none_said
        checks["R2"] = True
    else:
        if not exp:
            checks["R1"] = checks["R2"] = True
        elif mode == "toc":
            checks["R1"] = (bool(set(ids[:3]) & set(exp)) if case.get("goal") == "survey" else exp[0] in ids[:3])
        elif case.get("goal") == "survey":
            checks["R1"] = bool(ids) and ids[0] in exp      # 盘点题没有唯一主答：第一条是金标之一即可
        else:
            checks["R1"] = bool(ids) and ids[0] == exp[0]
        if exp:
            need = case.get("min_cover") or (min(len(exp), 8) if tier == "toc" else 1)
            checks["R2"] = len(set(ids) & set(exp)) >= need
        if case.get("allow_none") and none_said and not ids:
            checks["R1"] = checks["R2"] = True
    bad_ids = [i for i in ids if any(str(i).startswith(p) for p in case.get("must_not_ids") or [])]
    bad_titles = [t for t in titles_of(result, ids) if any(re.search(rx, t) for rx in case.get("must_not_titles") or [])]
    checks["R3"] = not bad_ids and not bad_titles
    bad_text = [rx for rx in case.get("must_not_text") or [] if re.search(rx, md)]
    checks["R4"] = not bad_text
    must = case.get("must_have") or []
    have = [bool(re.search(rx, md)) for rx in must]
    checks["R5"] = all(have)
    if tier == "any":
        checks["R6"] = True
    elif tier == "none":
        checks["R6"] = none_said
    else:
        checks["R6"] = mode == tier
    checks["R8"] = mode == "toc" or tier == "none" or bool(re.search(r"来源\s*\d+", md))
    # 1017 阶段 1：回答自检（link_brain/answer_check，生产每答都跑、挂在 result["checks"]）——
    # R9 引用对齐 ≥ 0.7 · R10 没有「说没有但来源 / 其他相关里有」· R11 没漏提示词措辞 · R12 点名的说话人都在来源里
    ac = result.get("checks") or {}
    if mode == "toc" or not ac:
        checks["R9"] = checks["R10"] = checks["R11"] = checks["R12"] = True
    else:
        rate = (ac.get("alignment") or {}).get("rate")
        checks["R9"] = rate is None or rate >= 0.7
        checks["R10"] = not (ac.get("absence") or {}).get("conflicts")
        checks["R11"] = not (ac.get("leak") or {}).get("found")
        checks["R12"] = not (ac.get("speaker") or {}).get("unknown")
    # 1018 v2.1：防御句 / 搬运度 / 流水账 / 导读（answer_check 新增四项；旧结果没有这些键 = 按过算，和 R9–R12 的口径一样）
    if mode == "toc" or not ac or "defense" not in ac:
        checks["R13"] = checks["R14"] = checks["R15"] = checks["R16"] = True
    else:
        checks["R13"] = not (ac.get("defense") or {}).get("over", False)
        checks["R14"] = not (ac.get("copy") or {}).get("over", False)
        checks["R15"] = not (ac.get("per_source") or {}).get("flagged", False)
        g = ac.get("guide") or {}
        checks["R16"] = (bool(g.get("present")) and not g.get("missing") and not g.get("bad_locations")) if g.get("cited") else True
    core = all(checks[k] for k in CORE_RULES if k in checks)
    return {"pass": all(checks.values()), "pass_core": core, "checks": checks, "mode": mode, "cited": ids[:12],
            "must_have_ratio": (sum(have) / len(have)) if have else 1.0,
            "bad_titles": bad_titles, "bad_ids": bad_ids, "bad_text": bad_text, "chars": len(md),
            "self_check": {"warnings": ac.get("warnings"), "alignment": (ac.get("alignment") or {}).get("rate"),
                           "absence_conflicts": len((ac.get("absence") or {}).get("conflicts") or []),
                           "defense": (ac.get("defense") or {}).get("hits"), "copy": (ac.get("copy") or {}).get("ratio"),
                           "per_source_run": (ac.get("per_source") or {}).get("max_run"),
                           "guide": {k: (ac.get("guide") or {}).get(k) for k in ("present", "lines", "cited", "missing", "bad_locations")},
                           "selection": (result.get("selection") or {}).get("reason")},
            "task": result.get("task"), "cached": bool(result.get("cached")), "thought": (result.get("thought") or "")[:600],
            "first_para": first_paragraph(md)}


def first_paragraph(md):
    """正文第一段（跳过缓存提示 / 图 / 空行），给人看「第一段是不是判断句」。"""
    for para in re.split(r"\n\s*\n", md or ""):
        t = para.strip()
        if not t or t.startswith(">") or t.startswith("![[") or t.startswith("#"):
            continue
        return t[:300]
    return ""


def rejudge_r1(path, cases_path):
    """改了 R1 口径后，按存下的 mode / cited 重判 R1 和 pass（别的规则沿用当时的判定），不重跑模型。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in json.loads(Path(cases_path).read_text(encoding="utf-8"))}
    for row in data["rows"]:
        case = cases.get(row["id"]) or {}
        fake = {"mode": row["mode"], "markdown": row.get("markdown") or "",
                "toc": [{"id": i} for i in row["cited"]] if row["mode"] == "toc" else None,
                "sources": [{"id": i, "citation": n} for n, i in enumerate(row["cited"], 1)]}
        if row["mode"] != "toc":
            fake["markdown"] = " ".join(f"[来源{n}]" for n in range(1, len(row["cited"]) + 1)) + " " + fake["markdown"]
        row["checks"]["R1"] = judge(case, fake)["checks"]["R1"]
        row["pass"] = all(row["checks"].values())
        row["pass_core"] = all(row["checks"].get(k, True) for k in CORE_RULES)
    scored = [r for r in data["rows"] if r.get("tier") != "any"]
    data["summary"].update(_totals(scored))
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data["summary"]


def _totals(scored):
    return {"passed": sum(r["pass"] for r in scored), "pass_rate": round(sum(r["pass"] for r in scored) / max(1, len(scored)), 3),
            "passed_core": sum(1 for r in scored if r.get("pass_core", r["pass"])),
            "by_rule": {k: sum(r["checks"].get(k, False) for r in scored) for k in ALL_RULES},
            "cached": sum(1 for r in scored if r.get("cached"))}


def rescore(path, cases_path):
    """按存下的回答 + 来源摘录重跑自检（answer_check）并重判 R9–R12 和 pass；不调模型。只对带 sources 的结果有效。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from link_brain import answer_check
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in (raw.get("cases") if isinstance(raw, dict) else raw)}
    for row in data["rows"]:
        if not row.get("sources") and row.get("mode") != "toc":
            continue
        srcs = [{**s, "excerpt": ""} for s in row.get("sources") or []]
        checks = answer_check.run(row.get("markdown") or "", srcs, related=row.get("related") or [], mode=row.get("mode") or "direct",
                                  question=row.get("question") or "", task=row.get("task") or "")
        row["checks_rescored"] = checks
        fake = {"mode": row["mode"], "markdown": row.get("markdown") or "", "checks": checks, "selection": {"reason": (row.get("self_check") or {}).get("selection")},
                "toc": [{"id": i} for i in row["cited"]] if row["mode"] == "toc" else None,
                "sources": [{"id": i, "citation": n} for n, i in enumerate(row["cited"], 1)]}
        if row["mode"] != "toc":
            fake["markdown"] = " ".join(f"[来源{n}]" for n in range(1, len(row["cited"]) + 1)) + " " + fake["markdown"]
        v = judge(cases.get(row["id"]) or {}, fake)
        for k in ("R9", "R10", "R11", "R12", "R13", "R14", "R15", "R16"):
            row["checks"][k] = v["checks"][k]
        row["self_check"] = v["self_check"]
        row["pass"] = all(row["checks"].values())
        row["pass_core"] = all(row["checks"].get(k, True) for k in CORE_RULES)
    scored = [r for r in data["rows"] if r.get("tier") != "any"]
    data["summary"].update(_totals(scored))
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data["summary"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--vault", required=False)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rescore", action="store_true", help="不跑模型：按 --out 里存的回答和来源重跑自检、重判 R9–R12")
    ap.add_argument("--code")
    ap.add_argument("--only")
    ap.add_argument("--model", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--fresh-catalog", action="store_true", help="内存里按这份代码重收目录（不写盘）")
    args = ap.parse_args(argv)
    if args.rescore:
        print(json.dumps(rescore(args.out, args.cases), ensure_ascii=False, indent=1))
        return 0
    if not args.vault:
        ap.error("要 --vault")
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if isinstance(cases, dict):   # 1017 题集顶层是 {version, built_at, cases}
        cases = cases.get("cases") or []
    if args.only:
        want = set(args.only.split(","))
        cases = [c for c in cases if c.get("id") in want]
    link_brain, blocked, code_dir = _setup(args)
    usage = _usage_counter()
    from link_brain import ask
    if args.fresh_catalog:
        # 目录字段改过（评论区图片 / 画面文字 / 划重点）时：在内存里按这份代码重收一遍目录，不写 catalog-data.json
        from link_brain import catalog, storage
        fresh = catalog.collect(storage.vault_root())
        ask.load_items = lambda: ask._with_live_notes(fresh)
        print(f"内存目录：{len(fresh)} 篇", flush=True)
    rows = []
    for case in cases:
        history = []
        for prev in case.get("history") or []:
            history.append({"role": "user", "content": prev})
            history.append({"role": "assistant", "content": "（上一答略）"})
        start = time.perf_counter()
        before = dict(usage)
        try:
            res = ask.answer(case["question"], history, model=args.model)
        except Exception as exc:  # noqa: BLE001 - 一题崩了照样跑完
            res = {"status": "error", "markdown": f"崩了：{type(exc).__name__}: {exc}"}
        took = round(time.perf_counter() - start, 1)
        verdict = judge(case, res)
        tokens = {"prompt": usage["prompt"] - before["prompt"], "completion": usage["completion"] - before["completion"],
                  "calls": usage["calls"] - before["calls"]}
        rows.append({"id": case.get("id"), "question": case["question"], "tier": case.get("tier"), "status": res.get("status"),
                     "seconds": took, "tokens": tokens, **verdict,
                     "understanding": res.get("understanding"), "mode_reason": res.get("mode_reason"),
                     # 送给模型的全部来源（不只引用到的）：写参考答案 / 对比漏了什么用
                     "sources_all": [{k: s.get(k) for k in ("citation", "id", "title", "agent_md", "note")} for s in res.get("sources") or []],
                     "markdown": (res.get("markdown") or "")[:8000],
                     # 1017：存来源摘录 / 其他相关 / 自检结果，改了自检规则能用 --rescore 离线重判 R9–R12，不重跑模型
                     "sources": [{"id": s.get("id"), "citation": s.get("citation"), "title": s.get("title"), "author": s.get("author"),
                                  "excerpts": [{"field": e.get("field"), "text": str(e.get("text") or "")[:1500]} for e in (s.get("excerpts") or [])]}
                                 for s in (res.get("sources") or [])],
                     "related": [{"id": r.get("id"), "title": r.get("title"), "excerpt": str(r.get("excerpt") or "")[:600]} for r in (res.get("related") or [])[:30]],
                     "answer_checks": res.get("checks")})   # 键名别和 verdict 里的规则判分 checks 撞
        mark = "过" if verdict["pass"] else ("核" if verdict.get("pass_core") else "×")
        fails = ",".join(k for k, v in verdict["checks"].items() if not v)
        print(f"{case.get('id'):>4} {mark} {verdict['mode']:<6} {took:>5}s {tokens['prompt']:>6}+{tokens['completion']:<5} {fails:<14} {case['question'][:24]}",
              flush=True)
    scored = [r for r in rows if r.get("tier") != "any"]
    summary = {"label": args.label, "code": str(code_dir), "cases": len(rows), "scored": len(scored), **_totals(scored),
               "tokens": {"prompt": usage["prompt"], "completion": usage["completion"], "calls": usage["calls"],
                          "calls_without_usage": usage["unknown_calls"]},
               "blocked_writes": blocked, "f01": next((r["pass"] for r in rows if r["id"] == "F01"), None)}
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
