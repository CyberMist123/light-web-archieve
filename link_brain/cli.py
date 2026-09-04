"""`python -m link_brain` 命令行入口。

退出码约定（docs/FORMAT.md 也记了一份）：
  0  成功
  1  一般错误
  2  缺内容 gate 触发（明确知道缺东西，例如图片没下全）
  3  尚未实现的子命令
"""

from __future__ import annotations

import argparse
import sys

PROG = "python -m link_brain"

ORIGINS = ("tg", "cmx", "cc", "cli")
INGEST_KINDS = ("shared", "favorite")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_CONTENT = 2
EXIT_NOT_IMPLEMENTED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="light-web-archieve：把小红书链接归档成不可变 RAW + 一篇 Obsidian 可见笔记。",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="打印网络/MCP 调用等细节")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("ingest", help="归档一个链接（URL / xhslink 短链 / 分享文本）")
    p.add_argument("target", help="链接或包含链接的分享文本")
    p.add_argument("--origin", choices=ORIGINS, default="cli", help="从哪个端进来的")
    p.add_argument("--actor", default="human", help="human 或 ai:<name>")
    p.add_argument("--ingest-kind", choices=INGEST_KINDS, default="shared")
    p.add_argument("--note", default=None, help="原始附言，渲染成留言层 cmt1")
    p.add_argument("--refresh", action="store_true", help="重新抓取；有变化才写新 RAW 版本（Lot 2）")

    p = sub.add_parser("read", help="打印一个已归档对象")
    p.add_argument("target", help="item_id 或 URL")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--brief", action="store_true", help="只打印标题 + 概要（≤5 行）")
    g.add_argument("--full", action="store_true", help="打印整个 derived/agent.md")

    p = sub.add_parser("search", help="按关键词搜标题/正文")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("sync-favorites", help="同步小红书收藏（Lot 6，可选）")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("inbox", help="列出被戳到某角色且未处理的对象")
    p.add_argument("--for", dest="for_actor", required=True, help="角色名，如 fable")

    p = sub.add_parser("resolve", help="把一条留言标记为已处理")
    p.add_argument("target", help="item_id")
    p.add_argument("--comment-id", required=True, help="留言编号，如 cmt2")
    p.add_argument("--as", dest="as_actor", required=True, help="以谁的身份处理")

    p = sub.add_parser("comment", help="给一个对象追加一行留言")
    p.add_argument("target", help="item_id")
    p.add_argument("text", help="留言正文")
    p.add_argument("--as", dest="as_actor", required=True, help="human / gpt / fable / ...")
    p.add_argument("--target", dest="target_actor", default=None, help="戳给谁（不填就是自言自语）")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_OK

    if args.command == "ingest":
        from . import ingest as ingest_mod

        return ingest_mod.run(args)

    print(
        f"`{args.command}` 尚未实现（Lot 0 占位）。当前进度见 docs/STATE.md。",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
