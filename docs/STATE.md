# Current State

current_lot: 3b-ui
current_main: e80245a60d7c01044fc8d70cea508ffea5ec02e4
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

## 已知缺口

- 图片左右箭头暂不作为稳定功能；当前主要用横向滚动 / 触控滑动切图。
- 复杂评论数据仍受 MCP 返回结构限制；V1 不为了 UI 自建额外小红书抓取器。
- 评论图如 MCP 未返回对应媒体字段则无法补抓。
- 附件只能从正文线索标记 `unavailable`。
- `inbox / resolve / comment / sync-favorites` 尚未完成。
- Lot 4 小模型派生尚未开始。
- Owner Windows 上 Git 已安装，但普通 PowerShell 的 PATH 仍可能找不到 `git`；必要时临时使用 `C:\Program Files\Git\cmd\git.exe`。

## 下一步

1. Owner `git pull` + `python -m link_brain render --all`，确认回滚后的稳定 UI 已恢复。
2. Issue #2 只做小幅视觉修正，不再加入高风险图片交互。
3. 人类版稳定后继续 Lot 4。
