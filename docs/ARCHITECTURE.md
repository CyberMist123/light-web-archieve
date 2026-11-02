# ARCHITECTURE — 一页看懂 light-web-archieve（Link Brain）

给第一次打开这个仓库的人。规则细节在 `docs/CONVENTIONS.md`，数据格式在 `docs/FORMAT.md`，发布标准在 `docs/RELEASE-BAR.md`。
`docs/STATE.md`、`docs/TASKBOOK.md`、`docs/ARCH-AUDIT.md` 是给 AI 编码助手看的施工日志和排查记录，不是入门读物。

## 它是什么

一个 Obsidian 插件 + 一个 Python 包 + 一个本机读取服务。把小红书收藏整篇存进你自己的 vault（原文、图、视频、评论、附件），
把图里的字、视频里的话、附件全文变成可搜索的文字，然后能「问收藏」并带出处作答。数据全在本地；不配任何 AI key 也能归档、浏览、搜索。

## 五层

| 层 | 在哪 | 做什么 | 不做什么 |
|---|---|---|---|
| **入口** | `obsidian-plugins/link-brain-actions/`（插件）· `link_brain/cli.py`（命令行）· `link_brain/mcp_server.py` + `remote/`（给别的 AI 用的 MCP）· `link_brain/nightly.py`（夜跑） | 收用户 / 定时器 / 外部 AI 的请求，交给用例层；把结果显示出来 | 不自己算真相：插件只显示后端给的状态（`catalog-data.schema` 对不上就提示，不猜着画） |
| **用例** | `ingest.py`（链接 → 归档）· `sources/xiaohongshu/favorites.py`（同步收藏）· `catalog.py`（目录页数据）· `ask.py` + `recall_*`（问收藏）· `remove.py` / `restore.py`（回收站）· `enrich.py` / `vision.py` / `videos.py` / `pdftext.py`（补处理） | 一个用户动作一个模块，按顺序调规则层和外部能力 | 不直接碰网络和模型，不自己写文件格式 |
| **规则** | `domain.py`（身份 item_id / 在库判断 / 收藏口径 / meta 字段归属，1025 第二波 PR①）· `problems.py`（唯一问题记录与故障码）· `pricing.py`（价格）· `provenance.py`（谁收的，判断转发自 domain）· `sources/xiaohongshu/fav_counts.py`（篇数口径）· `sources/xiaohongshu/accounts.py`（一个号一个会话）· `errtext.py`（异常 → 人话） | 全仓只此一份的判断：怎么算钱、怎么算篇数、什么叫「我的收藏」、出错怎么分类 | 守卫测试（`tests/test_guards.py`，基线 `tests/guards-baseline.json`）保证别处不再抄一份 |
| **外部能力** | `providers.py`（配置 → 执行器的唯一入口）· `text_stream.py` / `llm.py`（文本模型）· `asr.py` · `docconv.py` · `rerank.py` · `sources/`（来源接口 + 注册表）· `sources/xiaohongshu/adapter.py`（读取服务的客户端） | 模型、OCR、语音、文档转换、小红书读取。每种能力一个接口，缺了就如实返回「没配 / 没装」 | 模型输出和网页内容一律当不可信数据（`mdsafe.py` 清洗） |
| **数据** | `storage.py`（路径、原子写、文件锁）· `index.py`（SQLite 索引 + 删除屏蔽）· `synclog.py` / `usage.py` / `actionlog.py`（账本） | 真相文件只追加或原子重写；派生文件随时可以删掉重建 | 不在锁外改别人会压实的文件 |

## 进程模型

- **页面怎么画出来**（1102 起不要 Dataview）：目录 / 星标 / 问收藏 / Wiki / 回收站 / B 站挑选这几张页，和每篇笔记底部的批注块，
  md 里都只有一小段 ` ```lb-page ` 代码块（脚本名 + 几行 JSON 参数，`catalog._page_bootstrap()` / `render.annotate_block()` 生成）。
  插件在 `onload` 里 `registerMarkdownCodeBlockProcessor('lb-page', …)`（`page-host.js`）：找仓根 → 读（同一版本复用已编译的）
  `_archive/<页面脚本>`（`catalog-page.js` 等，`catalog build` 由 `link_brain/assets/lb-page-lib.js` + 各 view 拼出来）→ 给一个和 Dataview 同样大小的
  `dv`（容器、component、`current()`）跑起来；库里 `.md` 变了 2.5 秒防抖重跑（和 Dataview 一样，页面靠 `reuseDom` 原样挂回旧 DOM）。
  载入核心只有一份（`page-bootstrap.js` 的 `lb-page-core`，插件里是 `tools/sync_tokens.py` 拷的逐字副本）。
  **同一个插件手机上也装**（manifest `isDesktopOnly: false`）：手机上 `onload` 只注册这个处理器、把 `note.css` 注入 head，不加命令 / 设置页、不起进程；
  页面在手机上看到的 `LB.provider()` 是 null，走原来的手机只读路（要插件的按钮不画，或点了说「手机上只能看…」）。
  兜底：不想在手机上装 LWA 插件的，`pageBlock` 改成 `dataviewjs`（或环境变量 `LINK_BRAIN_PAGE_BLOCK`），下次 `catalog` 重建换回旧写法、靠手机上的 Dataview 显示。
- **插件 main.js 是构建产物**：源是 `main.src.js`，`npm run build`（`tools/build_plugin.cjs`）用 esbuild 把 `page-host.js` 打成 IIFE（全局名 `LBPageHost`）放在前面、
  `main.src.js` 原样跟在后面。手机上只加载 main.js 一个文件，所以手机要用的代码必须打进去；桌面上其余几个 ui 文件照旧在运行时按路径加载。
  `path` / `fs` / `child_process` 都是用到时才加载（手机上没有）。CI 跑 `npm run build:check`，main.js 不是最新构建就红。
- **插件拉 Python**：插件只有一个起进程入口 `spawnPy`，每次调用 `python -m link_brain <子命令> --json`，**只认 stdout 最后一行 JSON**（`{ok, code, message, …}`）；stderr 最后一行是人话原因。长任务互斥（同一时刻一个），轻量调用并行。
- **Python 拉读取服务**：所有要登录小红书的操作经本机 HTTP 服务 `link-brain-reader`（`reader/` 里的 Go 补丁版 xiaohongshu-mcp，默认端口 18061）。它**不是任何 Python 的子进程**（经短命中转拉起），所以杀 Python 进程树不会杀掉浏览器会话；一个号只有一个浏览器 profile，操作串行。
- **夜跑**：`python -m link_brain nightly` 按步骤顺序起子进程（同步收藏 → 补附件 → 补评论 → 概要 / 打标 → 识图 → 转写 → 向量 → 目录），每步带时限，超时只杀这一步；碰号的步骤一旦撞风控 / 掉登录（退出码 5）后面碰号的全跳过。Windows 上由计划任务 `LinkBrainNightly` 触发，插件设置里开关。
- **跨入口并发**：命令行、插件、夜跑、MCP 可能同时写同一份文件，靠 `storage.file_lock(name)` 文件锁，等不到就抛 `LockBusy`、由调用方如实报；只有问题记录这类账本等不到锁时写旁路再并回，不丢记录。
- **退出码**：0 成功 / 部分完成 · 1 出错 · 2 缺内容 · 5 号要人处理 · 6 号被占用（`cli.py` 开头）。

## 真相文件 vs 派生文件

vault 里 `_archive/` 下的文件分两类。真相文件丢了就是丢了（备份它们）；派生文件删掉后下次构建会重建。

| 真相（备份、只追加 / 原子写） | 从哪来 | 派生（可删、会重建） | 由谁重建 |
|---|---|---|---|
| `xiaohongshu/<id>/raw/vNNNN/`（source.json、manifest.json、原始 assets） | 归档，**写完不再改** | `xiaohongshu/<id>/derived/`（agent.md、vision.json、extracted.json、previews） | `enrich` / `vision` / `render` |
| `xiaohongshu/<id>/meta.json`、`notes.json`（批注）、`comments.jsonl`（留言层） | 归档、用户操作 | `index.db`（SQLite 索引，含 tombstones 缓存表） | `index` 重建 / 每次 `connect` 对齐 |
| `tombstones.jsonl`（删除屏蔽事件） | 回收站 | `catalog-data.json`、`index-data.json`、`trash-data.json`、`fonts/`、页面脚本 `*-page.js` / `annotate-view.js`、`page-blocks.json` | `catalog build` |
| `problems.jsonl` + `problems.pending/`（问题记录） | 各步骤 `problems.report` | `problems-summary.json` | `problems` 每次写成功后 |
| `sync-log.jsonl`、`usage/YYYY-MM.jsonl`、`post-tags-history.jsonl` | 同步、调模型、改标签 | `semantic.db`、`topic-vectors.json`、`query-expand-cache.json` | `embed` / `index catch-up` |
| 库根 `索引.md`（用户写的分类树）、`albums.json`、`topics.json`、`selections` | 用户 | `index-ai.json`、`index-suggestions.json` | `indexai` |
| 可见笔记 `Web/Xiaohongshu/*.md` 的批注区 | 用户 | 可见笔记的正文区（标记对之间） | `render` |

配置的唯一来源：插件 `data.json`（AI 接口、远程阅读、Python 路径），在 vault 的 `.obsidian/plugins/link-brain-actions/` 下；账号登录态与读取服务状态在 `~/.link-brain/`，不在 vault 里。

## 怎么改它

1. 先读 `docs/RELEASE-BAR.md` 第 3 节「完成定义」和 `docs/CONVENTIONS.md`。
2. 新的判断只写一处（规则层），别处调它；守卫测试会拦住抄本。
3. 后端产生的每个新状态都要写清用户在哪里看到它。
4. 跑 `python -m pytest -q` 和 `node tests/run-node.cjs --unit`；页面改动再跑 `npm run test:ui`（要 playwright）。
