# 设置页「功能」与一键装好 / 跑完：前后端契约

## 10-10 修订（她的裁决：恢复分栏，按「什么都不懂的新用户」重写；覆盖下面 10-09「一页」的布局部分）

她 10-10 的话：「原本的设置分栏还是需要的」——恢复成分栏（标签页），同时守住 10-09 的两条：**每个设置只出现在一处**；**装上自动跑轻量版、一键装好 / 跑完**（零配置首次、`setup run` 都不变）。

- **五栏**（`SETTING_TABS`，一次只画一栏；停在哪一栏记在插件对象 `settingsView.tab`，不写 data.json）：
  - **概览**：一句「装上就能用…」；小红书账号 · 收藏同步（状态 + 次要链接「立即同步」「改时间」）· 评论补齐（「现在补」）· 问题（「打开问题列表」）· 这台电脑（打开了的功能各自装好没有）；**这一栏唯一的主按钮「一键装好 / 跑完」**，进度就在按钮下面。
  - **收藏与同步**：收藏放在哪（只此一处）· 自动同步（定时编辑器就在这里；目录页「同步记录」里的弹窗是同一个组件）· 每天最多新收几篇 · 下载图片 / 视频 · **每篇评论抓几楼**（原「自动拉取」「手动拉取」合成一项，手动的差别是一行小字：某一篇要全部评论 = 那篇右上角 ⋮「抓全部评论」）· 登录后自动同步 · 批注署名 · 目录分类（折叠；10-10 起 = 索引.md：编辑索引 / AI 起草 / 未归类建议 / 重新整理目录 + 索引文件路径，原「名称: 关键词」文本框退场）。
  - **AI**：第一句「要不要 AI：不填也能用；填了多出 问收藏、自动概要、识图」→ 每个功能一个开关、旁边标价钱（本地 OCR / 本地语音 / CapsLock 说话 =「免费（本机跑）」；概要和打标签、识图、问收藏 = `setup estimate` 的「约 ¥x / 100 篇」「约 ¥x / 次」，估不出写「按用量」）→「去哪弄密钥、大概多少钱」（按服务商一行：价钱 +「去拿密钥」+「填上它的地址和模型」；密钥页面在 `pricing.json` 的 `providers.<名>.key_url`，estimate 原样带出）→ 打开了的那几项的接口地址 · 密钥 · 模型名 · 测试 →「全部关掉（密钥留着）」= 轻量版。本机那几样的开关显示「实际在用的」（选过，或装好了且设置里正开着）。
  - **连接其他 AI**：远程访问的东西全在这一栏（不再拆两处）——勾软件 → 本机的一键接上 / 撤销；网页版：远程访问开关 · 你的网址（**紧挨着「还没有网址？」**：① 有域名走 Cloudflare 隧道 ② 没有用 Tailscale Funnel）· 测一下外面能不能连上 · 连接地址 · 口令 · 几步做法 · 已经连上的（断开）；开放给 AI 的文件夹；最下面一个默认收起的「高级：端口、访问令牌、访问记录」（访问令牌只在这里，给不支持口令的软件；测本机连接程序也在这里）。
  - **高级**：附件手动下载 · AI 细项（写概要用的模型、精细识图模型、认视频画面里的字、认字精度 / 模型目录、本机语音识别端口 / CapsWriter 位置、视频转文字改用在线接口）· 问收藏（输入框提示字、模型下拉表、用量上限、先想同义词一起搜）· 提示词 · 批注留言给 AI · 开发者（问收藏 / 概要改用本机命令行、后端命令、检查这台电脑、这台电脑要什么）。
- **文案规矩**（她 10-10 定，参考 CC Switch）：每项说明压到一行（≤ 60 字，`tests/test_settings_layout.cjs` 守），多的放「?」悬停；「?」只讲规则是什么，会覆盖 / 要重启 / 要花钱这类后果写在按钮字（如「测试（发一句话，几乎不花钱）」「换一个新口令（旧的作废）」）或点了以后的确认框里；子选项只在父开关打开后出现；按钮不能点时旁边一句说为什么；开关改了立刻存，存失败把内存和开关都拨回原值并提示「没保存上，开关已拨回原来的位置：<原因>」（Obsidian 1.14.4 的 `ToggleComponent.setValue` 会再触发 onChange，拨回时挡一下）。
- **对新手只讲「口令」**：访问令牌只在「连接其他 AI → 高级」；「OAuth」这个词不出现在界面上（ChatGPT 那一步写「选会弹授权页的那一项（不是 No authentication）」）。
- **每栏最多一个主按钮**，其余次要动作是「像链接的一行字」（`.lb-link`），aria-label 写清点了会发生什么。
- **读不到的块**一律 `plugin.failBox(container, what, err, retry)`：「这一块暂时读不到，点重试」，原始报错折在「详情」里（不再露「账号那一行没画上：」「读不到状态：」「连接 AI 没画上：」）。
- 「打开设置」带落点：`openSetupPage(section)` → 分栏，旧名照认（`status` / `start` / `features` → 概览；`ai` → AI；`remote` / `connect` → 连接其他 AI；`sync` → 收藏与同步；`advanced` → 高级）；`status` 额外滚到账号那一行。
- 这一批**不做**新功能（备份、导入导出、用量统计另开一批）。

## 10-09 修订（她的裁决，覆盖下面第 7 批的前端部分；布局部分已被上面 10-10 修订取代）

她 10-09 晚的话：「连几个 MCP 要看好几个地方；设置页依然太乱；装了插件、填了 API 就能直接用，不填 API 也跑完；尽量一次跑完、集成在一个模块里、少操作。」
再补充三条（同晚）：

1. **零配置**：装上插件就按轻量版自动跑起来——不填任何东西也能直接用；首次启动自动「装好缺的 → 同步 → OCR → 目录 → 索引」。
2. **开关 + 一个按钮**：其余组件（AI 文本 / 识图、语音转写、CapsLock）做成同一页上的开关，外加一个「一键装好 / 跑完」按钮；**不再分步向导跳页**。
3. **没有单独的「开始」页**：并进设置——设置页顶部就是这一块（**状态 + 功能开关 + 连接 AI**）；别处重复的设置项一律删掉，**只留一处**；其余收进**一个**「高级」。

落地（以第 7 批的一页布局为基础做减法，后端 `setup plan / check / install / estimate / backfill` 不变）：

- 设置页是**一页**，从上到下：
  - **状态**：小红书账号（扫码 / 验证就在这一行）· 收藏同步（立即同步 / 定时…）· 评论补齐进度（后台在补 / 都补齐了 / 几篇补不上）· 问题（几件要你处理 + 打开问题面板）。
  - **功能**：`setup plan` 的每一项一行（磁盘 / 内存 / 状态）；必需项（归档、读取组件、Dataview）只显示状态；其余一个开关，开关就是唯一入口
    （OCR 开关 = `ocr.mode`、本机语音识别开关 = `asrAI.mode` 的 capswriter、CapsLock 开关 = 起 / 停 CapsWriter 客户端）；
    AI 问答 · 概要 · 打标、识图打开了就**在原地**出接口 / Key / 模型 / 测试 + 每 100 篇参考价（`setup estimate`）+「用建议的接口」；
    没选过 = **轻量版**；下面一个「轻量版（不要 key）」快捷和合计；最后是 **「一键装好 / 跑完」**（`setup run`，进度就在按钮下面，底部状态栏同步显示、可停）。
  - **连接 AI**：勾要连的客户端（Claude Code / Claude Desktop / claude.ai / ChatGPT / 其他 MCP 客户端，可多选，存 `settings.connect.clients`），
    每个一步：本机的一键写配置（`connect add`，写前备份、写完报结果、可「撤销」）；网页的一屏给全（远程服务开关、域名 + 测试公网、连接地址复制、口令复制 / 随机生成、几步做法、已连接的客户端可吊销）；
    其他：JSON 片段复制。开放给 AI 的文件夹（权限）只在这里：小红书收藏库开关 + 已开放列表 +「从库内选…」「选本机文件夹…」两个入口并排（对话框弹不出来时手输路径兜底）。
  - **高级**（一个折叠，默认收起，开没开记在插件对象上、不写 data.json）：同步细项、AI 细项（归档摘要模型、精细识别模型、视频画面文字、语音识别方式 / 端口、问答模型表、问答用量、提示词）、
    OCR 精度 / 模型目录、批注、远程服务（端口 / 访问令牌 / 最近访问 / 撤销全部 / 域名教程）、分类、运行环境。
- **首次**（`home-ui.firstRun`，启动检查里调）：新库（还没有 `_archive/catalog-data.json`）且没走过 → 选轻量版、自动跑一次「一键装好 / 跑完」；老库只记一笔、选择不动、不跑。没登录时那次会停在「确认小红书登录」，扫码成功后（第一次登录且从没同步过）自动再跑一遍。
- 「打开设置」带落点：`openSetupPage(section)`，旧分页名照认（`ai` / `start` → 功能、`remote` → 连接 AI、`sync` / `advanced` → 高级）。

### 后端新增

#### `python -m link_brain setup run`
按 `setup.selected`（没选过 = 轻量版）依次：装好要用的组件（能自动装的逐项装，装不了的如实给做法、不挡后面）→ 确认小红书登录（只问读取服务内存状态，不开页）→
同步收藏（`sync-favorites --limit 0 --extract`，含本地 OCR、开了 AI 顺手识图 / 概要）→ 补识图 / 概要（开了且配好 AI 才跑）→ 整理目录 → 语义索引（开了 AI 才跑）→ 评论补齐转后台。
每一步是带时限的子进程（超时只结束这一步、放过读取服务）。stdout 一行一个事件：
```jsonc
{"type":"progress","stage":"install|login|sync|enrich|catalog|embed|comments","label":"…","index":3,"count":7,"state":"running|ok|skipped|failed","text":"…"}
{"type":"progress","stage":"install","component":"asr","phase":"下载","done":12345,"total":67890,"text":"…"}   // 装组件的进度（同 setup install）
{"type":"result","ok":false,"code":"NEEDS_HUMAN","message":"先处理小红书：……；处理好再点一次「一键装好 / 跑完」","stages":[{"id","label","state","text"}],"selected":[…]}
```
退出码：0 都成 · 1 有步没成 · 5 号要人处理（掉登录 / 验证：碰号的步骤跳过，离线的照跑）。

#### `python -m link_brain connect status|add|remove <claude-code|claude-desktop>`
见 `link_brain/connect.py`：Claude Code 走 `claude mcp add lwa -s user -e … -- <python> -m link_brain mcp`（撤销 `claude mcp remove lwa -s user`）；
Claude Desktop 改 `claude_desktop_config.json` 的 `mcpServers.lwa`（只动这一项）。写前把原文件复制到 `~/.link-brain/connect-backups/`。测试一律临时配置路径。

#### `python -m link_brain pick-folder [--title T] [--initial DIR]`
弹系统「选文件夹」对话框（tkinter 置顶，没有就 PowerShell FolderBrowserDialog），`{ok, path, canceled, via}`；取消不算失败。

---

## 第 7 批原契约（10-03）——后端部分照旧有效，前端「左清单 + 右分步向导」已被上面 10-09 修订取代

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
- 选中状态由前端存插件设置 `setup.selected`（id 数组）；后端不存（`providers` 按它给 AI 门禁，`setup run` 按它决定跑哪几步）。

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

## 前端（第 7 批原文，已被 10-09 修订取代，留作出处）
- 插件设置页改成**上方分页**：开始 / 同步与内容 / AI / 远程阅读 / 高级（现有「更多」里的东西按类归入，**一项不删**；`tests/test_settings_layout.cjs` 的「一项不少」清单继续守住——10-09 起按一页核对，挪地方 / 合并重复的按表对上）。
- 「开始」页 = 左功能清单（预设按钮：轻量版 / 推荐 / 全部；每项勾选框 + 名称 + 磁盘 / 内存 + 齿轮跳到对应分页；底部合计）+ 右分步指引（①–⑤，上一步 / 下一步，竖排步骤条）。
- ② 一键检查并安装：逐项显示状态和进度条（读 install 的 progress 事件），失败如实给原因和重试；全部 ready 才算这步完成。
- ⑤ AI：先写「不填 key 也能用：归档、浏览、关键词搜索、本地 OCR、本地语音」；再列建议接口 + estimate 的每 100 篇价格（标价格日期）；填 key 后「试问一句」走真实问答（复用问收藏的 answerArchive），回答直接显示在这一步。
- 走完收成总览。首次引导 Modal（第 5 批 B2 的 onboarding-ui.js）改为直接打开设置页「开始」分页。
