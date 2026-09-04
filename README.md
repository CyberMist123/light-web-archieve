# light-web-archieve

把小红书链接归档成**不可变的原始快照** + **一篇给人看的 Obsidian 笔记**。

不是爬虫项目：小红书读取全部走本机已经跑着的 [xiaohongshu-mcp](http://127.0.0.1:18060/mcp)，
图片理解走本机 `media.py`（RapidOCR + qwen flash）。本仓库只负责“接住、归一化、落盘、渲染、索引”。

## 现在能做什么

| 能力 | 状态 |
|---|---|
| `python -m link_brain --help` / 子命令骨架 | ✅ Lot 0 |
| 数据格式规范 `docs/FORMAT.md` | ✅ Lot 0 |
| 小红书链接 → 不可变 RAW（正文/图片/评论） | ✅ Lot 1 |
| SQLite 索引 + 去重（HIT 不重抓）+ `--refresh` 版本比对 | ✅ Lot 2 |
| `read` / `search` / `reindex` | ✅ Lot 2 |
| 图片 OCR（`derived/vision.json`）+ Obsidian 可见笔记 + AI 版渲染（`derived/agent.md`） | ✅ Lot 3 |
| `render` 子命令、`read --brief/--full`、`search` 一行格式 | ✅ Lot 3 |
| **Obsidian 人类版响应式小红书详情页：宽 pane 左图右文、窄 pane / 手机自动单栏、横向切图、轻量楼中楼评论树、行内话题标签** | ✅ UI 稳定基线 |
| 笔记附件：元数据（走笔记网页版，游客可达）+ **字节下载**（`attachments` 子命令，要小号登录态） | ✅ |
| 小模型摘要/标签/外链推荐（`derived/extracted.json`、`docs/BENCH.md`） | ✅ Lot 4 |
| **给主模型的摘要通路**：`catch "<消息全文>"` 一条 JSON、`read --brief/--full --json`、`search --json` | ✅ |
| 留言层 / 戳一下 / 收件箱 | ⬜ Lot 5 |
| 收藏同步 | ⬜ Lot 6（可选） |

当前真实进度与 UI 取舍以 `docs/STATE.md` 为准。

## 用法

```bash
python -m link_brain --help
python -m link_brain ingest "https://xhslink.cn/o/xxxxxxxx" --origin cli --note "顺手存的"
python -m link_brain ingest "<同一条链接>"               # 第二次命中索引，打印 HIT，不联网不重抓
python -m link_brain ingest "<同一条链接>" --refresh     # 重抓，内容无变化不产生新 RAW 版本
python -m link_brain read xhs-<note_id>                   # 打印 meta.json
python -m link_brain search "关键词"                     # 按标题/正文 LIKE 查询
python -m link_brain reindex                              # 从已有 raw/ 回填 index.db，不重抓
python -m link_brain render xhs-<note_id>                 # 拼可见笔记 + derived/agent.md（先跑图片 OCR）
python -m link_brain render --all                         # 对索引里所有对象重渲染一遍（幂等）
python -m link_brain read xhs-<note_id> --brief           # 标题 + 正文前120字，≤5行
python -m link_brain read xhs-<note_id> --full            # 打印整个 derived/agent.md
python -m link_brain render --all --extract               # 缺 extracted.json 才调小模型（Lot 4）
python -m link_brain render xhs-<note_id> --re-extract    # 强制重调小模型，覆盖旧结果
python -m link_brain attachments xhs-<note_id>            # 下载笔记附件字节（开浏览器，见下）
python -m link_brain attachments --all                    # 所有有附件的对象都下一遍
python -m link_brain catch "<聊天消息全文>" --origin tg    # 给主模型：自己找链接、归档、只打一个 JSON
python -m link_brain read xhs-<note_id> --brief --json    # 同一份 JSON 结构，给主模型查已归档的
python -m link_brain search "关键词" --json               # 查本地索引，机器可读
```

`ingest` 归档成功后会自动跑一遍 vision + render；`vault\Web\Xiaohongshu\<标题>.md` 是人唯一要看的文件（撞名才带 `__<id8>` 后缀），
`<!-- link-brain:comments:start/end -->` 里的留言层手写内容 rerender 不会被覆盖，只有 `<!-- link-brain:content:start/end -->` 里的正文/图片/评论会被重写。

人类版使用 `cssclasses: [link-brain, xhs-note]`。宽 note pane 时左图右文；pane 变窄、桌面打开侧栏或手机端时自动切单栏。图片不做缩略图墙，而是在媒体区横向 `scroll-snap`。

当前 UI 以**稳定阅读**为优先：顶部作者保持简单圆点 + 作者名，不显示作者 badge；原站评论不显示日期、地点或总评论数量，评论者名字灰色弱化，评论正文优先使用楷体，楼中楼用轻缩进 + 淡竖线表示层级；话题标签显示为小红书式行内 `#标签`，不使用胶囊底色。

图片切换暂不依赖自定义按钮、radio 或网页跳转；这类 Obsidian 交互实验曾在实机出现错误，当前以横向滚动 / 触控滑动为稳定方案。详情见 `docs/STATE.md`。

`render` 会把仓库内 `link_brain/assets/link-brain.css` **同步**到 `vault/.obsidian/snippets/link-brain.css`，因此 UI 更新会跟随 rerender 生效。第一次使用时，Owner 仍需在 Obsidian 设置 → 外观 → CSS 片段里打开一次 `link-brain` 开关。

### 笔记附件

小红书的「笔记文件」MCP 完全不返回。`ingest` 会顺手 GET 一次笔记网页版，从
`__INITIAL_STATE__...note.relatedFile` 拿到**元数据**（文件名 / `doc_id` / 页数 / 下载数）——
这一步**游客可达**，不用登录。

**字节**要登录才给，而且下载接口带签名头，所以本仓不复刻签名，直接让浏览器去点那个下载按钮：

```bash
python -m link_brain attachments xhs-<note_id>
```

前提（只需配一次）：agent-browser 的 profile（`C:\\Users\\18717\\Tools\\agent-browser\\profile`）
里登录**另一个小红书小号**——**不能用主号**，主号在 18060 的 MCP 那侧，两边同时在线会互相顶掉。
其余的（headed 模式、关掉“每次都问保存位置”、进程树超时）代码里都处理了，细节见
`docs/POC-xiaohongshu.md` 第 4b 节。

字节落对象级 `_archive/<source>/<id>/attachments/`，**不进已封存的 `raw/vNNNN/`**；
下完，笔记顶上那行附件会从“未下载”变成指向本地文件的链接。

笔记最上面是一条灰色小字：`原文 · 机读版 · 附件`（原网址、`derived/agent.md`、附件文件）。
它必须在正文 HTML 块**外面**、并且用 Obsidian 自己的链接形式（`[…](http)` / `[[vault 路径]]`）：
裸 HTML 里的 `<a href="../../_archive/…">` Obsidian 一律当外部 URL，本地文件点不开
（2026-09-04 Owner 实机踩到），和 Lot 3b「原图链接放 HTML 块外面」是同一个坑。

### 给主模型的摘要通路（`catch`）

TG / CMX / CC 端的主模型不需要懂这个仓库，Bash 直调一条命令就行（**不起 HTTP 服务、不起 MCP 服务**）：

```bash
python -m link_brain catch "<她发来的整条消息>" --origin tg --actor human
```

它自己从消息里找小红书链接（`xiaohongshu.com` / `xhslink.cn` / `xhslink.com`），
有就归档（命中索引就是 `hit`，不联网不重抓），**stdout 只有一行 JSON**，日志全走 stderr：

```json
{"found": 1, "items": [{"item_id": "xhs-…", "status": "new", "title": "…", "summary": "…", "tags": ["…"], "kind": "image", "visible_note": "D:\\LIGHT WEB ARCHIEVE\\vault\\Web\\Xiaohongshu\\….md", "agent_md": "D:\\LIGHT WEB ARCHIEVE\\vault\\_archive\\xiaohongshu\\…\\derived\\agent.md", "attachments": {"status": "downloaded", "items": []}, "url": "https://…"}]}
```

- 没有链接 → `{"found": 0, "items": []}`，零成本、不碰网络，调用方一眼判断要不要展开。
- 整条消息会当留言 cmt1 写进可见笔记（**只在第一次归档时**，见 `docs/STATE.md` 已知缺口）。
- `summary` 用小模型概要，没有就退回正文前 120 字；想顺手花钱生成加 `--extract`。
- 路径都是绝对路径，调用方要细节就自己去读 `agent_md`。
- 字段表和 `read --json` / `search --json` 的结构在 `docs/FORMAT.md` §10。

### 小模型派生（Lot 4）

`render --extract` 会把「正文 + 图片 OCR + 带编号的评论」喂给 `media.py text`（默认 qwen3.7-flash），
拿回一份固定 JSON 落到 `derived/extracted.json`：概要、要点、标签、值得点开的链接、
有价值/是广告的评论。它只读本地文件，**不会重抓网页**；删掉 `extracted.json` 重跑就只是重新调一次模型。

- 概要和要点回填进 `derived/agent.md`，`read --brief` 优先用模型概要；抽取失败时写"（未生成）"，不阻断。
- 标签按 `docs/tag-vocab.yaml` 归一后并进可见 md 的 `tags:`。**只增不减**：原帖 hashtag、
  Owner 手写的 tag、frontmatter 里 Owner 自己加的键（`time` / `finder` / `comment` …）rerender 都原样保留。
- 模型输出一律当不可信数据：非 `http(s)` 的"链接"降级成线索文本、标签洗成 Obsidian 合法字符、
  正文/评论渲染前 HTML 转义。评论里写"忽略以上指令…"也只是普通文本。
- 模型 id 和价格在 `link_brain/assets/llm-config.yaml`，跑分见 `docs/BENCH.md`（首轮 5/5 一次成功，单条约 $0.000125）。

退出码：`0` 成功 / `1` 一般错误 / `2` 缺内容 gate（图片没下全）/ `3` 子命令未实现。

## 环境

- Windows + Python 3.14，PowerShell 7
- 依赖：`mcp` `httpx` `pyyaml` `pillow`；开发额外 `pytest`
- 小红书 MCP 守护：`Start-ScheduledTask XiaohongshuMCP`，在线自查 `check_login_status`
- vault 位置默认是仓库下的 `vault/`，可用环境变量 `LINK_BRAIN_VAULT` 覆盖

## 仓库是公开的

`vault/`、`.env`、`*.local.*` 全在 `.gitignore`。**任何 cookie / token / key / 抓下来的样本数据都不许进版本控制。**
commit 前跑一次 `git status` 核对。

## 文档

- `docs/TASKBOOK.md` — 唯一执行文档（做什么、验收标准、5 条样本）
- `docs/FORMAT.md` — 数据格式唯一真相
- `docs/POC-xiaohongshu.md` — 小红书 MCP 能拿到什么、拿不到什么
- `docs/STATE.md` — 当前进度、已回滚实验、下一步
- `docs/BENCH.md` — 小模型跑分（成功率 / token / 成本，Owner 填人工判定列）
- `docs/tag-vocab.yaml` — 标签归一词表

## 测试

```bash
python -m pytest -q
```
