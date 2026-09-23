# light-web-archieve

> 2026-09-23：来源支持原文证据定位与短暂高亮；问答/选帖可导出 Markdown＋可选原图 ZIP。星标统一在「星标收藏」查看，不再往根目录复制笔记。图片使用原有翻页，不额外加缩略图工具条；目录保持整页瀑布流。最新验收边界见 `docs/STATE.md`。

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

## 收藏搜索与 AI 对话

最新交互：卡片星标悬停显示，已收藏打开独立纯文本目录；卡片管理用右键。AI回答双击编辑，书签图标切换收藏；右上「已保存」查看。媒体右上图钉切换图片位置锁定；点击页码展开缩略图直跳，前后翻页支持循环。视频下方倍速按钮点击切换，左右拖动微调。更新后需重载 Link Brain Actions 与 Link Brain Native Media Nav。

2026-09-20：目录右上角 ☆ 与正文底部收藏共用状态，收藏自动排前；支持已收藏、视频、附件筛选，顶栏和搜索分类固定，只有卡片区滚动。
目录 `/问题` 进入统一问答页。输入和追问留在底部；点击回答中的 `[来源N]` 或含引用的段落，在右侧原生阅读栏打开整篇；参考材料的「上下对照」在右侧下方打开第二篇。右栏图片、作者正文、评论上下排列，可独立滚动，分隔线可拖宽。
「已保存」位于右上角，支持个人笔记和编辑已保存内容；回答支持编辑、保存、带来源与本地绝对路径复制。来源里可展开命中原文，区分作者正文、评论、OCR、附件和转写。
快捷键：Obsidian 设置 → 快捷键 → 搜索「跳转目录并搜索收藏」，自行绑定喜欢的组合键。
部署后重新加载 Link Brain Actions，再重开目录／收藏搜索页。浏览器验证不等于原生 Obsidian 分栏和视频验收。

部署插件时将 `obsidian-plugins/link-brain-actions/` 中的 `manifest.json`、`main.js`、`library-ui.js` 一起复制到 vault 的同名插件目录。

目录页输入普通文字，按 Enter 搜索；输入 `/问题`，按 Enter 获取 AI 回答，下方可继续追问。
顶栏「浏览收藏 / 问收藏」切换两页；问收藏页直接输入问题即可，支持流式回答、复制/保存和展开来源。
纯「＋」打开导入网址/同步收藏夹；顶栏 `…` 管理分类、回收站、刷新目录。卡片右下 `…` 管理该条收藏。

搜索覆盖标题、标签、原文正文、已转换附件、视频转写、图片/评论图片 OCR、评论以及摘要。转写权重6；问答/Fable共用BM25排序和密集原文窗口。
权重依次为 12 / 10 / 7 / 6 / 5 / 3 / 2（作者 1），同义词匹配乘 0.75。
常用中英文词组来自 `link_brain/assets/search-aliases.json`，如音乐/music、菜谱/recipe；
单字“音”也能检索，结果会比“音乐”宽。普通搜索不调用模型，AI 回答使用已有文本 AI 配置。
不存在于本地的评论、图片 OCR 或尚未转换的文件内容无法被检索。

Claude Code / Codex 可直接在仓根调用，JSON 保留原文片段、命中字段、权重、完整 MD 路径：

```powershell
python -m link_brain search "music" --json
python -m link_brain ask "从收藏里整理咖喱鱼蛋的材料和步骤"
python -m link_brain read xhs-<note_id> --full --json
# 追问历史从 stdin 传入，避免写入命令行：
'[{"role":"user","content":"咖喱鱼蛋怎么做"}]' | python -m link_brain ask "需要烤箱吗" --history-stdin
```

Python 接口为 `link_brain.retrieval.search(query, limit=20)` 和
`link_brain.ask.answer(question, history=None)`。返回的 `agent_md` 可继续读取完整正文，
机读版的「附件正文 Markdown」链接指向 `derived/attachments/<doc_id>.md`。
AI 可以组合材料；来源不足时说明缺口。引用只表示检索材料，仍可点击正文核对模型表述。

### Fable 只取材料（不调用模型）

```powershell
python -m link_brain retrieve "蒜香鱼片怎么做" --top-k 8
# Fluffy 的 tools/scripts/lwa.py：
python lwa.py --ask "蒜香鱼片怎么做" --json
python lwa.py --full xhs-<note_id> --json
```

返回标题、命中原文片段（全体≤2500字）、Obsidian/Web链接、附件/转写标志。Web链接沿用已有需要登录的WebDAV服务。Obsidian库名可用 `LINK_BRAIN_OBSIDIAN_VAULT` 覆盖。

问答常驻进程：`python -m link_brain serve --stdio`。stdin每行 `{"id":"1","question":"问题","history":[]}`，stdout回同id的start/delta/result，delta的text为增量；空闲10分钟退出。插件负责150秒超时与重启，不起HTTP服务。模型/实测边界见 `docs/BENCH.md`。

视频下载：`python -m link_brain videos --all`；本机转写：`python -m link_brain videos --transcribe <item_id>`，转写独立执行，不阻塞导入。

### 微信或其他渠道的调用封装

统一请求支持 `question`、`history`、`include`。默认 `include` 为空，只发送正文；
需要时指定 `links`、`files`。优先让渠道程序通过子进程 stdin 传 JSON，无需启动额外服务：

```json
{"question":"概括这份教程","history":[],"include":["links","files"]}
```

```powershell
python -m link_brain ask --request-stdin
# 或现成命令行形式：
python -m link_brain ask "概括这份教程" --include links --include files
```

响应中 `delivery` 是渠道应发送的内容：

```json
{
  "status":"ok",
  "delivery":{
    "body":"回答正文，已去掉供本地 UI 使用的来源编号",
    "links":[{"title":"原文标题","url":"https://…","source_id":"xhs-…","markdown_path":"本机完整MD路径"}],
    "files":[{"name":"教程.pdf","path":"本机文件绝对路径","mime_type":"application/pdf","bytes":1234,"source_id":"xhs-…","markdown_path":"转换后的MD路径"}]
  },
  "history":[{"role":"user","content":"问题"},{"role":"assistant","content":"回答"}]
}
```

未请求 `links/files` 时不会出现对应字段。链接和文件从实际归档材料生成，优先使用回答引用的材料；
不存在的文件不会作为附件返回，`files: []` 表示没有可发送文件。渠道可把 `history` 原样用于下一次请求。
渠道发送器只发送 `delivery.body`，按需逐项发链接、读取 `files[].path` 上传；不要把本机路径当网页地址发给用户。
`status:error` 需要显示失败而不是当成回答。`sources`、`matches` 等是内部检索信息。
Python 调用同样支持 `answer(question, history=..., include=["links", "files"])`。
这次提供调用与返回契约，不包含微信登录或消息发送器。

## 附件下载与挂载

点目录的待补标识，或右键收藏 →「下载 / 挂本地文件」。支持拖入、文件选择器、
默认 Downloads 目录中的推荐文件；文件夹和等待时长可在插件设置修改。
「打开原网页，等待下载」使用本地浏览器，监听新下载且同名的完整文件，稳定后自动挂载；
不同名文件需点选推荐或拖入。结束/超时会提示关闭网页，不关闭用户的其他浏览器标签。

挂载后自动转换 PDF/DOCX、重渲染并更新搜索。转换失败与字节缺失分别报告。
`attachments --all` 优先查配置目录中的同名文件，再走现有浏览器自动下载；
下载失败也清理自动浏览器。`attachments --audit` 输出逐文件完整性，含待确认附件线索。
多附件必须全部存在才显示已下载。夜间脚本保留附件失败退出码，设置可查看上次运行和下次时间。

## 用法

```bash
python -m link_brain --help
python -m link_brain ingest "https://xhslink.cn/o/xxxxxxxx" --origin cli --note "顺手存的"
python -m link_brain ingest "<同一条链接>"               # 第二次命中索引，打印 HIT，不联网不重抓
python -m link_brain ingest "<同一条链接>" --refresh     # 重抓，内容无变化不产生新 RAW 版本
python -m link_brain read xhs-<note_id>                   # 打印 meta.json
python -m link_brain search "关键词"                     # 按字段权重检索
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

### 收藏目录（封面瀑布流）

`python -m link_brain catalog` 重写两样：`vault/_archive/catalog-data.json`（纯程序拼的数据）和 `vault/小红书收藏目录.md`（一段 dataviewjs 页面，读那份数据渲染封面瀑布流、点标签加/减筛选、搜索）。每晚同步后自动跑。

**首次一次性设置**：Obsidian 装社区插件 **Dataview**，并在它的设置里打开 **Enable JavaScript Queries**。没装 / 没开时，目录页显示的是 dataviewjs 源码而不是卡片墙。页面样式由 dataviewjs 自注入，不需要额外开 CSS 片段。

### 收藏墙与检索（2026-09-16）

目录顶部「+ 导入链接」打开弹窗，支持粘贴多条链接或分享文案；清洗去重后逐条入库，当前支持小红书。可切换「今日新增」。卡片显示归档时点赞数，顶部显示目录生成时间。
普通搜索支持拼音近似和漏字；`#AI #记忆` 按标签 OR 查询；`/问题` 打开未来的 AI 回答界面（目前未接服务）。后续在 Link Brain Actions 插件实现 `answerArchive({question, items})` 返回回答文本，页面即可调用。

打开「小红书收藏目录」：无标签的自适应封面墙，显示标题、作者和日期，悬停看摘要。
搜索支持正文、概要、标题、后台标签的多关键词、非连续文字与英文单字符拼写近似；按相关程度排序。这是本地文字匹配，不是 AI 语义检索。
右键卡片可编辑标签（逗号分隔），直接保存笔记的 `tags` 属性；也可由 Obsidian 属性栏或其他属性编辑插件修改。主动清空和删除的标签不会在重渲染时复活。已有标签以用户保存的值为准，小模型仍可生成建议，但不自动覆盖已有属性。
当前收集入口仍为小红书；卡片数据已携带来源，其他软件的实际导入尚未接入。

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

退出码：`0` 成功 / `1` 一般错误 / `2` 缺内容 gate（图片没下全）/ `3` 子命令未实现 /
`5` 要人处理（登录态失效、风控验证码、18060 的 MCP 挂了）——**批量看到 5 就停车**。

`5` 同时会报一次警：`LINK_BRAIN_ALERT_CMD` 指向一条外部命令（stdin 收 UTF-8 JSON），
本仓库不含任何推送地址/key，细节见 `docs/FORMAT.md` §9。

## 环境

- Windows + Python 3.14，PowerShell 7
- 依赖：`mcp` `httpx` `pyyaml` `pillow`；开发额外 `pytest`
- 小红书 MCP 守护：`Start-ScheduledTask XiaohongshuMCP`，在线自查 `check_login_status`
- vault 位置默认是仓库下的 `vault/`，可用环境变量 `LINK_BRAIN_VAULT` 覆盖

### 本机依赖与环境变量（开源移植看这里）

代码里凡是指向作者本机的绝对路径，都是「环境变量覆盖 + 作者本机兜底」——别人 clone 下来，
把下面这些指到自己的东西即可，不改代码：

| 环境变量 | 覆盖什么 | 不设时的默认 |
|---|---|---|
| `LINK_BRAIN_VAULT` | vault 根目录 | 仓库下 `vault/` |
| `LINK_BRAIN_MEDIA_PY` | 便宜的文本/识图脚本 `media.py`（`llm.py` / `vision.py`） | 作者本机路径 |
| `DASHSCOPE_API_KEY` | media.py 用的千问 key | media.py 读仓库外 CSV |
| `LINK_BRAIN_FAVDUMP` / `XHS_FAV_HOST` / `XHS_FAV_PROFILE` | 私密收藏读取器 favdump.exe 及其 profile（`favorites.py`） | 作者本机 `.xiaohongshu-mcp` |
| `LINK_BRAIN_AB_PROFILE_PREFS` | 附件下载用的 **agent-browser 小号登录 profile** 的 Preferences（`attachments.py`） | 作者本机 agent-browser profile |

**浏览器登录**（附件字节、私密收藏）本就依赖本机 agent-browser / favdump 的登录态，
是可选的重活；不配这两条也不影响归档主体、目录、检索、问答。

### AI 接口（问答 / 摘要 / 识图 / TTS）

配置在 Obsidian 插件 **Link Brain Actions 的设置页**，只落 `vault/.obsidian/plugins/link-brain-actions/data.json`
（`vault/` 已 gitignore，**key 绝不进仓、绝不打印**）。两种通路：

- **本机 media.py（默认）**：复用作者本机已配置的便宜通路，无需在插件里填 key。
- **自定义 HTTP**：没有 media.py 的用户填自己的 OpenAI 兼容 endpoint/model/key 即可（文本走 `/chat/completions`、TTS 走 `/audio/speech`）。

摘要提示词接 `llm.py` 抽取流程、识图通路接 `vision.py`、`/问AI` 走 `python -m link_brain ask`
（读整个本地 `catalog-data.json` 重新检索，只把挑出的少量片段送模型，token 控制全在这一步）。
每条接口在设置页都有「测试」按钮，发一次最小真实调用验证是否接通。

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

## 许可

[MIT](LICENSE) © CyberMist
