# Current State

current_lot: 4
current_main: 5330cbb  # catch + 报警 + 实机反馈那批（docs 提交在它后面）
repo_path: D:\LIGHT WEB ARCHIEVE

## 已真实通过

### Lot 0
- CLI 骨架、FORMAT、公开仓库忽略规则已完成。

### Lot 1
- 小红书 URL/短链/分享文本 → MCP → 不可变 RAW；正文、图片、评论、视频封面等已落盘。

### Lot 2
- SQLite 去重、HIT、refresh、read/search/reindex 已完成。

### Lot 3
- vision OCR、单篇人类 Obsidian note、`derived/agent.md`、rerender 保留手写 comments 层已完成。

### Lot 3b / Issue #2：Obsidian 人类版 UI
当前以 **稳定、可读的人类版** 为准，不继续堆交互实验。

当前保留：
- 宽 note pane：左图右文；pane 变窄、桌面侧栏挤压或手机端：自动单栏。
- 多图：一屏一张的横向 `scroll-snap`，不做缩略图墙。
- 顶部作者：恢复早期简单的紫色圆点 + 作者名，不显示作者 badge，不给每个评论人生成彩色头像。
- 原站评论：不显示日期、地点、总评论数量；评论人名灰色弱化；评论正文优先楷体；楼中楼用轻缩进 + 淡竖线。
- 标签：保留小红书式行内 `#话题`，不使用胶囊底色。
- Reading View + Live Preview 都应用 `.xhs-note` 样式；机器 metadata 与 marker 行继续隐藏。
- `render` 会同步仓库 `link_brain/assets/link-brain.css` 到 vault snippet，避免本地旧 CSS 不更新。

### 本轮明确回滚 / 暂不做
以下实验在 Obsidian 实机上产生错误或体验变差，已经从当前 `main` 撤掉，不应被后续实现误认为当前需求：
- radio/label 图片切页控制。
- 用页内 anchor 实现的左右箭头跳转。
- 双击图片打开小红书网页。
- 帖子作者 `作者` badge。
- 每个评论人的随机/哈希彩色头像。
- 评论区独立滚动、图片/正文强制固定的实验布局。

原因：箭头/切图在 Obsidian 中出现错误跳转，双击外链也受 Obsidian/小红书网页行为影响。当前优先恢复稳定阅读体验。

当前恢复基线来自 `a1f6f3b36a8a69796811f59371238fcd96b109dd` 的 UI 状态；`main` 在此基础上只保留小红书式行内标签，当前提交为 `e80245a60d7c01044fc8d70cea508ffea5ec02e4`。

### Lot 4：小模型派生
- `llm.py`：正文 + 图片 OCR + 带编号评论 → `media.py text`（qwen3.7-flash）→ 固定 JSON →
  schema 校验（失败重试 1 次）→ `derived/extracted.json`。只读本地文件，不重抓网页。
- 概要 / 要点回填 `derived/agent.md`；`read --brief` 优先用模型概要；抽取失败写"（未生成）"，不阻断。
- 标签按 `docs/tag-vocab.yaml`（20 个常用词）归一后并进可见 md 的 `tags:`，**只增不减**。
- 顺手补的两个数据保护：可见 md 的 frontmatter 改用 YAML 解析（Obsidian 会把 `tags: [a, b]`
  改写成块状列表，旧的正则版本读不到、会把 Owner 手写 tag 弄丢）；非 `cssclasses/tags/link_brain`
  的键当作 Owner 手写，rerender 原样保留。
- 模型输出全程当不可信数据：非 http(s) 的"链接"降级成线索、标签只留 Obsidian 合法字符、
  评论编号必须在输入里出现过、渲染前 HTML 转义。`tests/test_llm.py` 里有端到端注入用例。
- 模型 id / 价格在 `link_brain/assets/llm-config.yaml`（不写死在代码里）。
- 5 条样本实跑：JSON 一次成功 5/5，单条平均估算成本 $0.000125，见 `docs/BENCH.md`。
  D 条（原帖没有裸 URL）确实被点出了 `Yinglianchun/Ombre-Brain`。

### 附件（2026-09-04，Owner 点名的最高优先级）
- **元数据这一半做完了，游客可达、没动登录态。** 笔记网页版 SSR 的
  `__INITIAL_STATE__...note.relatedFile` 有 `docId` / 名字 / 页数 / 下载数，MCP 不返回它。
  `ingest` 现在顺手 GET 一次笔记页（`xhs.fetch_related_file`），结果落 `raw/vNNNN/web_raw.json`，
  写成 `attachments[].status="metadata_only"`，人看的笔记里出现一行 📎 卡片，agent.md 的「外链」也带上。
- 顺带修掉了老启发式的误报：网页探测成功且没有 `relatedFile` = 这篇确实没挂文件；
  但页面 200 却没有这条笔记（登录墙/已删/占位页）算探测失败，退回正文线索。
- 样本 A 已 `--refresh` 出 `v0002`（v0001 字节不变），`附件=metadata_only`，
  拿到 `p模式教程-机教版.pdf` / 19 页 / docId `7658854832003020032`。
- **字节也拿到了（2026-09-04 当天打通）**：`python -m link_brain attachments <item_id>` 用
  agent-browser 的小号登录态开 headed 浏览器点下载，字节落对象级 `attachments/`，
  写 `attachments.json`（doc_id / sha256 / 大小），`meta.attachments_status=downloaded`，
  可见 md 的 📎 变成指向本地文件。**`raw/vNNNN/` 一个字节不动。**
- 样本 A 实测：`p模式教程-机教版.pdf` 1,436,001 字节，自动下的 sha256 与手工点击下载完全一致。
- 踩到并记进 `docs/POC-xiaohongshu.md` 第 4b 节的坑：headless 下载 POST 会挂死（必须 headed）、
  Chrome“问保存位置”会让自动点击变成取消、`open <url>` 在登录态小红书页面永不返回、
  Windows 上 `subprocess.run(capture_output, timeout)` 杀不掉 `.cmd` 的子孙进程会假超时。

### 给主模型的摘要通路（2026-09-04，STATE 上一版「下一步 1」）
- `catch "<消息全文>" --origin tg|cmx|cc --actor human`：自己从消息里找小红书链接
  （`xhs.URL_RE` + host 白名单 `xiaohongshu.com`/`xhslink.cn`/`xhslink.com`）→ 逐条 `ingest`
  （命中索引就是 HIT，不联网）→ **stdout 只有一行 JSON**，日志全在 stderr。
  没链接就是 `{"found": 0, "items": []}`，零成本。同一篇在一条消息里出现两次只算一条。
- item 字段：`item_id / status(new|hit|error) / title / summary / tags / kind /
  visible_note / agent_md / attachments / url`，路径全是绝对路径。整条消息当 `--note` 传下去。
  `summary` 用 `derived/extracted.json` 的小模型概要，没有退回正文前 120 字（`--extract` 才花钱调模型）。
- 一条链接抓挂了只让那条变成 `status=error`（带 `error` 文本），其余照常，退出码 1、JSON 照样打全。
- 顺手加了 `read --brief --json`（同一份 item 结构，没有 status 键）、`read --full --json`
  （带整篇 agent.md 的 `markdown`）、`search --json`（只查 SQLite，所以 summary 是正文前 120 字）。
- **不做 HTTP / MCP 服务**（硬约束 8）：TG/CMX 就是 Bash 直调 CLI。结构写死在 `docs/FORMAT.md` §10。
- 机器可读输出走 `read.dump_json`，直接写 stdout 的 UTF-8 字节：Windows 控制台是 GBK，
  `print()` 碰到标题里的 emoji（如「无线水吧台‼️」）会 UnicodeEncodeError 让调用方拿到崩溃而不是 JSON。
  人看的那几条 print 也顺手降成 `errors="replace"`（在 `cli.main` 里），不改编码、中文照常。
- `tests/test_catch.py`：链接检测/白名单、无链接零成本、new→hit 不联网、一条消息两个同篇算一条、
  抓失败仍是合法 JSON、`--json` 三条通路。全套 78 个测试绿。

### 附件链接回归修复（2026-09-04，Owner 实机报的）
- 症状：上个版本的 📎 点得开，附件字节下下来之后点不开了。
- 真因：字节下下来后 href 从 `https://www.xiaohongshu.com/file/<docId>` 换成了本地相对路径，
  而**裸 HTML 里的 `<a href="../../_archive/…">` Obsidian 一律当外部 URL**，本地文件打不开。
  `<img src>` 能显示是另一条通路，别拿它当反证。跟 Lot 3b 第 2 条「原图链接要放 HTML 块外面」同一个坑。
- 修法：`render._attachments_md` 取代 `_attachments_html`，附件行改成 content 层里、
  HTML 容器**外面**的一行 Markdown——本地文件 `📎 [[_archive/…/attachments/x.pdf|x.pdf（19 页 · 已存本地）]]`，
  只有元数据的仍是普通 Markdown 链接指原站。5 篇已 `render --all` 重渲染过。
  **等 Owner 在 Obsidian 里点一下确认。**

### 评论区图片（Owner 问的）
- 现在拿不到，**不是解析漏了**：MCP `get_feed_detail` 返回的评论对象只有
  `id/noteId/content/likeCount/createTime/ipLocation/liked/userInfo/subCommentCount/subComments/showTags`，
  64 条评论里 `pictures`/`picture`/`image` 一个键都没有；全库 6 份 manifest 的 `comment_image` 数都是 0。
- 下载通路其实早写好了（`ingest.download_media` 认 `comment_image` role），数据源一给字段就自动下。
- 真要拿到只能照附件那条路：agent-browser 小号登录态开 headed 浏览器抓评论区（硬约束 10 允许）。
  是独立一个 Lot 的量，且会弹窗口打扰 Owner —— **等 Owner 点头再排**。

### Owner 实机反馈这一轮（2026-09-04 夜 → 09-05）
- **附件点不开**（她报的）：真因是裸 HTML 里的 `<a href="../../_archive/…">`——Obsidian 一律当外部
  URL，本地文件打不开；`<img src>` 能显示是另一条通路，别拿它当反证。现在附件/原文/机读版是
  content 层最上面一个 callout（`> [!link-brain-file]`，CSS `data-callout="link-brain-file"`），
  **必须在 HTML 容器外面**，本地文件用 `[[vault 路径]]`。
- 那条灰字长这样：`原文 · 机读版 · 附件`。「机读版」直接进 `derived/agent.md`（她说在 Obsidian 里
  看不到机读视角）。样式按她要求：**没有灰框、字是灰的**，不写 📎 字符，悬停才变强调色。
- **文件名去掉 `__<id8>`**（她原话「__080119fe 就这些别写」）。撞名才退回带后缀：判断读对方
  frontmatter 的 `link_brain.item_id`，Owner 手写的同名老文件绝不覆盖。同一对象有两份 md 时
  `merge_existing` 把 tag / 她手写的 frontmatter 键 / 留言层并起来再删旧的
  （`家克…` 那篇的 `time/finder/from/comment` 就是这么保住的）。
- **收藏链接的形状**：从主页/收藏页复制出来是 `/user/profile/<作者id>/<note_id>`，
  老正则一条都解不出来（前面那截是作者 id）。已加分支 + 回归测试。

### 报警：出事不许不知不觉挂着跑（2026-09-05）
- 三类分开：`AccountBlockedError`（登录态失效/验证码/限流）、`ServiceDownError`（18060 或它的
  浏览器起不来/连不上）、普通 `AdapterError`（这篇没了，批量继续）。前两类 → 退出码 **5** + 报警 + 停车。
- `link_brain/alert.py` 只认环境变量 `LINK_BRAIN_ALERT_CMD`（stdin 收 UTF-8 JSON），
  **公开仓里没有任何推送地址/key**。本机出口是 `cyberlink\Fluffy-SelfHood\tools\scripts\lwa-alert.py`
  = Bark（`bark.mjs`，key 在 `~/.bark/config.json`）+ TG（`tg-mirror.py --send --force`，
  末尾写「Fable 不用处理」）。两条都实测通过。
- anyio 把 `ConnectError` 包进 `ExceptionGroup`，`str()` 只剩「unhandled errors in a TaskGroup」——
  要 `xhs.flatten_exc` 摊开子异常才认得出"连不上 18060"。
- **18060 挂掉的真因是本机内存**，不是掉登录也不是风控：它每次调用都新开一个 Chrome，
  可用物理内存 <1G 时高发 `[launcher] Failed to get the debug url`（2026-09-04 夜实测：
  0.5–0.9G 时连挂 14 条）。所以 ingest 对 ServiceDown **先退避重试 3 次（20s/60s）** 再停车；
  批量脚本另加内存闸（<1.4G 就等）。重启服务只是治标。

### Owner 的 31 条收藏（2026-09-04 夜）
- 源文件 `C:\Users\18717\Downloads\_.md`，31 条去重后 31 篇。第一轮 17 篇成功落盘，
  14 篇卡在上面那个内存问题；补抓脚本带内存闸在等（会自己跑完再统一 `render --all --extract`）。
- 有附件（`metadata_only`）的 7 篇；只有 P 模式那篇的字节已经在本地。
- `vault/Web/Xiaohongshu/` 里有一个 `20260904-文档体系整理-裁决.md` 不是归档产物，是别的会话丢进来的
  cyberlink 文档，没敢动，等 Owner 处置。

### 2026-09-05 凌晨这一轮做完的
- 31 条收藏全部补抓完（30 篇落盘，`6a74946c…` 那条每次都在 MCP 侧 300s 超时，单独挂着）。
- 附件字节 10 个已下（含 4 个 .docx）；`pdf2md` 把 8 个 PDF 转成 `derived/attachments/<doc_id>.md`，
  坏字形全部 0%——只有子集化字体那份走了逐页 OCR，其余直接抽文字层。
- 原文链接带 `xsec_token`（裸 canonical 会 404，实测验过）；顶部灰字变成
  `原文 · 机读版 · 附件 · 全文`。
- **布局折腾了两轮最后回滚**：想把正文从 HTML 搬出来变 Markdown（为了能划 `==重点==`），
  试过 float、也试过把 grid 建到 sizer 上，Owner 实机两次都说更差，最后 `git checkout 62c9024`
  整体回到她认可的那版（`.lb-cols` 两栏 grid + 图片 sticky + 正文在 `.lb-detail` 里）。
  **教训写在这里，别再重蹈**：正文一旦是 Markdown，它在 DOM 里必然是 sizer 的直接子节点
  （Obsidian 遇空行闭合 HTML 块），两栏只能靠 sizer 级 grid / float 兜，视觉细节对不齐；
  真要划重点得走 `<mark>` 这条不碰布局的路。
  过程中量到两条硬知识：**元素响应不了自己的容器查询**（sizer 自己当容器时 display 改不动、
  子节点规则却生效）；老 `auto-fit(minmax(390px,1fr))` 在 795px 仍是两栏，断点别定在 700/800。

## 已知缺口

- 图片左右箭头暂不作为稳定功能；当前主要用横向滚动 / 触控滑动切图。
- 复杂评论数据仍受 MCP 返回结构限制；V1 不为了 UI 自建额外小红书抓取器。
- 评论图如 MCP 未返回对应媒体字段则无法补抓。
- 附件下载依赖 agent-browser profile 里的**小号登录态**；那个登录掉了就要重扫
  （主号绝不能扫这个 profile——会顶掉 18060 MCP / TG 端，2026-09-04 实际发生过一次）。
- 附件下载要开 headed 浏览器，会在屏幕上弹窗口，跑批量时会打扰 Owner。
- `inbox / resolve / comment / sync-favorites` 尚未完成。
- `catch` 只在**第一次**归档时把消息写成留言 cmt1；已经归档过的（HIT）那条消息只进 relations 表，
  不会追加到可见 md 的留言层——那是 Lot 5 `comment` 的活，等 Lot 5 一起接。
- 评论区图片全库为 0，MCP 不返回该字段（见上）。
- PDF 附件还没转成 md。通路是现成的（`media.py pdf`，本地 pymupdf + 扫描页走 CMX OCR），
  但实测 `p模式教程-机教版.pdf` 的文字层字形映射是坏的（人→⼈、：→9、括号→df，子集化字体），
  这类必须退回「页面渲成图 → OCR」。判据用康熙部首 / CJK 兼容区字符占比。
- 附件字节要 headed 浏览器，批量下会在屏幕上弹窗打扰 Owner；还没接进 ingest 自动跑。
- BENCH.md 的「漏正文 / 误删细节 / 广告当信息」三列还空着，等 Owner 人工判定；样本补到 20 条后要重跑。
- token 数是字符估算（`media.py text` 不回传 usage），只能横向比较，不是账单。
- 广告/噪音判定偏激进（C 条 19 条评论标了 12 条噪音）；只影响 agent.md 标注，不删内容。
- 小红书原 hashtag 里带空格的（如 `Operit AI`）仍原样写进 `tags:`，Obsidian 认不了这种 tag；
  只清洗了小模型给的标签，没动原帖的（改原帖 hashtag 会动到 Owner 已有的文件）。
- `vault/Web/Xiaohongshu/家克喜欢催人，我将用魔法打败魔法.md`（没有 `__<id8>` 后缀那个）是
  旧命名留下的重复文件，里面有 Owner 手写的 `time/finder/from/comment`。没敢动，等 Owner 决定
  是并进正式那篇还是删掉。
- Owner Windows 上 Git 已安装，但普通 PowerShell 的 PATH 仍可能找不到 `git`；必要时临时使用 `C:\Program Files\Git\cmd\git.exe`。

## 下一步

按这个顺序做，都不需要再问 Owner 要决定（她 2026-09-05 凌晨已经拍完板）。

1. **Lot 5 留言层**（主线最后一块）：`comment / inbox / resolve` + `scripts/smoke.py`；
   顺带把 `catch` 在 HIT 时把新消息追加成留言接上（现在只进 relations 表）。
2. **Lot 7 评论图补抓**（Owner 已批，规格见 `docs/TASKBOOK.md` Lot 7）：MCP 没有那个字段，
   走 agent-browser 小号登录态读页面 DOM 拿 URL、httpx 下字节，落**对象级** `comment-media/`，
   不碰已封存的 `raw/`。
3. **目录页**：vault 里一篇自动维护的索引 md——按标签/时间列全部笔记，一行一条
   （标题链接 + 一行概要 + tags + 日期），`render --all` 时顺手重写，纯程序拼、不过模型。
4. **docx → 文本**：4 个附件是 .docx，`pdf2md` 只吃 PDF。通路加进
   `Fluffy-SelfHood/tools/scripts/media.py`（硬约束 3：不自研，和 pdf 一条路），再让 `pdf2md` 认 .docx。
5. **Lot 6 收藏同步**（Owner 已批：两个号都能给 AI 用）：先花十分钟试
   `get_my_profile(tab="fav")`，能走通就不用她扫码；走不通再谈第二个 MCP 实例。
6. **附件自动接线**：ingest 发现 `metadata_only` 就自动下一次字节；批量用 `--no-browser` 跳过 +
   结尾汇总缺哪几篇。
7. **高亮**（等 Owner 说做才做）：唯一可行的是 `<mark>` 这条**不碰布局**的路——给一条命令把她选中的
   句子写进 content 层，rerender 时按原文匹配贴回去。**不要**再为了高亮去动两栏布局（今晚栽了两次）。
8. Issue #2 的 UI 实机验收：回滚之后再确认一次。
9. `docs/BENCH.md` 最后三列 Owner 说不做 20 条了，以后手工填，不再挡路。

### 明确不做 / 不用管（Owner 2026-09-05 拍板）
- `6a74946c…` 那条笔记每次抓都 300s 超时——**不用管**，别再花时间查。
- `vault/Web/Xiaohongshu/20260904-文档体系整理-裁决.md`（别的会话丢进来的 cyberlink 文档）
  ——**不用管**，别动它。
