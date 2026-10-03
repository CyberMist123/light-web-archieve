"""「开始」页向导的后端（第 7 批，契约 docs/SETUP-CONTRACT.md）：

  python -m link_brain setup plan                         功能清单 + 磁盘 / 内存占用（带依据）+ 预设
  python -m link_brain setup check [--components a,b]     只检查不改东西
  python -m link_brain setup install --component <id>     边装边打进度事件（一行一个 JSON），最后一行 result
  python -m link_brain setup estimate [--posts 100]       每 100 篇的 AI 花费估算（按库里平均量 × 官方单价）
  python -m link_brain setup backfill                     补历史收藏：总数 / 已入库 / 还剩 / 每天上限 / 预计天数

check / plan 的 status：ready | missing | partial | failed（plan 里检查出错记 unknown）| needs_key（要 API key 的两项
没配 key：不算没装好，all_ready 不被它拖住，前端放到 ⑤ 填）。
输出都是 CONVENTIONS §1 形状 {ok, code, message, ...}，退出码和 ok 一致：0 成功 · 1 失败 · 5 要人手动处理
（装不了、只能照提示自己做的：Dataview、填 key、发布地址没配等）。人话原因进 stderr 最后一行。
"""
from __future__ import annotations

import sys
from typing import Any

EXIT_OK, EXIT_FAILED, EXIT_NEEDS_HUMAN = 0, 1, 5


def add_parser(sub) -> None:
    p = sub.add_parser("setup", help="「开始」页向导：plan / check / install / estimate / backfill")
    ssub = p.add_subparsers(dest="setup_command", metavar="<plan|check|install|estimate|backfill>")
    ssub.add_parser("plan", help="功能清单（每项磁盘 / 内存占用、状态、预设）")
    pc = ssub.add_parser("check", help="逐项检查（只读）")
    pc.add_argument("--components", default="", help="逗号分隔的功能 id，不给 = 全部")
    pi = ssub.add_parser("install", help="装一项：stdout 一行一个进度事件，最后一行 result")
    pi.add_argument("--component", required=True, help="功能 id：core / ocr / asr / capslock / reader / dataview / …")
    pi.add_argument("--asr-model", default="", help="CapsWriter 模型：qwen3-asr-q4（默认）/ sensevoice（小、快、准确度低一档）")
    pe = ssub.add_parser("estimate", help="每 N 篇的 AI 花费估算")
    pe.add_argument("--posts", type=int, default=100)
    ssub.add_parser("backfill", help="补历史收藏进度和预计天数")


def _say(message: str) -> None:
    if message:
        print(message, file=sys.stderr)


def run(args) -> int:
    from ..read import dump_json
    from . import backfill, components, estimate
    from .common import stdout_emit
    cmd = getattr(args, "setup_command", None)
    if cmd == "plan":
        dump_json(components.plan())
        return EXIT_OK
    if cmd == "check":
        ids = [x.strip() for x in (args.components or "").split(",") if x.strip()] or None
        out = components.check(ids)
        if not out["ok"]:
            _say(out["message"])
        dump_json(out)
        return EXIT_OK if out["ok"] else EXIT_FAILED
    if cmd == "install":
        from . import capswriter
        try:
            out: dict[str, Any] = components.install(args.component, stdout_emit,
                                                     asr_model=args.asr_model or capswriter.DEFAULT_MODEL)
        except KeyboardInterrupt:
            # Ctrl+C：下到一半的 .part 留着（再装接着下），解压的临时目录已在 finally 里删掉
            out = {"type": "result", "ok": False, "code": "TRANSIENT.INTERRUPTED", "component": args.component,
                   "status": "failed", "message": "安装被打断了：已下的部分留着，再点安装会接着来"}
        if not out["ok"]:
            _say(out["message"])
        stdout_emit(out)
        if out["ok"]:
            return EXIT_OK
        return EXIT_NEEDS_HUMAN if out.get("manual") else EXIT_FAILED
    if cmd == "estimate":
        dump_json(estimate.estimate(max(1, int(args.posts or 100))))
        return EXIT_OK
    if cmd == "backfill":
        dump_json(backfill.backfill())
        return EXIT_OK
    dump_json({"ok": False, "code": "SKIPPED.NOT_CONFIGURED", "message": "要给子命令：plan / check / install / estimate / backfill"})
    return EXIT_FAILED
