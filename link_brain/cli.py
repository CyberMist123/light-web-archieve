"""`python -m link_brain` 命令行入口。

退出码约定（docs/FORMAT.md 也记了一份）：
  0  成功 / 部分完成（到预算、到每日上限，剩下的明天接着来）
  1  一般错误
  2  缺内容 gate 触发（明确知道缺东西，例如图片没下全）
  3  尚未实现的子命令（`login --status` 另有约定：3 = 游客）
  5  要人处理：掉登录 / 安全验证 / 风控熔断中（已停车，没接着开页）
  6  号正被别的任务占用（同步收藏 / 附件 / 导入在跑），稍后再试
"""

from __future__ import annotations

import argparse
import json
import sys

PROG = "python -m link_brain"

ORIGINS = ("tg", "cmx", "cc", "cli")
INGEST_KINDS = ("shared", "favorite")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_CONTENT = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_NEEDS_HUMAN = 5
EXIT_ACCOUNT_BUSY = 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="light-web-archieve：把小红书链接归档成不可变 RAW + 一篇 Obsidian 可见笔记。",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="打印网络/MCP 调用等细节")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser('watch', help='实时进度黑框：号状态、正在抓什么、最近每次用号的结果（只读本机文件，不碰号）')
    p.add_argument('--interval', type=float, default=2, help='几秒刷新一次（默认 2）')
    p.add_argument('--once', action='store_true', help='只打印一屏就退出')

    p = sub.add_parser('crawl', help='交替抓取：抓新收藏 → 补评论 → 补以前的收藏 → 补评论 …（像人一样间歇，跑满 1 小时歇半小时）')
    p.add_argument('--hours', type=float, default=0, help='最多跑几小时（0 = 一直跑，Ctrl+C 停）')
    p.add_argument('--fav-min', type=int, default=20, help='每块抓收藏最多几分钟（默认 20）')
    p.add_argument('--comments-min', type=int, default=25, help='每块补评论最多几分钟（默认 25）')

    p = sub.add_parser('doctor', help='检查运行状态与首次设置（不修改配置）')
    p.add_argument('--json', action='store_true')
    p.add_argument('--obsidian-dir', help='实际 Obsidian 配置目录（插件自动传入）')
    p.add_argument('--only', choices=['local', 'xhs', 'favorites', 'attachments'], help='只检查一组能力，供界面逐项更新')
    p = sub.add_parser('login', help='打开扫码页面，自动验证并保存登录态（一个号覆盖读取/收藏/附件）')
    p.add_argument('account', nargs='?', choices=['xhs', 'favorites', 'attachments'], default='xhs',
                   help='兼容旧用法；三项现在是同一个账号')
    p.add_argument('--force', action='store_true', help='已登录也重新出码')
    p.add_argument('--verify', action='store_true', help='打开验证窗口，手动完成小红书安全验证')
    p.add_argument('--status', action='store_true', help='只检查登录状态')
    p.add_argument('--logout', action='store_true', help='退出登录（只清本地读取组件的登录）')
    p.add_argument('--qr', action='store_true', help='出二维码网页（远程扫码用），默认打开小红书官方登录窗口')
    p.add_argument('--timeout', type=int, default=270, help='扫码等待秒数')
    p.add_argument('--json', action='store_true')
    # 1008（L6·S4 / B1）
    p.add_argument('--shallow', action='store_true',
                   help='配合 --status：浅查——只问读取服务内存里的状态，服务没起不拉起、不开浏览器（设置页账号行用）')
    p.add_argument('--wait', action='store_true', help='配合 --verify：等验证窗口关掉，如实回报结论（只轮询内存状态，不开页）')
    p.add_argument('--clear-hold', dest='clear_hold', action='store_true',
                   help='「没看到验证，恢复」：解除风控暂停（必须同时带 --by-owner，表示是你亲手确认的）')
    p.add_argument('--by-owner', dest='by_owner', action='store_true', help='配合 --clear-hold：你亲手确认')

    p = sub.add_parser("transcribe", help="把一段录音转成文字（问 AI 的语音输入用）")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("vision", help="识图：--upgrade 第一层（全库分批）/ --refine 第二层补跑打了标的图 / --refine-mark 手动点名")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--upgrade", action="store_true", help="第一层：本地 OCR + 便宜模型，按识图版本全库分批重跑")
    g.add_argument("--refine", action="store_true", help="第二层：强模型补跑 refine: pending 的图，一次一张")
    g.add_argument("--refine-mark", metavar="ITEM_ID", help="手动点名：把这篇（或 --asset 那一张）标成待精细识别")
    p.add_argument("--asset", help="配合 --refine-mark：只点名这一张（vision.json 里的 asset 路径或文件名）")
    p.add_argument("--now", action="store_true", help="配合 --refine-mark：点名后马上补跑这篇，不等夜里")
    p.add_argument("--retry-failed", dest="retry_failed", action="store_true",
                   help="配合 --refine-mark：只重标这篇里精细识别放弃了的图（问题列表「现在修」用）")
    p.add_argument("--limit", type=int, default=30, help="--upgrade 最多几篇 / --refine 最多几张，0 = 全部")

    p = sub.add_parser("comments", help="手动抓一篇的评论区（楼中楼 / 评论图片 / 语音评论）；--fill 续读上次没读全的楼")
    p.add_argument("target", nargs="?", default=None, help="item_id（xhs-<note_id>）或链接")
    p.add_argument("--floors", default="all", choices=["all", "20", "50"], help="默认全量；慢，热门笔记可能要十几分钟")
    p.add_argument("--fill", action="store_true", help="续读：只展开上次预算用完没读全的那几楼（每次约 9 分钟）")
    p.add_argument("--fill-pending", dest="fill_pending", action="store_true",
                   help="给库里评论还有缺口的篇各续读一次（按设置里的楼数现算缺口，缺得少的在前；每篇自己拿账号锁）")
    p.add_argument("--limit", type=int, default=0, help="配合 --fill-pending：最多续几篇（0=不限）")
    p.add_argument("--only", action="append", default=None, metavar="ITEM_ID[,…]",
                   help="配合 --fill-pending：只补这几篇（按 --floors 的楼数，不改设置），配 --until-done 补到没有缺口为止")
    p.add_argument("--budget-min", dest="budget_min", type=float, default=0, help="配合 --fill-pending：最多跑几分钟")
    p.add_argument("--until-done", dest="until_done", action="store_true",
                   help="配合 --fill-pending：后台一直补到全库没有缺口（撞验证 / 掉登录就停下等，处理好自动接着；夜跑时让路）")
    p.add_argument("--detach", action="store_true",
                   help="配合 --fill-pending：在后台拉起 --until-done 补跑（单实例，已经在跑就不再起），立刻返回")
    p.add_argument("--then-background", dest="then_background", action="store_true",
                   help="配合 --fill-pending（夜跑用）：预算内没补完就转到后台接着补")
    p.add_argument("--fill-status", dest="fill_status", action="store_true",
                   help="评论补齐进度 JSON（本地读，不碰号；插件设置页 / 状态栏用）")
    p.add_argument("--wait-lock-min", dest="wait_lock_min", type=float, default=2,
                   help="号被别的任务占着时最多等几分钟（默认 2），等不到退出码 6")
    p.add_argument("--progress", action="store_true",
                   help="手动抓一篇时 stdout 一行一个进度事件 JSON（等号 / 读评论区 / 下评论图 / 写进笔记），最后一行照旧是结果（插件笔记页画进度用）")

    p = sub.add_parser("note-verify", help="1011：这篇在小红书网页版要验证才能看——开验证窗口到这篇，她过完验证关窗后自动补抓评论 / 附件")
    p.add_argument("target", help="item_id（xhs-<note_id>）")
    p.add_argument("--wait", action="store_true", help="等窗口关掉再如实回报结果（只轮询读取服务内存状态，不开页）")

    p = sub.add_parser("ingest", help="归档一个链接（URL / xhslink 短链 / 分享文本）")
    p.add_argument("target", help="链接或包含链接的分享文本")
    p.add_argument("--origin", choices=ORIGINS, default="cli", help="从哪个端进来的")
    p.add_argument("--actor", default="human", help="human 或 ai:<name>")
    p.add_argument("--ingest-kind", choices=INGEST_KINDS, default="shared")
    p.add_argument("--note", default=None, help="原始附言，渲染成留言层 cmt1")
    p.add_argument("--refresh", action="store_true", help="重新抓取；有变化才写新 RAW 版本（Lot 2）")
    p.add_argument("--wait-lock-min", dest="wait_lock_min", type=float, default=2,
                   help="号被别的任务占着时最多等几分钟（默认 2），等不到退出码 6")

    p = sub.add_parser("prune-comments", help="删掉某个角色留在正文留言层的留言（默认 system 的「收好了」戳）")
    p.add_argument("--actor", default="system")
    p.add_argument("--dry-run", dest="dry_run", action="store_true")

    p = sub.add_parser("relabel", help="改「谁收的」（meta + 索引）：比如 AI 调研收的帖被记成了她分享的；改完跑 catalog")
    p.add_argument("items", nargs="+", help="笔记 id（xhs- 前缀可省）")
    p.add_argument("--actor", help="human 或 ai:<name>")
    p.add_argument("--origin", choices=ORIGINS)
    p.add_argument("--project", help="项目名（空串 = 清掉）")

    p = sub.add_parser(
        "catch",
        help="给主模型用：吃一整条消息，自己找小红书链接归档，只打一个 JSON",
    )
    p.add_argument("message", help="原始消息全文（整条会当作留言 cmt1 存进可见笔记）")
    p.add_argument("--origin", choices=ORIGINS, default="cli", help="从哪个端进来的")
    p.add_argument("--actor", default="human", help="human 或 ai:<name>")
    p.add_argument("--project", default="", help="AI 为哪个项目收的（目录里按它分组，比如 graph / ai群聊）；只记在新收的篇上")
    p.add_argument(
        "--extract",
        action="store_true",
        help="顺手调小模型补 extracted.json（默认不调，概要退回正文前 120 字）",
    )
    p.add_argument("--refresh", action="store_true", help="已在库也重新抓一次（有变化才写新 RAW 版本）")
    p.add_argument("--wait-lock-min", dest="wait_lock_min", type=float, default=2,
                   help="号正被同步收藏 / 附件占着时最多等几分钟（默认 2）；等不到退出码 6「正在同步收藏，稍后再收」")

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

    p = sub.add_parser("browse", help="翻收藏目录：按入库日期 / 标签筛，新→旧（和 MCP search 同一套，不调模型）")
    p.add_argument("query", nargs="?", default="", help="可选关键词；不给 = 只按过滤条件列")
    p.add_argument("--date", help="某天入库的（YYYY-MM-DD）")
    p.add_argument("--since", help="入库日期从（YYYY-MM-DD）")
    p.add_argument("--until", help="入库日期到（YYYY-MM-DD）")
    p.add_argument("--tag", help="按标签（整词优先、无则包含）")
    p.add_argument("--album", help="按她的小红书专辑（整名优先、无则包含）")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--json", action="store_true", help="机器可读版")

    p = sub.add_parser("albums", help="小红书专辑：sync 读专辑列表和每个专辑里的笔记（碰号，夜跑一步）；list 看本地记下的专辑")
    p.add_argument("action", choices=["sync", "list"])
    p.add_argument("--max", type=int, default=6, help="sync：这次最多开几个专辑")
    p.add_argument("--budget-min", dest="budget_min", type=float, default=25, help="sync：最多花几分钟")
    p.add_argument("--no-list", dest="no_list", action="store_true", help="sync：不读专辑列表，只看已知专辑")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("item", help="读一篇的机读版（可只取一段）或拿第 N 张原图的路径（和 MCP read 同一套）")
    p.add_argument("target", help="item_id（带不带 xhs- 都行）或原文链接")
    p.add_argument("--part", help="只取这一段：概要 / 重要细节 / 原文 / 图片 OCR / 评论 / 附件全文 …（包含匹配）")
    p.add_argument("--image", type=int, help="第 N 张图（正文图在前、评论图在后，和 agent.md 里的「图N」一致）：打印绝对路径")
    p.add_argument("--offset", type=int, default=0, help="长文续读：从第几个字符开始")
    p.add_argument("--max-chars", dest="max_chars", type=int, default=30000)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("reindex", help="从已有 raw/ 回填 index.db（不重抓、不联网）")

    p = sub.add_parser("render", help="拼可见 md + derived/agent.md（纯程序拼模板；加 --vision 才先跑识图）")
    p.add_argument("target", nargs="?", default=None, help="item_id；配合 --all 时可省略")
    p.add_argument("--all", action="store_true", help="对索引里所有对象都渲染一遍")
    p.add_argument("--vision", action="store_true",
                   help="先跑识图（调识图模型，可能花钱）再写笔记；默认不识图，识图平时由 enrich 补")
    p.add_argument("--no-vision", dest="no_vision", action="store_true",
                   help="（默认就是这样，保留兼容）只用已有识图结果重写笔记，不调识图模型")
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

    p = sub.add_parser("attachments", help="下载笔记附件字节（经读取服务 link-brain-reader，与收藏、评论同一个号；掉登录走 login 扫码）")
    p.add_argument("target", nargs="?", default=None, help="item_id；配合 --all 时可省略")
    p.add_argument("--all", action="store_true", help="对所有带附件元数据的对象都下一遍")
    p.add_argument("--force", action="store_true", help="已经下过也重下")
    p.add_argument("--doc-id", default=None, help="手动挂载到指定附件")
    p.add_argument("--audit", action="store_true", help="输出附件完整性 JSON，不联网")
    p.add_argument("--recheck", action="store_true", help="补查当时网页探测失败的笔记（游客浏览器），探到附件就下载；查不清的报警")
    p.add_argument("--limit", type=int, default=0,
                   help="--recheck 每次最多查几篇（0=不限；--guest-only 时 0=自动：平时 20、积压期 40；--logged-in-tail 时 0=5）")
    p.add_argument("--guest-only", dest="guest_only", action="store_true",
                   help="配合 --recheck：游客段——不碰号（不拉起读取服务、不拿账号锁），只登记探到的附件，不下载")
    p.add_argument("--logged-in-tail", dest="logged_in_tail", action="store_true",
                   help="配合 --recheck：收尾段——游客读不到的用登录号看一眼（碰号，熔断 / 账号锁 / 开页间隔照旧）")
    p.add_argument("--recheck-status", dest="recheck_status", action="store_true", help="输出附件补查状态 JSON，不联网")
    p.add_argument("--skipped", default=None, help="记一笔「收尾段今晚跳过了」和原因（夜跑脚本用），不联网")
    p.add_argument("--reconcile", action="store_true", help="附件补查本地对账（不联网），输出 JSON")
    p.add_argument("--attach", default=None,
                   help="把本地已下好的文件手动挂到这篇（系统下不了时用）：给文件路径")
    p.add_argument("--dedupe", action="store_true",
                   help="一次性修复：同一文件记了两条（manual-… 和真编号）的并成一条，不联网")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="配合 --dedupe：只报会改哪几篇，不写")
    p.add_argument("--wait-lock-min", dest="wait_lock_min", type=float, default=10,
                   help="号被别的任务占着时最多等几分钟（默认 10），等不到退出码 6")
    p.add_argument("--budget-min", dest="budget_min", type=float, default=0,
                   help="最多跑几分钟（0=不限）：剩下的时间装不下下一个附件页就收手、正常收尾，剩下的下次补（退出码 0）")

    p = sub.add_parser("note", help="笔记批注 / ⭐ 收藏（sidecar，不改正文）")
    nsub = p.add_subparsers(dest="note_command")
    pn = nsub.add_parser("star", help="⭐ 收藏开关：点亮复制正文到 vault 根，熄灭删副本")
    pn.add_argument("target", nargs="+", help="item_id 或裸 source_id（可以一次给多个：catalog-data 整批只改一次）")
    pn.add_argument("--off", action="store_true", help="取消收藏（默认是点亮）")
    pn = nsub.add_parser("add", help="加一条批注（@fable 开头会打标）")
    pn.add_argument("target", help="item_id 或裸 source_id")
    pn.add_argument("text", help="批注文字")
    pn = nsub.add_parser("list", help="列出这篇的批注和收藏态")
    pn.add_argument("target", help="item_id 或裸 source_id")
    pn = nsub.add_parser("notify", help="没送过的 @ 批注交给通知命令（notify-cmd.txt），同一条只送一次")
    pn.add_argument("--dry-run", dest="dry_run", action="store_true", help="只列出来，不送")
    pn = nsub.add_parser("reply", help="AI 回一条批注（显示在被回那条下面）")
    pn.add_argument("target", help="item_id 或裸 source_id")
    pn.add_argument("annot_id", help="被回的那条批注的 id")
    pn.add_argument("text", help="回复文字")
    pn.add_argument("--as", dest="as_actor", default="fable", help="谁回的（默认 fable）")

    p = sub.add_parser("pdf2md", help="把已下载的 PDF 附件转成 Markdown（文字层坏了自动退回逐页 OCR）")
    p.add_argument("target", nargs="?", default=None, help="item_id；配合 --all 时可省略")
    p.add_argument("--all", action="store_true", help="所有下过附件的对象都转一遍")
    p.add_argument("--force", action="store_true", help="已经转过也重转")
    p.add_argument("--force-ocr", dest="force_ocr", action="store_true",
                   help="跳过文字层，直接逐页 OCR")

    p = sub.add_parser("sync-favorites", help="同步小红书收藏（Lot 6）")
    p.add_argument("--limit", type=int, default=0, help="最多同步多少条收藏（0=全量，按读取服务返回的收藏顺序）；默认全量，靠 ingest 去重做增量，别再截成第一页")
    p.add_argument("--origin", choices=ORIGINS, default="cli", help="从哪个端触发的")
    p.add_argument("--actor", default="human", help="human 或 ai:<name>")
    p.add_argument("--extract", action="store_true",
                   help="抓取阶段结束后，对本次新收的笔记补识图 + 概要（不碰号，受剩余预算约束）")
    p.add_argument("--budget-min", dest="budget_min", type=float, default=0,
                   help="最多跑几分钟（0=不限）：到点不再开新的抓取，剩下的明天继续（退出码 0）")
    p.add_argument("--wait-lock-min", dest="wait_lock_min", type=float, default=10,
                   help="号被别的任务占着时最多等几分钟（默认 10），等不到退出码 6")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true",
                   help="这次读全量收藏（滚到底；平时只读最新一段，每周一次全量）")
    g.add_argument("--from-snapshot", dest="from_snapshot", action="store_true",
                   help="不读收藏列表，只按上次全量名单补抓积压（夜里撞验证、自查恢复后用）")

    p = sub.add_parser("enrich", help="给已归档的笔记补识图 + 概要（不碰号；每篇子进程、20 分钟上限）")
    p.add_argument("--pending", action="store_true",
                   help="处理全部候选：待 enrich 的（新收的）/ 概要失败或缺失的 / 有图没识的")
    p.add_argument("--item", default=None, help="只补这一篇（item_id）；失败满 3 次的也照跑")
    p.add_argument("--budget-min", dest="budget_min", type=float, default=0, help="最多跑几分钟（0=不限）")
    p.add_argument("--limit", type=int, default=0, help="最多补几篇（0=不限）")

    p = sub.add_parser('videos', help='补下载已有视频，或独立运行本机转写')
    p.add_argument('target', nargs='?')
    p.add_argument('--all', action='store_true')
    p.add_argument('--transcribe', action='store_true')
    p.add_argument('--rescreen', action='store_true', help='配合 --transcribe：没人声 / 没音轨的视频重读一次画面字幕')

    sub.add_parser("export-bundle", help="从 stdin 接收选帖，导出 Markdown 与可选原图 ZIP")

    p = sub.add_parser("catalog", help="重写 vault 里的收藏目录页（纯程序拼，不联网）")
    p.add_argument("--print-cats", action="store_true", help="只打印当前生效的大类（设置页载入用），不重建")
    p.add_argument("--if-dirty", action="store_true", help="只在有待重建（_archive/catalog-dirty.json）时重建")

    # 10-10 索引树（库根 索引.md → _archive/index-data.json）与节点 wiki
    from . import indextree, wiki as wiki_mod
    indextree.add_parser(sub)
    wiki_mod.add_parser(sub)

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

    sub.add_parser('mcp', help='MCP stdio 服务（给本机 AI 客户端接）')
    p = sub.add_parser('serve', help='常驻 stdio 问答 worker')
    p.add_argument('--stdio', action='store_true', required=True)

    p = sub.add_parser("skills", help="问收藏的技能：list 列出 / show <id> 看正文 / import <SKILL.md 或文件夹> 导入（只拷文字）")
    p.add_argument("action", nargs="?", default="list", choices=["list", "show", "import"])
    p.add_argument("target", nargs="?", default="", help="show：技能 id；import：SKILL.md 文件或含它的文件夹")
    p.add_argument("--overwrite", action="store_true", help="import：同名技能直接覆盖")

    p = sub.add_parser("ask", help="基于本地归档库问答（/问AI 的后端；只把少量片段送模型）")
    p.add_argument("question", nargs="?", default="", help="自然语言问题")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--history-stdin", action="store_true", help="从 stdin 读取 [{role,content}] 追问历史")
    g.add_argument("--request-stdin", action="store_true", help="从 stdin 读取完整 JSON 请求：question/history/include")
    p.add_argument("--include", action="append", choices=["body", "links", "files"], help="可重复：正文之外返回链接或文件；默认只有正文")

    p = sub.add_parser("selftest", help="设置页「测试」按钮的后端：发一次最小调用验证接口")
    p.add_argument("kind", choices=["text", "summary", "vision", "ocr", "asr", "mcp"],
                   help="测哪个能力：text 问答 / summary 归档摘要 / vision 识图 / ocr 本地 OCR / asr 语音识别 / mcp")

    p = sub.add_parser("usage", help="设置页「用量与余额」：按功能 / 提供商汇总 token 和花费，可带余额")
    p.add_argument("--balance", action="store_true", help="顺带查余额（DeepSeek 有接口；千问只给跳转）")
    p.add_argument("--table", action="store_true", help="只给 AI 配置表（每项功能能选接口 / 本机命令行、有哪些命令行），不读账本")

    p = sub.add_parser("clean", help="清洗分享文案里的小红书链接（跟随短链、只留 xsec_token/source），输出 JSON")
    p.add_argument("text", help="一整段分享文案或链接")

    p = sub.add_parser("delete", help="移动收藏到回收站，并屏蔽后续同步")
    p.add_argument("item_ids", nargs="+", help="一个或多个 item_id")

    p = sub.add_parser('trash', help='恢复、彻底删除、清空回收站，或解除已删记录的屏蔽（重新导入用）')
    p.add_argument('action', choices=['restore', 'purge', 'empty', 'forget'])
    p.add_argument('item_ids', nargs='*')

    p = sub.add_parser("tidy-comments", help="去掉旧笔记里纯链接的自动 cmt1 留言")

    p = sub.add_parser("sync-schedule", help="看/改每晚收藏巡检的周期（Windows 计划任务 XhsFavSync）")
    p.add_argument("--set", choices=["daily", "weekly", "off"], help="改成每天/每周/关闭；不给就只报当前")
    p.add_argument("--at", help="时间 HH:mm（如 04:00 / 22:30）；配合 --set daily/weekly")
    p.add_argument("--day", help="周几（Monday…Sunday）；配合 --set weekly")
    p.add_argument("--rules", help='10-03 灵活定时：规则 JSON，如 [{"kind":"weekly","days":["Monday"],"times":["08:00"]},'
                                   '{"kind":"hourly","hours":4}]；kind = once / daily / weekly / hourly（每 1–6 小时）')
    g = p.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true",
                   help="注册每天跑 nightly 的计划任务 LinkBrainNightly（--at 时间，默认 04:00；--vault 收藏库）")
    g.add_argument("--uninstall", action="store_true", help="删掉计划任务 LinkBrainNightly")
    p.add_argument("--vault", help="配合 --install：夜跑用的收藏库（默认当前生效的收藏库）")

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

    from . import problems as problems_mod
    problems_mod.add_parser(sub)

    from .remote import cli as remote_cli
    remote_cli.add_parser(sub)
    from . import pickfolder
    pickfolder.add_parser(sub)
    from . import connect as connect_mod
    connect_mod.add_parser(sub)
    from . import keyprobe as keyprobe_mod
    keyprobe_mod.add_parser(sub)

    from . import nightly as nightly_mod, reader_install, report as report_mod
    nightly_mod.add_parser(sub)
    from . import night_captcha as night_captcha_mod
    night_captcha_mod.add_parser(sub)  # 1011 夜里撞验证：冷却后自查一次
    reader_install.add_parser(sub)
    report_mod.add_parser(sub)
    from . import synclog as synclog_mod
    synclog_mod.add_parser(sub)
    from . import setup as setup_mod
    setup_mod.add_parser(sub)
    # 批次 D · L5：恢复这篇 / 单篇导出 / 按标签连播
    from . import note_print, playlist as playlist_mod, restore as restore_mod
    restore_mod.add_parser(sub)
    note_print.add_parser(sub)
    playlist_mod.add_parser(sub)

    p = sub.add_parser("chatter-report", help="1015：全库评论里多少被判成水话（机读版略去）、有没有误伤；只读，结果另存 _archive/chatter-report.json")
    p.add_argument("--samples", type=int, default=20, help="可能误伤的例子最多列几条")
    p.add_argument("--json", action="store_true", help="最后一行输出 JSON")

    p = sub.add_parser("highlight", help="给一篇笔记正文加/去一处高亮（<mark>，持久到重渲染）")
    p.add_argument("target", help="item_id")
    p.add_argument("phrase", nargs="+", help="要高亮的原文片段（原样、含标点，需在正文里出现过）；可以给几段，一次写盘")
    p.add_argument("--remove", action="store_true", help="去掉这几处高亮")
    p.add_argument("--color", default=None, choices=["yellow", "green", "blue", "pink", "purple"],
                   help="颜色（默认黄）；已经划过的给个不同颜色 = 换色")
    p.add_argument("--json", action="store_true", help="最后一行输出 JSON（插件用）")

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

    from . import accounts, storage, synclog
    code = EXIT_ERROR
    try:
        code = _dispatch(args)
        if code == EXIT_OK:
            _resolve_crash(args.command)
        return code
    except accounts.AccountBusyError as exc:
        print(f"没跑：{exc}", file=sys.stderr)
        code = EXIT_ACCOUNT_BUSY
        return code
    except storage.LockBusy as exc:
        # 跨入口文件锁（目录重建等）等满了还拿不到：stderr 最后一行给人看的原因（CONVENTIONS §1.1）
        print(f"没跑完：{exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - 最后一道兜底：子命令漏出来的未知异常
        return _crashed(args.command, exc)
    finally:
        # 10-03 同步记录：这一步攒下的结果并进这次同步那行（sync-log.jsonl）；插件「立即同步」自己开的那次收尾
        if args.command != "synclog":
            synclog.finish_command(args.command, args, code)


def _crashed(command: str, exc: Exception) -> int:
    """子命令抛了没接住的异常：Traceback 进 stderr，登记一条 TRANSIENT.STEP_CRASHED（step=cli.<子命令>），
    stdout 最后一行是 §1 的 outcome JSON，stderr 最后一行是给人看的原因，退出码 1（CONVENTIONS §1.1 / §1.2）。"""
    import traceback

    from . import problems, read
    from .errtext import errtext
    reason = errtext(exc)
    traceback.print_exc(file=sys.stderr)
    step = f"cli.{command}"
    try:
        problems.report(step if problems._valid_step(step) else "cli.unknown", "TRANSIENT.STEP_CRASHED",
                        f"{command} 中途出错：{reason}")
    except Exception as rexc:  # noqa: BLE001 - 登记失败也要把 JSON 吐出来
        print(f"[cli] 问题记录没写上（{errtext(rexc)}）", file=sys.stderr)
    read.dump_json(read.outcome({}, ok=False, code="TRANSIENT.STEP_CRASHED", message=f"{command} 中途出错：{reason}"))
    print(f"没跑完：{reason}", file=sys.stderr)
    return EXIT_ERROR


def _resolve_crash(command: str) -> None:
    """这个子命令这次跑通了：之前兜底登记的崩溃标已解决（没有就什么都不写）。"""
    try:
        from . import problems
        problems.resolve(f"cli.{command}", None, "TRANSIENT.STEP_CRASHED")
    except Exception:  # noqa: BLE001 - resolve 自己不抛；这里再兜一层，收尾不能把成功变失败
        pass


def _account_lock(args, owner: str, on_wait=None):
    from . import accounts
    return accounts.account_session(owner, wait_s=float(getattr(args, "wait_lock_min", 2) or 0) * 60, on_wait=on_wait)


def _dispatch(args) -> int:
    if args.command == 'watch':
        from . import watch
        return watch.run(args)

    if args.command == 'crawl':
        from . import crawl
        return crawl.run(args)

    if args.command == 'mcp':
        from . import mcp_server
        return mcp_server.main()

    if args.command == 'problems':
        from . import problems
        if getattr(args, "problems_cmd", None) in ("list", "repair"):
            # 1017：精细识图放弃不再算故障——面板读取 / 自愈轮之前把以前登记的那些行收成已解决（幂等）
            try:
                from . import vision
                vision.retire_refine_problems()
            except Exception as exc:  # noqa: BLE001 - 收旧行是顺手的事，出错不能挡住面板
                from .errtext import errtext
                print(f"[problems] 收旧的精细识图行没做完（{errtext(exc)}），先照常列问题", file=sys.stderr)
        return problems.run(args)
    if args.command == 'remote':
        from .remote import cli as remote_cli
        return remote_cli.run(args)
    if args.command == 'pick-folder':
        from . import pickfolder
        return pickfolder.run(args)
    if args.command == 'connect':
        from . import connect as connect_mod
        return connect_mod.run(args)
    if args.command == 'keys':
        from . import keyprobe as keyprobe_mod
        return keyprobe_mod.run(args)
    if args.command == 'nightly':
        from . import nightly
        return nightly.run(args)
    if args.command == 'captcha-recover':
        from . import night_captcha
        return night_captcha.run(args)
    if args.command == 'reader':
        from . import reader_install
        return reader_install.run(args)
    if args.command == 'report':
        from . import report
        return report.run(args)
    if args.command == 'synclog':
        from . import synclog
        return synclog.run(args)
    if args.command == 'setup':
        from . import setup as setup_mod
        return setup_mod.run(args)
    if args.command == 'doctor':
        from . import doctor
        return doctor.run(args)
    if args.command == 'transcribe':
        from . import voice
        return voice.run(args)
    if args.command == 'vision':
        from . import vision
        if getattr(args, "refine", False):
            return vision.run_refine(args)
        if getattr(args, "refine_mark", None):
            return vision.run_refine_mark(args)
        return vision.run_upgrade(args)
    if args.command == 'note-verify':
        from . import restricted
        return restricted.run_verify(args)
    if args.command == 'comments':
        from . import ingest
        if getattr(args, 'fill_pending', False) or getattr(args, 'fill_status', False):
            return ingest.run_comments(args)  # 1009：补跑每篇自己拿账号锁（不整晚攥着）；进度只读本地
        # 1010：--progress（插件「抓全部评论」）——等号、读评论区、下评论图、写进笔记，一步一个进度事件（最后一行照旧是结果）
        emit = ingest.progress_emitter(args)
        if emit is None:
            with _account_lock(args, "comments"):
                return ingest.run_comments(args)
        emit("start", "准备抓这篇的全部评论")
        from . import accounts
        try:
            with _account_lock(args, "comments", on_wait=ingest.lock_wait_reporter(emit, getattr(args, "wait_lock_min", 2))):
                return ingest.run_comments(args)
        except accounts.AccountBusyError as exc:
            # 等满了还没轮到：最后一行给插件一句人话（不然插件拿到的最后一行是进度事件，只能按退出码瞎猜「在跑别的任务」）
            from .read import dump_json, outcome
            mins = float(getattr(args, "wait_lock_min", 2) or 0)
            dump_json(outcome({"results": []}, ok=False, code="BUSY",
                              message=f"号一直被「{ingest.owner_text(exc.holder)}」占着，等了 {mins:.0f} 分钟没轮到：过一会儿再点"))
            print(f"没跑：{exc}", file=sys.stderr)
            return EXIT_ACCOUNT_BUSY
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

        with _account_lock(args, "ingest"):
            return ingest_mod.run(args)

    if args.command == "enrich":
        from . import enrich as enrich_mod

        return enrich_mod.run(args)

    if args.command == "prune-comments":
        from . import comments as comments_mod

        print(json.dumps(comments_mod.prune_actor(args.actor, dry_run=args.dry_run), ensure_ascii=False))
        return 0

    if args.command == "relabel":
        from . import provenance

        rows = provenance.relabel(args.items, actor=args.actor, origin=args.origin, project=args.project)
        print(json.dumps({"items": rows}, ensure_ascii=False))
        return 0 if all(r["status"] == "ok" for r in rows) else 1

    if args.command == "catch":
        from . import catch as catch_mod

        return catch_mod.run(args)

    if args.command == "read":
        from . import read as read_mod

        return read_mod.run(args)

    if args.command == "search":
        from . import read as read_mod

        return read_mod.run_search(args)

    if args.command == "browse":
        from . import mcp_tools

        return mcp_tools.run_browse(args)

    if args.command == "albums":
        from . import albums as albums_mod

        return albums_mod.run(args)

    if args.command == "item":
        from . import mcp_tools

        return mcp_tools.run_item(args)

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
        if getattr(args, "note_command", None) in ("notify", "reply"):
            from . import mention as mention_mod

            return mention_mod.run(args)
        from . import note as note_mod

        return note_mod.run(args)

    if args.command == "pdf2md":
        from . import pdftext as pdftext_mod

        return pdftext_mod.run(args)

    if args.command == "render":
        from . import render as render_mod

        return render_mod.run(args)

    if args.command == "chatter-report":
        from . import agentmd
        r = agentmd.chatter_report(samples=args.samples)
        print(r["message"], file=sys.stderr)
        if args.json:
            from .read import dump_json
            dump_json(r)
        else:
            print(r["message"])
            for x in r["samples"]:
                print(f"  {x['item']} {x['floor']}：{x['text']}")
        return EXIT_OK

    if args.command == "highlight":
        from . import render as render_mod

        r = render_mod.set_highlights(args.target, list(args.phrase), remove=args.remove, color=getattr(args, "color", None))
        verb = "去掉高亮" if args.remove else "加高亮"
        n = len(r["changed"])
        if args.json:
            from .read import dump_json
            if n:
                message = ("已取消 %d 处" if args.remove else "已划 %d 处") % n
            elif r["already"] and not r["missing"]:
                message = "这几处已经划过了"
            else:
                message = "没找到这段原文"
            results = ([{"phrase": x, "status": "ok"} for x in r["changed"]]
                       + [{"phrase": x, "status": "already"} for x in r["already"]]
                       + [{"phrase": x, "status": "missing"} for x in r["missing"]])
            dump_json({"ok": bool(n), "code": "", "message": message, "item_id": args.target,
                       "changed": r["changed"], "missing": r["missing"], "already": r["already"], "results": results})
        else:
            print(f"{verb}：{'已改 %d 处' % n if n else '未找到该片段 / 无变化'} · {r['visible']}")
        return EXIT_OK if n else 1

    if args.command == "sync-favorites":
        from . import favorites as favorites_mod

        return favorites_mod.run(args)

    if args.command == "export-bundle":
        from . import export_bundle
        return export_bundle.run(args)

    if args.command == "restore":
        from . import restore as restore_mod
        return restore_mod.run(args)

    if args.command == "export-note":
        from . import note_print
        return note_print.run(args)

    if args.command == "playlist":
        from . import playlist as playlist_mod
        return playlist_mod.run(args)

    if args.command == "catalog":
        from . import catalog as catalog_mod

        return catalog_mod.run(args)

    if args.command == "index":
        from . import indextree
        return indextree.run(args)

    if args.command == "wiki":
        from . import wiki as wiki_mod
        return wiki_mod.run(args)

    if args.command == "skills":
        from . import skills as skills_mod
        return skills_mod.run(args)

    if args.command == "ask":
        from . import ask as ask_mod

        return ask_mod.run(args)

    if args.command == "selftest":
        from . import ask as ask_mod

        return ask_mod.run_selftest(args)

    if args.command == "usage":
        from . import usage as usage_mod

        return usage_mod.run(args)

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

        if getattr(args, "install", False) or getattr(args, "uninstall", False):
            return sync_schedule_mod.run_install(args)
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
