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

    p = sub.add_parser('doctor', help='检查运行状态与首次设置（不修改配置）')
    p.add_argument('--json', action='store_true')
    p.add_argument('--obsidian-dir', help='实际 Obsidian 配置目录（插件自动传入）')
    p.add_argument('--only', choices=['local', 'xhs', 'favorites', 'attachments'], help='只检查一组能力，供界面逐项更新')
    p = sub.add_parser('login', help='打开扫码页面，自动验证并保存登录态')
    p.add_argument('account', nargs='?', choices=['xhs', 'favorites', 'attachments'], default='xhs')
    p.add_argument('--force', action='store_true', help='重新登录 / 附件换号')
    p.add_argument('--install', action='store_true', help='缺少读取组件时下载官方 Windows x64 组件')
    p.add_argument('--timeout', type=int, default=300, help='扫码等待秒数')
    p.add_argument('--json', action='store_true')

    p = sub.add_parser("ingest", help="归档一个链接（URL / xhslink 短链 / 分享文本）")
    p.add_argument("target", help="链接或包含链接的分享文本")
    p.add_argument("--origin", choices=ORIGINS, default="cli", help="从哪个端进来的")
    p.add_argument("--actor", default="human", help="human 或 ai:<name>")
    p.add_argument("--ingest-kind", choices=INGEST_KINDS, default="shared")
    p.add_argument("--note", default=None, help="原始附言，渲染成留言层 cmt1")
    p.add_argument("--refresh", action="store_true", help="重新抓取；有变化才写新 RAW 版本（Lot 2）")

    p = sub.add_parser(
        "catch",
        help="给主模型用：吃一整条消息，自己找小红书链接归档，只打一个 JSON",
    )
    p.add_argument("message", help="原始消息全文（整条会当作留言 cmt1 存进可见笔记）")
    p.add_argument("--origin", choices=ORIGINS, default="cli", help="从哪个端进来的")
    p.add_argument("--actor", default="human", help="human 或 ai:<name>")
    p.add_argument(
        "--extract",
        action="store_true",
        help="顺手调小模型补 extracted.json（默认不调，概要退回正文前 120 字）",
    )

    p = sub.add_parser("read", help="打印一个已归档对象")
    p.add_argument("target", help="item_id 或 URL")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--brief", action="store_true", help="只打印标题 + 概要（≤5 行）")
    g.add_argument("--full", action="store_true", help="打印整个 derived/agent.md")
    p.add_argument("--json", action="store_true", help="机器可读版（给主模型），配合 --brief/--full")

    p = sub.add_parser("search", help="按关键词搜标题/正文")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true", help="机器可读版（给主模型）")

    p = sub.add_parser("reindex", help="从已有 raw/ 回填 index.db（不重抓、不联网）")

    p = sub.add_parser("render", help="拼可见 md + derived/agent.md（先跑 vision，纯程序拼模板）")
    p.add_argument("target", nargs="?", default=None, help="item_id；配合 --all 时可省略")
    p.add_argument("--all", action="store_true", help="对索引里所有对象都渲染一遍")
    p.add_argument(
        "--extract",
        action="store_true",
        help="缺 derived/extracted.json（或上次失败）时调小模型生成（Lot 4，不重抓网页）",
    )
    p.add_argument(
        "--re-extract",
        dest="re_extract",
        action="store_true",
        help="强制重调小模型，覆盖已有的 extracted.json",
    )

    p = sub.add_parser("attachments", help="下载笔记附件字节（要 agent-browser 小号登录态）")
    p.add_argument("target", nargs="?", default=None, help="item_id；配合 --all 时可省略")
    p.add_argument("--all", action="store_true", help="对所有带附件元数据的对象都下一遍")
    p.add_argument("--force", action="store_true", help="已经下过也重下")
    p.add_argument("--doc-id", default=None, help="手动挂载到指定附件")
    p.add_argument("--audit", action="store_true", help="输出附件完整性 JSON，不联网")
    p.add_argument("--attach", default=None,
                   help="把本地已下好的文件手动挂到这篇（系统下不了时用）：给文件路径")

    p = sub.add_parser("note", help="笔记批注 / ⭐ 收藏（sidecar，不改正文）")
    nsub = p.add_subparsers(dest="note_command")
    pn = nsub.add_parser("star", help="⭐ 收藏开关：点亮复制正文到 vault 根，熄灭删副本")
    pn.add_argument("target", help="item_id 或裸 source_id")
    pn.add_argument("--off", action="store_true", help="取消收藏（默认是点亮）")
    pn = nsub.add_parser("add", help="加一条批注（@fable 开头会打标）")
    pn.add_argument("target", help="item_id 或裸 source_id")
    pn.add_argument("text", help="批注文字")
    pn = nsub.add_parser("list", help="列出这篇的批注和收藏态")
    pn.add_argument("target", help="item_id 或裸 source_id")

    p = sub.add_parser("pdf2md", help="把已下载的 PDF 附件转成 Markdown（文字层坏了自动退回逐页 OCR）")
    p.add_argument("target", nargs="?", default=None, help="item_id；配合 --all 时可省略")
    p.add_argument("--all", action="store_true", help="所有下过附件的对象都转一遍")
    p.add_argument("--force", action="store_true", help="已经转过也重转")
    p.add_argument("--force-ocr", dest="force_ocr", action="store_true",
                   help="跳过文字层，直接逐页 OCR")

    p = sub.add_parser("sync-favorites", help="同步小红书收藏（Lot 6）")
    p.add_argument("--limit", type=int, default=0, help="最多同步多少条收藏（0=全量，favdump 顺序）；默认全量，靠 ingest 去重做增量，别再截成第一页")
    p.add_argument("--origin", choices=ORIGINS, default="cli", help="从哪个端触发的")
    p.add_argument("--actor", default="human", help="human 或 ai:<name>")
    p.add_argument("--extract", action="store_true", help="顺带跑小模型派生（花钱，默认不跑）")

    p = sub.add_parser('videos', help='补下载已有视频，或独立运行本机转写')
    p.add_argument('target', nargs='?')
    p.add_argument('--all', action='store_true')
    p.add_argument('--transcribe', action='store_true')

    sub.add_parser("export-bundle", help="从 stdin 接收选帖，导出 Markdown 与可选原图 ZIP")

    p = sub.add_parser("catalog", help="重写 vault 里的收藏目录页（纯程序拼，不联网）")
    p.add_argument("--print-cats", action="store_true", help="只打印当前生效的大类（设置页载入用），不重建")

    p = sub.add_parser("topic", help="星标主题：口头建、AI 配关键词，目录页 cats 栏下出一排 chip（输出 JSON）")
    tsub = p.add_subparsers(dest="topic_command")
    pt = tsub.add_parser("add", help="建主题：用问答模型扩 5-10 个关键词（模型不可用就用主题名本身）")
    pt.add_argument("name", help="主题名，如「AI 记忆层」")
    pt.add_argument("--no-catalog", dest="no_catalog", action="store_true", help="不顺手重建目录")
    tsub.add_parser("list", help="列出主题（含命中篇数，按上次重建的目录算）")
    pt = tsub.add_parser("remove", help="删主题")
    pt.add_argument("ref", help="主题 id 或名字")
    pt.add_argument("--no-catalog", dest="no_catalog", action="store_true", help="不顺手重建目录")
    pt = tsub.add_parser("rename", help="改主题名（关键词不变）")
    pt.add_argument("ref", help="主题 id 或旧名字")
    pt.add_argument("new_name", help="新名字")
    pt.add_argument("--no-catalog", dest="no_catalog", action="store_true", help="不顺手重建目录")

    p = sub.add_parser("embed",help="chunk 索引 + embedding 旁挂（增量写 semantic.db；没 key 时失败但不影响其它命令）")
    p.add_argument("--all", action="store_true", help="忽略已有向量，全部重算")

    p = sub.add_parser('retrieve', help='给 AI 返回命中摘录和链接，不调用模型')
    p.add_argument('question')
    p.add_argument('--top-k', type=int, default=8)

    p = sub.add_parser('serve', help='常驻 stdio 问答 worker')
    p.add_argument('--stdio', action='store_true', required=True)

    p = sub.add_parser("ask", help="基于本地归档库问答（/问AI 的后端；只把少量片段送模型）")
    p.add_argument("question", nargs="?", default="", help="自然语言问题")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--history-stdin", action="store_true", help="从 stdin 读取 [{role,content}] 追问历史")
    g.add_argument("--request-stdin", action="store_true", help="从 stdin 读取完整 JSON 请求：question/history/include")
    p.add_argument("--include", action="append", choices=["body", "links", "files"], help="可重复：正文之外返回链接或文件；默认只有正文")

    p = sub.add_parser("selftest", help="设置页「测试」按钮的后端：发一次最小调用验证接口")
    p.add_argument("kind", choices=["text", "ocr"], help="测哪条接口")

    p = sub.add_parser("clean", help="清洗分享文案里的小红书链接（跟随短链、只留 xsec_token/source），输出 JSON")
    p.add_argument("text", help="一整段分享文案或链接")

    p = sub.add_parser("delete", help="移动收藏到回收站，并屏蔽后续同步")
    p.add_argument("item_ids", nargs="+", help="一个或多个 item_id")

    p = sub.add_parser('trash', help='恢复、彻底删除或清空回收站')
    p.add_argument('action', choices=['restore', 'purge', 'empty'])
    p.add_argument('item_ids', nargs='*')

    p = sub.add_parser("tidy-comments", help="去掉旧笔记里纯链接的自动 cmt1 留言")

    p = sub.add_parser("sync-schedule", help="看/改每晚收藏巡检的周期（Windows 计划任务 XhsFavSync）")
    p.add_argument("--set", choices=["daily", "weekly", "off"], help="改成每天/每周/关闭；不给就只报当前")
    p.add_argument("--at", help="时间 HH:mm（如 04:00 / 22:30）；配合 --set daily/weekly")
    p.add_argument("--day", help="周几（Monday…Sunday）；配合 --set weekly")

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

    p = sub.add_parser("highlight", help="给一篇笔记正文加/去一处高亮（<mark>，持久到重渲染）")
    p.add_argument("target", help="item_id")
    p.add_argument("phrase", help="要高亮的原文片段（原样、含标点，需在正文里出现过）")
    p.add_argument("--remove", action="store_true", help="去掉这处高亮")

    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK：给人看的 print 一碰到 emoji（小红书标题里到处是）就
    # UnicodeEncodeError 整条命令崩。只把错误策略降成 replace，不改编码——Owner 的中文照常显示。
    # 机器可读的 JSON 不走这条路，直接写 UTF-8 字节，见 `read.dump_json`。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # pytest 的捕获流没有 reconfigure
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_OK

    if args.command == 'doctor':
        from . import doctor
        return doctor.run(args)
    if args.command == 'login':
        from . import accounts
        return accounts.run_login(args)
    if args.command == 'videos':
        from . import videos
        return videos.run(args)
    if args.command == 'topic':
        from . import topics
        return topics.run(args)
    if args.command == 'embed':
        from . import semantic
        return semantic.run(args)
    if args.command == 'retrieve':
        from .retrieval import retrieve_payload
        from .read import dump_json
        dump_json(retrieve_payload(args.question,args.top_k))
        return 0
    if args.command == 'serve':
        from . import serve
        return serve.run(args)
    if args.command == "ingest":
        from . import ingest as ingest_mod

        return ingest_mod.run(args)

    if args.command == "catch":
        from . import catch as catch_mod

        return catch_mod.run(args)

    if args.command == "read":
        from . import read as read_mod

        return read_mod.run(args)

    if args.command == "search":
        from . import read as read_mod

        return read_mod.run_search(args)

    if args.command == "reindex":
        from . import index as index_mod

        conn = index_mod.connect()
        try:
            done = index_mod.reindex_all(conn, verbose=getattr(args, "verbose", False))
        finally:
            conn.close()
        print(f"回填 {len(done)} 个对象：" + (", ".join(done) if done else "(空)"))
        return EXIT_OK

    if args.command == "attachments":
        from . import attachments as attachments_mod

        return attachments_mod.run(args)

    if args.command == "note":
        from . import note as note_mod

        return note_mod.run(args)

    if args.command == "pdf2md":
        from . import pdftext as pdftext_mod

        return pdftext_mod.run(args)

    if args.command == "render":
        from . import render as render_mod

        return render_mod.run(args)

    if args.command == "highlight":
        from . import render as render_mod

        path, changed = render_mod.set_highlight(args.target, args.phrase, remove=args.remove)
        verb = "去掉高亮" if args.remove else "加高亮"
        print(f"{verb}：{'已改' if changed else '未找到该片段 / 无变化'} · {path}")
        return EXIT_OK if changed else 1

    if args.command == "sync-favorites":
        from . import favorites as favorites_mod

        return favorites_mod.run(args)

    if args.command == "export-bundle":
        from . import export_bundle
        return export_bundle.run(args)

    if args.command == "catalog":
        from . import catalog as catalog_mod

        return catalog_mod.run(args)

    if args.command == "ask":
        from . import ask as ask_mod

        return ask_mod.run(args)

    if args.command == "selftest":
        from . import ask as ask_mod

        return ask_mod.run_selftest(args)

    if args.command == "clean":
        from .adapters import xiaohongshu as xhs
        from .read import dump_json

        urls = xhs.clean_share_text(args.text)
        dump_json({"count": len(urls), "urls": urls})
        return EXIT_OK

    if args.command in ("delete", "trash"):
        from . import remove as remove_mod

        return remove_mod.run(args)

    if args.command == "tidy-comments":
        from . import render as render_mod
        from .read import dump_json

        dump_json(render_mod.tidy_link_comments())
        return EXIT_OK

    if args.command == "sync-schedule":
        from . import sync_schedule as sync_schedule_mod

        return sync_schedule_mod.run(args)

    if args.command in ("comment", "inbox", "resolve"):
        from . import comments as comments_mod

        return {
            "comment": comments_mod.run_comment,
            "inbox": comments_mod.run_inbox,
            "resolve": comments_mod.run_resolve,
        }[args.command](args)

    print(
        f"`{args.command}` 尚未实现（Lot 0 占位）。当前进度见 docs/STATE.md。",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
