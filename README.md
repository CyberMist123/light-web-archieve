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
| **Obsidian 人类版响应式小红书详情页：宽 pane 左图右文、hover 左右切图/页码、稳定彩色头像、作者 badge、复杂楼中楼、独立评论滚动；窄 pane/手机自动单栏** | ✅ UI 返工 |
| 小模型摘要/标签/外链推荐 | ⬜ Lot 4 |
| 留言层 / 戳一下 / 收件箱 | ⬜ Lot 5 |
| 收藏同步 | ⬜ Lot 6（可选） |

当前真实进度以 `docs/STATE.md` 为准。

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

人类版使用 `cssclasses: [link-brain, xhs-note]`。宽 note pane 时左图右文：图片横向 `scroll-snap`，鼠标移入媒体区才出现灰底页码和左右切图按钮；右侧正文保持不动，评论区独立上下滚动。pane 变窄、桌面打开侧栏或手机端时自动切回自然单栏。

原站评论只保留阅读真正需要的信息：**不显示评论日期、地点或总评论数量**；评论者名字用灰色弱化，正文优先使用楷体；每个评论者按 `user_id/昵称` 生成稳定彩色头像。同一作者每次颜色一致，楼主回复复用帖子作者头像并显示 `作者` badge；楼中楼递归渲染，用轻缩进 + 淡竖线表示层级。话题标签显示成小红书式行内 `#tag`，不做胶囊。

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
- `docs/STATE.md` — 当前进度

## 测试

```bash
python -m pytest -q
```
