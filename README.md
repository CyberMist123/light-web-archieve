# light-web-archieve

把小红书链接归档成**不可变的原始快照** + **一篇给人看的 Obsidian 笔记**。

不是爬虫项目：小红书读取全部走本机已经跑着的 [xiaohongshu-mcp](http://127.0.0.1:18060/mcp)，
图片理解走本机 `media.py`（RapidOCR + qwen flash）。本仓库只负责"接住、归一化、落盘、渲染、索引"。

## 现在能做什么

| 能力 | 状态 |
|---|---|
| `python -m link_brain --help` / 子命令骨架 | ✅ Lot 0 |
| 数据格式规范 `docs/FORMAT.md` | ✅ Lot 0 |
| 小红书链接 → 不可变 RAW（正文/图片/评论） | ✅ Lot 1 |
| SQLite 索引 + 去重 + 版本比对 | ⬜ Lot 2 |
| Obsidian 可见笔记 + AI 版渲染 | ⬜ Lot 3 |
| 小模型摘要/标签/外链推荐 | ⬜ Lot 4 |
| 留言层 / 戳一下 / 收件箱 | ⬜ Lot 5 |
| 收藏同步 | ⬜ Lot 6（可选） |

当前真实进度以 `docs/STATE.md` 为准。

## 用法

```bash
python -m link_brain --help
python -m link_brain ingest "https://xhslink.cn/o/xxxxxxxx" --origin cli --note "顺手存的"
```

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
