# Current State

current_lot: 3b-ui
last_verified_commit: 4d795474839800b8aacc16f811a057040c3b8405

## 已真实通过

### Lot 0
- CLI 骨架、FORMAT、公开仓库忽略规则已完成。

### Lot 1
- 小红书 URL/短链/分享文本 → MCP → 不可变 RAW；正文、图片、评论、视频封面等已落盘。

### Lot 2
- SQLite 去重、HIT、refresh、read/search/reindex 已完成。

### Lot 3
- vision OCR、单篇人类 Obsidian note、derived/agent.md、rerender 保留手写 comments 层已完成。

### Lot 3b / Issue #2：Obsidian 人类版 UI
- `render.py` 输出 `lb-cols / lb-carousel / lb-detail / lb-comments / lb-replies` HTML 结构。
- `render.py` 每次 render 都同步受管 `link_brain.css` 到 vault snippet，避免旧 CSS 一直不更新。
- Owner 实机发现 Reading View 专用 selector 导致 Live Preview 下：多图纵向堆、正文不成两栏、link-brain markers 露出。
- 已修：Reading View + Live Preview 都适用 `.xhs-note` 样式；按当前 note pane 宽度自动双栏/单栏；carousel 强制一屏一图横滑；Live Preview 隐藏 marker 行；支持时 hover 出现左右 scroll button。
- Owner 最新评论区要求已落地：评论不显示日期/地点/总评论数量；正文使用 `Kaiti SC / STKaiti / KaiTi / 楷体` fallback；评论者名字灰色弱化；楼中楼缩进减少、竖线改为淡灰轻线。
- 相关提交：`d4ac50f083bfa90758e42d62111940fe19491246`（comment render）`35bec184e7314e7887a26418d1dfdb85015ab0db`（comment CSS）`91ec7cc6f2626d6e8246828bb7057a7fd31d191e`（UI tests）。
- 尚需 Owner 本机 `git pull` + `pytest` + `render --all` 后重新截图验收；此处不能声称已在 Owner Obsidian 真机通过。

## 已知缺口

- 评论图 MCP 当前结构没有媒体字段；V1 不额外自建抓取。
- 附件只能从正文线索标记 unavailable。
- `inbox / resolve / comment / sync-favorites` 尚未完成。
- Lot 4 小模型派生尚未开始。

## 下一步

先完成 Issue #2 的 Owner 实机 UI 验收，再继续 Lot 4。
