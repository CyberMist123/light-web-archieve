# 2026-10-11 网页版要验证才给看的笔记（分支 wt/restricted1011 + 读取组件 restricted1011）

## 入口
- 夜跑 / 后台：`comments --fill-pending [--until-done]`（评论补齐）、`attachments --all`（附件补下）、`attachments --recheck --logged-in-tail`（碰号补查）
- 插件：笔记页「现在抓全部评论」（`comments <id> --progress`）、评论区顶上「打开验证」、问题面板「打开验证」（都调 `note-verify <id> --wait`）
- 读取组件：`get_feed_detail`（MCP）/ `POST /api/v1/feeds/detail` / `POST /api/v1/attachments/download` / 新 `POST /api/v1/notes/search-token` / `POST /api/v1/verify/window`（带笔记）

## 步骤 · 预期 · 实测（本批全部在测试里做，没碰真号 / 真库 / 18061）

| # | 步骤 | 预期 | 实测 |
|---|---|---|---|
| 1 | 本机假站点（localbrowser，临时 profile、死代理）打开一页没有详情容器、页面状态里没有这篇的「限制页」 | `NOTE_RESTRICTED`，不写熔断，落证据，< 90 秒（不白滚评论） | ✅ `TestLocalBrowserRestrictedNote` |
| 2 | 同上但页面有看得见的验证浮层 / 有登录框 | 照旧 `CAPTCHA_REQUIRED` / `NOT_LOGGED_IN`（写熔断，不放宽） | ✅ 同上 |
| 3 | 全量 localbrowser（root + xiaohongshu） | 旧用例全绿（读收藏 / 评论楼层 / 风控探针 / 验证窗口） | ✅ 87 s / 587 s |
| 4 | 补评论撞 `NOTE_RESTRICTED`，假搜索搜到新口令 | 搜一次（先 pace）→ 歇 LWA_FETCH_REST → 新口令开一次 → 补上、清标记 | ✅ pytest |
| 5 | 搜不到 | 一篇一条 `note.restricted`（不推送），不算「没进展」、不报 COMMENTS_INCOMPLETE；后台再跑 0 次开页；当天不再搜 | ✅ pytest |
| 6 | 附件页撞 `NOTE_RESTRICTED` | 不进 3 次循环（旧口令 1 次 + 新口令 1 次），不进跨夜退避、不报「附件没下好」；之后跳过 | ✅ pytest |
| 7 | 「打开验证」过了 / 没过 / 号在熔断中 / 旧读取组件 | 过了：清标记、记窗口口令、续读清零、附件退避清掉、拉起后台补评论（隔 45 分钟）；没过：照实说、留着；熔断：先走熔断验证；旧组件：说要更新 | ✅ pytest + node（`test_note_restricted_1011.cjs`） |

## 体验预算（RELEASE-BAR §2）
- 「用户点的每一个操作有明确结果」：打开验证结束提示照 Python 的 message（过了 / 没看到这篇 / 号要处理 / 窗口没开成 / 组件旧）。
- 页面：笔记页只多一行字 + 一个链接式按钮（沿用 `.lb-act` 样式），不新增重绘。

## 待她：一步（真机，部署读取组件之后）
1. 打开一篇「网页版要验证」的笔记（问题面板「网页版要验证」那一行点「查看」），点评论区顶上的「打开验证」，在弹出的小红书窗口里过完验证、看到笔记内容后关窗——
   看提示是不是「过了，这篇能打开了…」，45 分钟后评论区那一行是不是没了、评论补上了。
2. 如果窗口里根本没有验证、笔记直接就显示了：也关窗（会判「过了」）；如果一直要验证过不去：提示会说「再点一次」，把截图发主审。
3. 主审另核：第一晚夜跑后 `~/.link-brain/risk-evidence/<时间>/meta.json` 里 `trigger=note_restricted` 的几份——这批页面到底长什么样（判法是推测的：
   「页面上没有这篇、也没有看得见的验证」）；如果出现大量 `NOT_LOGGED_IN` 熔断而号其实没掉，说明这类页面带登录框，要回来改判法。
