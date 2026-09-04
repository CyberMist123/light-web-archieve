# Current State

current_lot: 4
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
- **字节还没拿到**：游客打开 `/file/<docId>` 显示「登录即可下载该文件」。见「下一步」。

## 已知缺口

- 图片左右箭头暂不作为稳定功能；当前主要用横向滚动 / 触控滑动切图。
- 复杂评论数据仍受 MCP 返回结构限制；V1 不为了 UI 自建额外小红书抓取器。
- 评论图如 MCP 未返回对应媒体字段则无法补抓。
- 附件**字节**还没下载（只有元数据）。要下必须有一个小红书登录态；Owner 已同意
  「给 agent-browser 另开一个小红书号」这条路（不能用主号，agent-browser 扫码会把
  18060 MCP 那侧顶下线，TG 端会掉线）。等号开好再接下载那一段。
- `inbox / resolve / comment / sync-favorites` 尚未完成。
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

1. **附件字节**：Owner 用 agent-browser 的 profile 开一个**新的**小红书号登录一次
   （`agent-browser close --all` → 普通 Chrome 带 `--user-data-dir=C:\Users\18717\Tools\agent-browser\profile`
   打开小红书 → 她本人扫码 → 关窗）。之后实现 `attachments` 下载：走 `/file/<docId>` 页面
   拿真实下载 URL → 落 `raw/vNNNN/attachments/` → `status="downloaded"`。
   **别用主号扫**（会顶掉 18060 MCP / TG 端）。
2. 给主模型的摘要通路（issue #41 第 17 节）：TG / CMX / CC 收到链接 → `ingest` →
   回 `item_id` + 极短概要 + 本地路径。目前只有 CLI，没有给主模型用的入口。
3. Lot 5（`comment / inbox / resolve` + `scripts/smoke.py`）——人和 AI 互相留言那层。
4. Issue #2 的 UI 仍欠 Owner 一次实机验收。
5. `docs/BENCH.md` 最后三列 Owner 说不做 20 条了，以后手工填，不再挡路。
