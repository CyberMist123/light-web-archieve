# 「开始」页向导：前后端契约（第 7 批）

她要的效果（10-03，参照 MAA 初始设置）：一个页面里解决。左边 = 功能勾选清单（每项标磁盘 / 内存占用、带齿轮跳到详细设置，底部合计）；右边 = 分步指引（上一步 / 下一步，竖排步骤 ①–⑤）。先给不要付费 key 的本地方案，再提示建议的 API + 每 100 篇估算价格；有「轻量版（不要任何 key）」；CapsWriter 也要一键安装；**一次检查装好，之后不用她再回来补装**。

步骤：① 选功能 → ② 一键检查并安装 → ③ 登录（扫码）→ ④ 同步设置（每天几点 / 每天上限 / 图片·视频·评论·附件 + 补跑进度与预计天数）→ ⑤ AI（选填：建议接口 + 每 100 篇价格 + 填 key + 「试问一句」）。走完「开始」页收成总览（每步 ✓ + 修改）。其余分页：同步与内容 / AI / 远程阅读 / 高级（同一份设置，细调用）。

## 后端 CLI（全部输出 CONVENTIONS §1 形状：{ok, code, message, ...}，退出码与 ok 一致）

### `python -m link_brain setup plan`
```jsonc
{"ok":true,"code":"","message":"",
 "components":[
   {"id":"core","name":"归档·同步·浏览·关键词搜索","desc":"…","required":true,"default":true,
    "needs_key":false,"local":true,"disk_mb":120,"ram_mb":300,"installed":true,"status":"ready",
    "detail":"…","depends":[],"settings_tab":"sync"},
   {"id":"ocr","name":"本地 OCR（图片里的字）","required":false,"default":true,"needs_key":false,"local":true,
    "disk_mb":…,"ram_mb":…,"installed":…,"status":"ready|missing|partial|unknown","detail":"…","depends":["core"],"settings_tab":"ai"},
   {"id":"asr","name":"本地语音识别（CapsWriter，视频转写 / 语音提问）", …, "default":true, "depends":["core"]},
   {"id":"capslock","name":"CapsLock 语音输入", …, "default":true, "depends":["asr"]},
   {"id":"ai_text","name":"AI 问答 · 概要 · 打标（要 API key）","needs_key":true,"local":false,"default":false, …},
   {"id":"ai_vision","name":"识图（要 API key）","needs_key":true,"default":false, …},
   {"id":"reader","name":"读取组件（读小红书收藏 / 评论 / 附件）","required":true, …},
   {"id":"dataview","name":"Dataview（目录页显示用，Obsidian 插件）","required":true,"check_only":true, …},
   {"id":"remote","name":"远程阅读（MCP，高级，要自备域名）","default":false,"later":true, …}],
 "presets":{"light":["core","reader","dataview","ocr"],"recommended":["core","reader","dataview","ocr","asr","capslock","ai_text"],"full":[…全部…]},
 "totals_basis":"磁盘 / 内存是估计值：<怎么算的>"}
```
- disk_mb / ram_mb：实测或有出处的估计（本机已装的组件量真实占用；没装的按官方包大小 / 模型大小），写清 `basis`。
- 选中状态由前端存插件设置 `setup.selected`（id 数组）；后端不存。

### `python -m link_brain setup check [--components a,b,…]`
`{"ok":bool, "results":[{"item_id":"ocr","status":"ready|missing|partial|failed","code":"","error":"","detail":"…","fix":"auto|manual","fix_hint":"…"}]}` —— 只检查不改东西；`fix:"auto"` 表示 `setup install` 能装。

### `python -m link_brain setup install --component <id>`
边跑边往 stdout 打一行一个 JSON 进度事件：`{"type":"progress","component":"asr","phase":"下载|校验|解压|下载模型|验证","done":12345,"total":67890,"text":"…"}`，最后一行 `{"type":"result", ...§1 形状..., "status":"ready|failed"}`。装完自己再 `check` 一遍，结果写进 result。可中断（Ctrl+C / 插件 killTree），中断后再装能续或从头干净重来，不留半截。
- core：缺的 Python 依赖（按 pyproject）——若后端就是装好的包则 ready。
- ocr：本地 OCR 模型（现有 RapidOCR 档位，见 `link_brain/visual.py` / ai_config）。
- asr：CapsWriter-Offline 一键安装（下载官方发布包 + 模型到用户目录、校验、写好插件设置里的地址 / 端口、能启动服务端并自检）。发布地址 / 校验和 / 大小以官方 GitHub Release 为准，查到写进常量并注明出处和日期；查不到就留空并 `fix:"manual"` 给指引，不编。
- reader：调现有 `reader install`（发布地址空时如实 manual）。
- dataview：check_only（前端负责打开社区插件页）。

### `python -m link_brain setup estimate [--posts 100]`
```jsonc
{"ok":true,"posts":100,
 "basis":{"from_library":true,"sample":361,"avg_chars":…, "avg_images":…, "avg_video_min":…},
 "items":[
   {"id":"summary","name":"概要 + 打标","provider":"DeepSeek","model":"…","yuan":0.8,"per":"100 篇","how":"…"},
   {"id":"vision","name":"识图","provider":"通义千问","model":"…","yuan":…, …},
   {"id":"video","name":"视频转写（用 API 时；本地 CapsWriter 免费）","yuan":…, …},
   {"id":"ask","name":"问答（每问一次）","yuan":…, "per":"次"}],
 "prices":{"as_of":"2026-10-03","sources":["<官方定价页 URL>",…]},
 "local_free":["ocr","asr"]}
```
- 价格表放 `link_brain/pricing.json`（模型 → 输入 / 输出单价、图片 / 分钟单价、出处 URL、核对日期），可被用户配置覆盖；按她库里的实际平均量（字数、图片数、视频分钟）估算，库空就用默认典型值并 `from_library:false`。

### `python -m link_brain setup backfill`
`{"ok":true,"favorites_total":1159,"archived":361,"deferred":798,"daily_limit":50,"days_left":16,"as_of":"…"}`（数据来自 sync-status / problems-summary / 索引；缺就 null）。

## 前端
- 插件设置页改成**上方分页**：开始 / 同步与内容 / AI / 远程阅读 / 高级（现有「更多」里的东西按类归入，**一项不删**；`tests/test_settings_layout.cjs` 的「一项不少」清单继续守住）。
- 「开始」页 = 左功能清单（预设按钮：轻量版 / 推荐 / 全部；每项勾选框 + 名称 + 磁盘 / 内存 + 齿轮跳到对应分页；底部合计）+ 右分步指引（①–⑤，上一步 / 下一步，竖排步骤条）。
- ② 一键检查并安装：逐项显示状态和进度条（读 install 的 progress 事件），失败如实给原因和重试；全部 ready 才算这步完成。
- ⑤ AI：先写「不填 key 也能用：归档、浏览、关键词搜索、本地 OCR、本地语音」；再列建议接口 + estimate 的每 100 篇价格（标价格日期）；填 key 后「试问一句」走真实问答（复用问收藏的 answerArchive），回答直接显示在这一步。
- 走完收成总览。首次引导 Modal（第 5 批 B2 的 onboarding-ui.js）改为直接打开设置页「开始」分页。
