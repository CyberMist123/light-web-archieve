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
| 小模型摘要/标签/外链推荐 | ⬜ Lot 4 |
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
```

`ingest` 归档成功后会自动跑一遍 vision + render；`vault\Web\Xiaohongshu\<标题>__<id8>.md` 是人唯一要看的文件，
`<!-- link-brain:comments:start/end -->` 里的留言层手写内容 rerender 不会被覆盖，只有 `<!-- link-brain:content:start/end -->` 里的正文/图片/评论会被重写。

人类版使用 `cssclasses: [link-brain, xhs-note]`。宽 note pane 时左图右文；pane 变窄、桌面打开侧栏或手机端时自动切单栏。图片不做缩略图墙，而是在媒体区横向 `scroll-snap`。

当前 UI 以**稳定阅读**为优先：顶部作者保持简单圆点 + 作者名，不显示作者 badge；原站评论不显示日期、地点或总评论数量，评论者名字灰色弱化，评论正文优先使用楷体，楼中楼用轻缩进 + 淡竖线表示层级；话题标签显示为小红书式行内 `#标签`，不使用胶囊底色。

图片切换暂不依赖自定义按钮、radio 或网页跳转；这类 Obsidian 交互实验曾在实机出现错误，当前以横向滚动 / 触控滑动为稳定方案。详情见 `docs/STATE.md`。

`render` 会把仓库内 `link_brain/assets/link-brain.css` **同步**到 `vault/.obsidian/snippets/link-brain.css`，因此 UI 更新会跟随 rerender 生效。第一次使用时，Owner 仍需在 Obsidian 设置 → 外观 → CSS 片段里打开一次 `link-brain` 开关。

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

## 测试

```bash
python -m pytest -q
```
