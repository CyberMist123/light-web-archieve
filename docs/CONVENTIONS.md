# 跨模块约定

基线 main=fbd89c3（代码与 54ab220 相同，行号通用）。适用：`link_brain/`、`link_brain/assets/*.js`、`obsidian-plugins/link-brain-actions/`。
这份文件只定「各模块之间怎么说话」；功能做什么看 `docs/RELEASE-BAR.md`，数据长什么样看 `docs/FORMAT.md`。
每节三段：**规则** → **形状/签名** → **迁移点**（文件:行）。规则用「必须 / 不得」，没写的沿用现状。
总则一句：**后端产生的每个状态，要么有一张卡/一个入口能看到，要么就不许存在。**

---

## 1. 操作结果（用户点的操作：保存 / 删除 / 导入 / 搜索 / 转写 / 测试）

**规则**
1. 插件会消费的 CLI 子命令：stdout **只允许最后一行是一个 JSON**（已有 `read.dump_json`），人话进度一律 stderr（照 `favorites.run` 的 `redirect_stdout(sys.stderr)` 做）。stderr 最后一行必须是一句能直接给用户看的原因。
2. 退出码只认 `cli.py:3-9` 那张表：0 成功或部分完成（剩余有计划）· 1 有项目失败 · 2 缺内容 · 5 要人处理 · 6 号被占用。**JSON 和退出码必须一致**：有任何 `status=failed` 的条目就不许退 0。
3. 逐项操作（删除、导入、挂附件、转换）必须**每条单独 try**，一条抛错不许吞掉其余结果；`finally` 里做收尾（重建目录）。
4. 插件：所有 Python 调用走**一个**包装函数；禁止再出现「忽略退出码 / 只读 stdout / 空串当 `{}`」。
5. 页面：**写盘成功才改内存和界面**；若先改了内存（乐观更新），必须留快照并在失败时回滚，提示固定句式「没保存上，内容还在，可重试：<原因>」。禁止 `catch {}` 空吞。
6. 成功提示说做了什么（「已删 3 篇」「已保存」）；失败提示带原因；进行中只显示后端真实发来的阶段，没有阶段就显示「正在…」，不轮播假文案。
7. （批次 D）新 CLI 的最后一行 JSON 一律 `read.dump_json(read.outcome(payload, ok=…, message=…, code=…))`：在旧键之外补 `ok / code / message`，不改旧键；`message` 是一句能直接给人看的话。插件 `run()` 的结束提示**只用 `json.message`**（没有 JSON 才按退出码兜底），永远不把整段 JSON、`exit=…`、stdout 尾巴弹给她。
8. （批次 D）提示与确认的规矩：
   - 做完 = 提示条：插件 `notify(msg, {kind, ms, actions})`，页面 `LB.say(msg, {kind, ms, actions})`（插件在就转给 notify）。默认时长成功 / 普通 3 秒、失败 / 警示 8 秒、带按钮 8 秒；`ms=0` 常驻，只给进度用（`LB.progress(msg)` → `{set, hide}`，set 只换成后端真实阶段）。
   - 要确认 = Obsidian 风格确认框：插件 `confirm({title, body, ok, cancel, danger})` / 页面 `LB.confirm(...)` → `Promise<boolean>`，Enter 确定、Esc / 关窗 = false；会丢东西的操作 `danger:true`。能撤销的操作不确认，改用 `LB.undoNotice(msg, onUndo, ms=6000)`（同一时刻只留最新一个；撤销失败照第 5 条的固定句式说原因）。
   - 进行中显示在发起处：页面 `LB.busy(el, text)`（卡片 / 区块上的遮罩只盖住目标：目标没定位时临时给行内 `position:relative`，结束还原），插件 `busyButton(btn, text)`；「还在跑别的」一律用 `plugin.busyText(label?)` 那一句（正在X（进度），完成后再点，或在底部状态栏停止）。
   - 全仓**不许** `window.alert`；`window.confirm` 只允许出现在 lb-page-lib 的兜底分支（插件没加载 / 手机上）。

**形状**
```jsonc
// 顶层（每个命令在自己既有键之外一律加这三个；不改旧键名）
{"ok": true, "code": "", "message": "已删除 3 篇", /* 原有键… */ "results": [
  {"item_id": "xhs-…", "status": "ok|skipped|failed|blocked|missing", "code": "", "error": ""}]}
```
`status` 词表固定五个；`code` 是 §2 的故障码（成功为空）。
```js
// main.js 唯一包装：解析最后一行 JSON；退出码≠0 且解析失败 → 抛 stderr 尾三行；超时 → 走 §6 killTree
async runPy(args, {input=null, timeoutMs=0, label=''} = {}) → {code, json|null, out, err, timedOut}
```
页面统一写法：
```js
const prev = snapshot(state); mutate(state); render();             // 乐观
try { const r = await provider().X(); if (!r.ok) throw Error(r.message); }
catch (e) { restore(prev); render(); notice('没保存上，内容还在，可重试：' + e.message); }
```

**迁移点**
- 插件六种解析：`main.js:310-320`（schedule 两处）、`:588-597 runJSON`、`:910-918`、`:921-929 deleteItems`（不看退出码、空串当 `{}`）、`:933-943 starNote`、`:946-952 attachFile`（code 2 当成功）、`:954-959 trashAction`、`:1267-1278 addTestButton` → 全部改走 `runPy`。
- `remove.py:132-138 delete_items`：每条 try、finally `catalog.build()`、逐条带 `code/error`；`:157` 退出码与 results 对齐。
- `catalog-view.js:323-327`：只摘 `status==='ok'`，其余保持选中并提示「n 篇没删掉：原因」。
- `chat-view.js:30-31`（`catch {}`）、`:349-353`（书签读内存）、`:377-381`、`:388-390`：改成「写盘成功再 unshift / filter」。
- `annotate-view.js:209-216`：`flash('已删')` 挪进 try，失败把那条 splice 回去；`:237-239` 失败 pop。
- `library-ui.js:41/44`：两段拼接，不覆盖。
- `main.js:1004-1011` 投喂：只替换匹配到的 URL 片段，同行其余字符原样。
- 进度：`chat-view.js:358-366` 轮播删掉；`serve.py` 已发 `start`，补 `{"type":"phase","text":…}` 事件（检索 / 筛选 / 生成），`main.js:673-681` 转发给 `onPhase`。
- `pdftext.run:337-344`、`videos.run:206`、`vision.run_upgrade:229` 等 stdout 混打 → stderr。

---

## 2. 故障码与问题记录

**规则**
1. 故障码 = `类.细分`，三类：`TRANSIENT`（自动退避重试）· `PERMANENT`（记原因，不再重试，不推送）· `NEEDS_HUMAN`（只报一次，一句话写该做什么）。另有一个**非故障类** `SKIPPED`（未配置 / 已关闭 / 预算到了）：进记录、不算失败、角标不计数。
2. 细分码全大写下划线，**复用现有码**不改拼写：`NOT_LOGGED_IN / CAPTCHA_REQUIRED / ACCOUNT_RISK / RISK_HOLD / NOT_INSTALLED / WRONG_ACCOUNT / RATE_LIMITED / DISCONNECTED / TIMEOUT / BUSY / INTERRUPTED / TOO_MANY_FAILURES / FAVORITES_SUSPICIOUS`。类由 `problems.classify(code)` 推出，所以 `sync-status.json.code`、`ReaderError.code` 的现有格式不变。
3. 新增细分码（首批）：`TRANSIENT.HTTP_5XX / HTTP_429 / NETWORK / SERVICE_BUSY / STEP_TIMEOUT`；`PERMANENT.PDF_ENCRYPTED / PDF_DAMAGED / DOC_UNSUPPORTED / NO_AUDIO / NO_SPEECH / NOTE_GONE / MODEL_OUTPUT_INVALID`（重试耗尽后）；`NEEDS_HUMAN.AUTH_FAILED（401/403）/ QUOTA_EXCEEDED / BACKUP_DISK_MISSING / STUCK（升级）`；`SKIPPED.NOT_CONFIGURED / DISABLED / BUDGET`。
4. **唯一问题记录** `vault/_archive/problems.jsonl`：append-only，一行一条；`load()` 按 `key` 折叠（最新一行为准，`count` 累加）；超过 500 条在 §6 锁内压实为最近 500 个 key。「已解决」= 再追加一行同 key 带 `resolved_at`。
5. 各模块**继续写自己的文件**（attachments.json / transcript.json / vision.json / extracted.json / sync-status.json 格式不动），只是在写入失败状态的同一处多调一次 `problems.report`，在同一步成功处调 `problems.resolve`。日志（sync-progress.log、fav-sync.log）保留，不再是查问题的入口。
6. **推送只有一个出口**：`problems.report` 内部判定——`NEEDS_HUMAN.*` 推一次（同 key 未解决不重推）；`TRANSIENT.*` 同 key 在**连续 3 个不同日历日**都出现 → 追加一条 `NEEDS_HUMAN.STUCK` 并推一次。`alert.alert` 改为模块私有，仓内禁止直接调用。夜跑脚本自己的汇总推送也取消，改为 `python -m link_brain problems report …`（它只负责登记步骤超时）。
7. **每个码都有自愈归类 + 一条台账**（10-04）：新增故障码时，同一个提交里 ①在 `repair.plan()` 给它归类——有修复动作（`run`，auto=夜跑自愈轮自动跑）/ 必须等（`wait`，写清等到几点、为什么）/ 要人处理（`human`，只限风控 / 登录 / key）/ 没有自动动作（`manual`，写下一步）；②在 `docs/ERRORS.md` 加一行「用户看到什么 → 根因 → 修法 / 自愈动作 → 回归用例名」。风控 / 登录 / 验证码 / 熔断永远是 `human`，自愈轮绝不重读收藏列表。
8. **子命令退出 3 = 没做完、原因已登记在它自己那一步**（`sync-favorites` 只读到一截、`embed` 没建完）：夜跑不重试、不另登记 `nightly.<步骤>`（同一件事只报一条）。

**形状**
```jsonc
{"ts":"2026-10-02T04:12:00+10:00","key":"attachments.convert|xhs-…|PDF_ENCRYPTED",
 "step":"attachments.convert","item_id":"xhs-…","title":"…","code":"PERMANENT.PDF_ENCRYPTED",
 "reason":"PDF 有打开密码（≤200 字）","action":"gave_up|retry_later|retrying|needs_human|skipped",
 "next_at":null,"count":1,"resolved_at":null}
```
```python
# link_brain/problems.py（新，约 150 行）
def report(step, code, reason, *, item_id=None, title=None, action=None, next_at=None) -> dict
def resolve(step, item_id=None, code=None) -> int          # 返回解决了几条
def classify(code) -> str                                   # 'TRANSIENT'|'PERMANENT'|'NEEDS_HUMAN'|'SKIPPED'
def load(limit=500) -> list[dict]                           # 折叠后、未解决在前
def summary() -> dict                                       # {needs_human: n, auto: n, gave_up: n, skipped: n, last_runs: {step: {ts, ok}}}
def export_redacted() -> str                                # §3「复制报错」
```
`step` 词表：`sync.favorites / ingest / attachments.download / attachments.convert / attachments.recheck / enrich.summary / vision.layer1 / vision.refine / videos.transcribe / embed / nightly.<stepname> / ask / login / config / remote / ai.summary / ai.vision / ai.refine / ai.embed / ai.ask`（`ai.*` = 接口那一侧的故障按能力归并成一条，item_id 为空，由 `ai_health.record` 写；调用点拿到 `api_error=True` 的结果**不要**再按篇 `problems.report`）（`remote` = 远程阅读服务：端口被占 `NEEDS_HUMAN.PORT_IN_USE`、计划任务没弄好 `PERMANENT.REMOTE_TASK_FAILED`）。

**迁移点**（每条：原状态文件照写 + `report/resolve`）
- 附件转 md：`attachments.mark_conversion:374-395`（failed → `PERMANENT.PDF_ENCRYPTED|PDF_DAMAGED` 或 `TRANSIENT.*`；`note is None` → resolve）；`pdftext.py:111-118,171-172,193-200` 给出区分码，不再只给一句 note；`pdftext.py:273-277` 的「同 sha 永不重试」只对 PERMANENT 成立，TRANSIENT 按 `next_at` 退避。
- 视频：`videos._failed:110-118`（`TRANSIENT`，`retry_after` 即 `next_at`）、`:139-141 no_speech`、`:174 no_audio` → `PERMANENT`；`transcribe` ok → resolve。
- 识图第二层：`vision.refine_object:318-322`（api_error → `TRANSIENT`，401/403 → `NEEDS_HUMAN.AUTH_FAILED`）、`:334-336 failed` → `PERMANENT.MODEL_OUTPUT_INVALID`；`run_refine:376-378` 收手 → `TRANSIENT.SERVICE_BUSY` 一条（step 级，item_id=None）。
- 概要：`llm.extract:402-419`（failed → 调用失败归 TRANSIENT，schema 两次不过归 PERMANENT.MODEL_OUTPUT_INVALID）；`enrich.enrich_one:222-227` gave_up → 不再 alert（`enrich.py:285-287` 删），改 report `action=gave_up`。
- 同步：`sync_state.record:94-147`、`account_problem:165-177`、`account_ok:180-188` 各加一行 report/resolve；`favorites.py:125,229,251,261,344,520`、`ingest.py:388,531`、`catch.py:139`、`attachments.py:206,245,877,903,1055,1095,1102` 共 17 处 `alert_mod.alert` 全部换成 `problems.report`。
- 问答：`ask.py:339 selection_failed` → `report('ask', 'SKIPPED.FALLBACK', …, action='skipped')`，结果里保留该键。
- 夜跑脚本（仓外）`Invoke-Step` 的 Problems 列表 → 每条 `python -m link_brain problems report --step nightly.<名> --code TRANSIENT.STEP_TIMEOUT`；脚本末尾直调报警出口的分支删除。

---

## 3. 后端状态 → 前端显示

**规则**
1. **登记制**：任何新故障码 / 新对象状态，必须同时在 `problems.STATE_REGISTRY` 登记一行，否则 `tests/test_problems_registry.py` 不过（它遍历代码里 `problems.report(` 的字面码 + registry，双向对齐）。
2. 显示位置只有四种：`top`（目录页顶部问题入口计数）· `card`（卡片角标 + 悬停原因）· `list`（只在问题列表里）· `none`（SKIPPED 之类，仅列表灰色「未开启」组）。NEEDS_HUMAN 一律 `top+card`。
3. 顶部入口 = 现在的「!」（`catalog-view.js:206-236`）升级：有「要你处理」显示橙色数字，其余灰色数字，为 0 不显示；点开 = 插件 `openProblems()` Modal，分组「等你处理 / 正在自动处理 / 已放弃 / 未开启」，每行：时间 · 标题 · 码 · 系统已做什么 · 「查看」（开那篇）· NEEDS_HUMAN 行附带 `accounts.SOLUTIONS` 的按钮。设置页不放诊断。
4. `catalog.collect` 给每个 item 加 `problems: [{code, reason, action}]`（从各对象文件推出，不读 jsonl），卡片悬停直接用；标签文案只从 registry 取，**JS 不许自己写状态文案**。
5. 「复制报错」= `problems.export_redacted()`：插件版本 · Python 版本 · 各 step 上次运行结果 · 最近 50 条问题。脱敏：去掉 `apiKey/token/cookie/Authorization/Bearer` 后面的值、`~` 替换家目录、`<vault>` 替换 vault 绝对路径、去掉 `xsec_token=` 参数值；保留 item_id 和标题（用户自己的数据）。
6. 登录/验证的「!」逻辑合并进去：`sync-status.json` 的 `blocked` 即 registry 里的 NEEDS_HUMAN 行，不再单独维护文案表。

**形状**
```python
STATE_REGISTRY = {  # code 前缀 → 显示；写进 catalog-data.json 的 "state_registry" 给 JS 读
  "NEEDS_HUMAN.NOT_LOGGED_IN": dict(where="top+card", label="需要登录", hover="小红书掉登录：点「!」扫码", group="needs_you"),
  "PERMANENT.PDF_ENCRYPTED":   dict(where="card",     label="全文没转出来", hover="PDF 有打开密码，字节已保存", group="gave_up"),
  "TRANSIENT.*":               dict(where="list",     label="稍后自动重试", hover="{reason}（{next_at} 再试）", group="auto"),
  "SKIPPED.*":                 dict(where="none",     label="未开启", hover="{reason}", group="off"),
}
```

**迁移点**
- 文案三处合一：`sync_state._ACCOUNT_MESSAGES:157-162`、`catalog-view.js:212-213` label 表、`main.js:416-427 VIEW` → registry（Python 唯一源，经 catalog-data 下发）。
- 「pid 还活着」判断三份：`sync_state.load:40-43`、`catalog-view.js:210`、`main.js:373` → 只留 Python 一份，页面读 `sync-status.json` 时不再自判。
- 卡片：`catalog-view.js:376-381` 角标区按 `it.problems` 追加灰标；`catalog.collect:291-292 attachment_reason` 并入 `problems`。
- `main.js:649-664 fixFromCatalog` → `openProblems()` 的一个按钮。

**第 4 批落地（10-02，后端）补充的契约**（字段名固定，前端照读）
```jsonc
// vault/_archive/problems-summary.json —— problems.jsonl 每次成功追加（report / resolve / 压实）后在 problems 锁里重写；
// sync_state 每次写 sync-status.json（record / progress / account_problem / account_ok / current）后也重写。写失败 fail-open。
{"updated_at": "2026-10-02T04:12:00+10:00",
 "needs_human": 1, "auto": 3, "gave_up": 2, "skipped": 1,          // 未解决的 key 数；skipped 只给「未开启」组，不算问题
 "last_runs": {"attachments.convert": {"ts": "…", "ok": false}},
 "sync": {"state": "ready|running|failed|blocked", "code": "", "message": "收藏同步完成", "detail": "",
          "label": "", "hover": "",                                 // code 非空时从登记表取（hover 已填好）
          "updated_at": "…", "last_success": "…", "favorites": 120,
          "new": 2, "deferred": 4,                                  // 本次新收几篇 / 还剩几篇逐晚处理（sync-status.json 新增的两个键）
          "progress": "", "running": false}}                        // running+pid 已死在 Python 侧改成 failed/INTERRUPTED
// catalog-data.json：顶层 "state_registry" = problems.registry_for_js()；每个 item 加
"problems": [{"code": "PERMANENT.PDF_ENCRYPTED", "label": "全文没转出来", "hover": "PDF 有打开密码，字节已保存",
              "group": "gave_up", "action": "gave_up"}]              // 从对象文件推出、不读 jsonl；SKIPPED 不列；attachment_reason / attachment_errors 照留
```
- 「pid 还活着」只在 `sync_state` 判：`load()` 只读修正；`current()` 发现 running+进程已死就把 INTERRUPTED 落盘进 sync-status.json、登记一条 `TRANSIENT.INTERRUPTED`、刷新 summary。`catalog.build` 末尾和 `python -m link_brain problems summary`（页面看到 running 但插件自己没在跑任务时调）都会走 `current()`。
- `problems list` 每行附 `label / hover（已填 {reason}{next_at}）/ group / where / step_label`；`problems resolve --step S [--item-id X] [--code C]` → `{ok, code, message, resolved}`（夜跑每步成功后调）；`problems summary` → 重写并输出 problems-summary.json。夜跑步骤名 `nightly.<小写字母数字连字符>`。
- 推送去重（§2.6 的细化）：NEEDS_HUMAN 按「同一步骤 + 同一细分码」去重（key 失效时几十篇都撞 AUTH_FAILED 只推一次）；账号类码（掉登录 / 验证 / 风控 / 熔断 / 登错号 / 没装组件 / `ACCOUNT_BLOCKED`）不管在哪一步撞见，一律登记在 `step=login, item_id=None`（`problems.report_blocked`）。STUCK 仍按 key 记（卡片上看得到是哪篇），推送同样按步骤去重。
- 新码：`NEEDS_HUMAN.ACCOUNT_BLOCKED / SYNC_STUCK`、`TRANSIENT.FAVORITES_FAILED / SYNC_FAILED / DOWNLOAD_FAILED / PROBE_FAILED / WEB_PROBE_BLOCKED / RETRY_EXHAUSTED / STEP_CRASHED / SECRET_TIMEOUT`、`PERMANENT.CONVERSION_FAILED / STEP_ARGS`；夜跑脚本专用的列在 `problems.EXTERNAL_CODES`。

---

## 4. 外部能力的 provider 接口

**规则**
1. 配置唯一源仍是插件 `data.json`（`ai_config.load`）。每个能力一个键：`textAI`（问答）· `summaryAI`（新，归档概要/打标，默认继承 textAI）· `visionAI`（第一层）· `visionAI.refine`（第二层）· `ocr` · `asrAI` · `docConvert`（本地，只有 `enabled`）。
2. `mode` 词表：`http`（OpenAI 兼容）· `cli`（本机命令行，仅 textAI）· `local`（进程内，ocr/docConvert）· `capswriter`（websocket，仅 asrAI）· `off`。**`media` 模式删除**。
3. key 来源顺序：`cfg.apiKey` → `cfg.keyFile/keyField`（已有）→ `os.environ[cfg.apiKeyEnv]` → 没有。**代码里不得出现任何默认目录、默认用户路径、默认 key 文件名**；用 `.githooks/private-patterns.local.txt` 里的模式 grep `link_brain/` 和插件源，命中数必须为 0（隐私闸只拦提交，这条拦默认值）。
4. 「没配置 = 跳过」：`resolve(cap)` 返回 `None` 时调用方记 `SKIPPED.NOT_CONFIGURED`，返回 `{"status":"skipped"}`，不算失败、不退非 0。
5. 超时全部在配置里有默认值（`ai_config.DEFAULTS[cap]["timeoutSec"]`），执行器不许写死数字。
6. 执行器返回统一形状；HTTP 执行器把状态码翻成故障码（429→`TRANSIENT.HTTP_429`，401/403→`NEEDS_HUMAN.AUTH_FAILED`，5xx→`TRANSIENT.HTTP_5XX`，402/欠费文案→`NEEDS_HUMAN.QUOTA_EXCEEDED`，4xx 其他→`PERMANENT.MODEL_OUTPUT_INVALID`）。
7. **测试按钮测的就是实际执行器**：`selftest <cap>` 对每个能力调 `resolve(cap)` + 与生产同一个函数（问答按下拉选中的 `with_model`；概要按 `summaryAI`；识图按 `visual.understand`；OCR 按 `vision.run_ocr`；语音按 `voice.transcribe` 跑随包 1 秒样例）。设置页每个能力块下只有一个「测试」按钮。
8. `assets/llm-config.yaml` 只留 prompts/limits/pricing/embedding；模型名、endpoint 不再从它回落。

**形状**
```python
# link_brain/providers.py（新，薄）
def resolve(cap: str, settings=None) -> dict | None   # 合并 DEFAULTS、解 key、带 timeoutSec；None = 未配置/off
# 执行器签名（现有函数改成这个返回形状即可）
#   text_stream.call(instruction, text, cfg, on_delta=None)    -> R
#   visual.understand(path, lines, cfg) / visual.refine(...)   -> R
#   vision.run_ocr(path, cfg)                                  -> R
#   asr.transcribe(wav_path, cfg)                              -> R   # 新 link_brain/asr.py：capswriter ws / http / off
#   docconv.to_markdown(path, cfg)                             -> R   # 新 link_brain/docconv.py：pypdfium2 + rapidocr + python-docx
R = {"status": "ok|failed|skipped", "text": str|None, "code": "<故障码或空>", "error": str|None,
     "usage": {...}|None, "truncated": bool, "api_error": bool}
```

**迁移点**
- 删：`text_stream.default_http_config:13-23`（本机 CSV 目录）、`llm.MEDIA_PY:33-36`、`vision.MEDIA_PY:21-24`、`pdftext.MEDIA_PY:29` 与 `_run_media:63-96,213-225`、`videos._speech:129-143`、`voice.transcribe:52-64` 的 media 分支。
- `llm.extract:375-377 call_media_text` → `text_stream.call(instruction, input_text, resolve('summaryAI'))`；`llm.load_config()['model']`（`:76-82`）不再当模型名来源。
- `text_stream.http_call:144`、`:23` 的 `llm.load_config()` 回落 → 删。
- `visual.vision_config:221-232` → `resolve('visionAI')`；`vision.strong_config:238-245` + `RefineRouter:257-286` 的 `LWA_GEMINI_KEYS` → `visionAI.refine.apiKeyEnv`（默认值可以是这个变量名，但不默认任何路径）。
- `vision.run_ocr:46-80` 的 `via in {cmx,qwen}` 删，只留 `local|off`；`main.js:1208-1212` OCR 下拉同步删 cmx/qwen。
- `ask.selftest:426-461` 按能力枚举；`main.js:1095,1212,1175 addTestButton` 改调 `selftest <cap>`。
- 两份默认值：`main.js:17-43 DEFAULT_SETTINGS` 与 `ai_config.DEFAULTS:52-86` 已经漂移（`dailyNewLimit` 200/50，Sonnet 命令不同，插件缺 `expandTerms` 说明）→ Python 生成 `assets/defaults.json`，两边都读它。

---

## 5. 页面状态与重绘（Dataview 2.5 秒刷新前提下）

**规则**
1. **数据版本** = `catalog-data.json` 的 `adapter.stat().mtime` + `built_at`。页面每次被 Dataview 重跑时先比版本：**版本没变且上一次的 DOM 还在 → 把旧 DOM 整块挂回新的 `dv.container`，不重读文件、不重建**；变了才重读 + 重建。
2. 解析后的数据缓存在插件对象 `provider().catalogCache = {version, data}`（5 MB JSON 只解析一次）；插件没加载时退回每次读。
3. **页面状态**（搜索词、筛选、主题、滚动、多选、展开的来源）存 `sessionStorage['lb:<role>']`，渲染后恢复；只存可 JSON 化的小对象，不存 DOM、不存 items。**插件对象**只放跨页面交接和进行中的事：`focusCatalogSearch`、`pendingArchiveQuestion`、`running/runningChild`、`answerWorker`、`catalogCache`、`pageState`（可选镜像）。**vault 文件**只放要跨设备/跨重启的：`chat-session.json`、`chat-archive.json`、`notes.json`。
4. 打开一篇再返回：**保持现在的打开方式**（同一窗格打开，不默认开新标签，免得标签越开越多）；返回时靠 §5.1 版本比对 + §5.3 状态恢复，回到原来的搜索词和滚动位置。按住 Ctrl 点开新标签照 Obsidian 习惯。
5. 数据变了只做**增量**：items 按 id diff，只重建变化的卡片；搜索框、滚动位置永不被重建影响。
6. 星标状态以 `catalog-data.json.items[].starred` 为准 + `link-brain:star` 事件更新，**不再每次打开读 350 份 notes.json**。
7. 文件监听只监听 `_archive/sync-status.json`、`_archive/problems-summary.json`（第 4 批起代替 problems.jsonl）和 `_archive/catalog-data.json`（批次 D：数据变了可见就刷新、不可见记 stale，800ms 防抖）（`vault.on('modify' / 'create')`），其它用版本比对。
8. 性能埋点：`console.debug('[lb] <页> <阶段> <ms>')`，默认开，每页四个点（read / parse / render / restore）。
9. （批次 D）**页面挂在 host 上**：目录 / 已收藏 / 回收站 / 问收藏页的 DOM 挂在 `LB.mountHost(cls)` 返回的 `div.lb-page-host`（`dv.container` 后面的兄弟节点，`data-lb-role=<页>`），不进 `dv.container`。原因：Dataview 0.5.68 重跑只执行 `container.innerHTML=''`（碰不到兄弟节点），页面挂在容器里会被摘下来再挂回去，输入框失焦、输入法断（C4）；它还给容器写行内 `overflow-x:auto`，容器成了滚动框，吸顶失效（C1）。host 由 `dv.component.register` 在卸载时摘掉，建之前先摘同 role 的残留；同一次运行里再调 `mountHost` 返回同一个 host；`keep()` 连 host 一起登记（登记的就是 host 本身也行），重跑时挂回原处。**批注块不用 host**（它要挪到左栏图片下面）——所以单栏笔记 / 实时预览里批注框会被 Dataview 重跑摘下：Chromium 摘掉有焦点的元素时同步发 blur，任何「失焦即保存」都会被重跑误触发（批次 D 基线 7ab44c6 上的红线读数见 `tests/test_rig_selfcheck.cjs` / `tests/ui/rig_selfcheck_ui.cjs`，修法归笔记线）。
10. （批次 D）**版本推进语义**：`reuseDom()` 里数据版本变了才调页面的 `update(v)`；**update 成功才推进 `view.version`**，失败记 `view.lastError`、保留旧版本，下次重跑重试；`view.updating` 是进行中锁，两次重跑叠在一起只做一次；**update 做完再核一次磁盘版本**，期间又变了（撞锁那次重跑带来的新版本）就接着再做一轮（最多 3 轮），不把新版本留给「下一次 Dataview 重跑」（catalog-data 变了本身不触发重跑）；锁 30 秒兜底（update 卡死时之后的重跑照样能更新）。页面自己刚写过版本文件：批注块用 `LB.rekeep()`；改了 catalog-data（点星 → `patch_items`）用 `LB.data.adopt(await LB.data.version(), data, written)`（data 必须就是插件缓存那份对象），下次重跑 0 读。`written` = 写者报回的「写完那一刻」的 stat `{mtime, size}`（Python 侧在锁里写完立刻 `os.stat`，`mtime = round(st_mtime_ns / 1e6)`，和 Obsidian 的 `Math.round(mtimeMs)` 同口径，比对容差 1ms）；给了就核，对不上（写者放锁之后、页面 stat 之前夜跑的 `catalog.build` 又写过）就不 adopt、走正常 update。不给 `written` 照旧推进（有这个竞态）。adopt 只推进「版本看 catalog-data」的那一页，批注块（版本看 notes.json）只推进插件缓存。目录数据的「更新于」统一用 `LB.dataUpdatedAt(data)`（= `built_at`）。
11. （批次 D）**样式挂 head**：页面样式一律 `LB.style(id, css)`（按 id 建或复用 `<style>`，文本不同才替换），不放进 wrap / 容器（复用时样式跟着走的老做法会因页面打开顺序互相盖）。共用规则和共享颜色变量在 `lb-shared`（lb-page-lib 初始化时自动注入），页面只放自己的规则；页面样式 id：目录 / 已收藏 `lbc-style`、问收藏 `lbchat-style`、回收站 `lb-trash-style`（批注块 `lba-annot-style`）；**lb-shared 总排在这几个前面**（页面对共用规则的覆盖靠「后写的赢」；热部署不重启时旧的页面样式先在 head 里，lb-page-lib 初始化会把 lb-shared 挪到它前面）。样式挂在**容器所在的 document** 的 head（页面开在弹出窗口里时进弹出窗口；建元素、兜底确认框同理）。跨页可能撞名的选择器加页面根前缀（目录 `.lbc-wrap`、问收藏 `.lbchat`）。颜色只用共享变量（`--lb-warn / --lb-warn-bg / --lb-warn-border / --lb-danger / --lb-danger-bg / --lb-ok / --lb-star`，插件 styles.css 顶部和 lb-shared 两份同值，`tests/test_css_vars_x13.cjs` 锁住）；橙色只给状态字和细条，说明文字保持正文色、前面加「⚠」。
12. （批次 D）**焦点与快捷键**：会被整页重建的输入框挂 `LB.trackFocus(input, key)`，首建末尾调 `LB.restoreFocus(input, key)`（3 秒内还原焦点和选区；记录单放 `sessionStorage['lb:<role>:focus']`，页面 `state.save` 整体覆盖页面状态冲不掉它；3 秒从 `max(focusAt, blurAt)` 算——重建摘掉输入框时 Chromium 同步发 blur，记下那一刻，她停手很久后才重建也照样还）；页面级快捷键（Ctrl+F、Ctrl+±、Esc 清多选）只给 `LB.activeLeafHas(wrap)` 为真的那一页；页面的全局 Esc 先判 `LB.menuOpen()`（菜单关掉后延一拍才变回 false）。菜单用 `LB.showMenu(items, evt)`（插件的 obsidian.Menu，自带 Esc / 方向键；鼠标点的按指针，键盘 Enter / 空格触发的 click（`detail=0`、坐标 0,0）和不带坐标的按发起元素左下角；返回的菜单上可以再 `onHide(cb)`，插件包了一层、照样复位 menuOpen；没有菜单项不显示也不设 menuOpen）；只有要放输入框的弹层（如时间菜单）才自制，并自己做键盘操作。
13. （批次 D）**手机只读与跳页**：`LB.mobile`（`app.isMobile`）为真时插件不在，需要插件的按钮点了只 `LB.need(method)` 说一句（`LB.MOBILE_ONLY_TEXT`）并返回 null；`LB.ensure(method)` 在手机上直接抛同一句、不去 enablePlugin；页首 `LB.mobileNote(host)` 插一次浅色小字。跳到目录 / 问收藏 / 已收藏 / 回收站用 `LB.openPage(role)`（按仓根那层 frontmatter 的 `lb-page` 找文件，不依赖插件）。所有 `provider().X()` 调用改成 `LB.need('X')?.X()` 或 `(await LB.ensure('X')).X()`。

**5.3 插件对象字段登记表**（跨页面交接和进行中的事只放插件对象上；新字段先在这里登记一行，各线只在自己那一小节里加）

| 字段 / 事件 | 谁写 | 谁读 | 说明 |
|---|---|---|---|
| `running` / `runningChild` / `importing` | 插件 spawnPy / importText | 页面 ensure、busyText | 互斥长任务（已有） |
| `runningProgress` | 状态栏那条线（L4） | `busyText()` | 占用句里的「（进度）」，没有就不写 |
| `catalogCache` `{version, root, data}` | lb-page-lib `data.load` / `data.adopt` | 三张页 | §5.2；adopt 只在 data 就是缓存那份时推进版本（给了 written 还要和当前 stat 对得上） |
| `answerWorker` / `answerPending` / `answerSequence` | 插件问答 worker | 插件 | pending 每条带 `tag`（`'chat'` / `'setup'`），`stopArchiveAnswer(tag)` 只停同 tag |
| `menuOpen` / `_lbMenu` | 插件 `showMenu` | `LB.menuOpen()` | 菜单真显示了才设 true；关掉后延一拍才变 false（调用方再设 onHide 也照样复位） |
| `mediaNav` | onload | 插件 `openLightbox` 转发 | 被跳过（旧插件开着）时 `skipped=true` |
| `noteActions` / `noteTools` / `imageActions` / `playerUI` | onload 的四个挂载点 | 各线自己 | `require(<文件>)(obsidian, plugin).attach()`；各线只改自己那个文件 |
| `focusCatalogSearch` / `pendingArchiveQuestion` | 命令 / 目录页 | 目录 / 问收藏页 | 已有 |
| 事件 `link-brain:settings` | 插件 `saveSettings()` 每次保存后 | 页面（`dv.component.registerEvent`，自己 rAF 合并） | 模型增删改名、设置变化都走它，不另设 models-changed |
| 事件 `link-brain:star` / `link-brain:catalog-prefs` | 插件 | 目录 / 批注块 | 已有 |
| 事件 `link-brain:ask-pending` / `link-brain:chat-session` | 插件 / 问收藏页 | 问收藏页 | 已有 |

- 目录线（L1）：`pendingCatalogQuery` + 事件 `link-brain:catalog-query`（笔记线写、目录读，读完即删）。
- 问收藏线（L2）：

  | 字段 / 事件 | 谁写 | 谁读 | 说明 |
  |---|---|---|---|
  | `chatInFlight` `{page, id, userTurnId, convId, private, q, askedAt, phase, text, startedAt}` | 问收藏页 `submit`（第一个 await 之前同步写；onPhase / onDelta 写 phase / text） | 所有问收藏页 | 同一时刻只答一问：`isBusy() = 自己在答 \|\| chatInFlight 属于别的页`。答完由发起那一页（哪怕已经换走、只剩旧闭包）删掉；`id` = 回答轮的 id，`userTurnId` = 它的问题 |
  | `chatQueue` `[{q, opts, at}]` | 问收藏页（作答中再发 / 忙时带词跳来） | 所有问收藏页 | `opts` 可带 `sourceIds` / `fresh` / `scope`；看得见、不忙的那一页从队首取（`drainQueue`），取走即删 |
  | `chatSaveChain` Promise | 问收藏页 `enqueueWrite` | 问收藏页 | `chat-session.json` / 历史文件只经这条链串行写（含换页前那一页的旧闭包）；答完的回答在链里先读磁盘、插回自己那条问题后面再写，不整份覆盖 |
  | `pendingArchiveScope` `{ids, title, note, at}` | 插件 `askAboutNote`（笔记 ⋯ / 命令） | 问收藏页 `takePending` | 「问这篇」：取走即删，超过 5 分钟丢弃；页面存进页面状态 `scope`，不自动提交 |
  | 事件 `link-brain:chat-live`(pageId) | 正在答的那一页（每个 delta / 阶段） | 别的问收藏页 | 收到后从 `chatInFlight.text / phase` 画流式那一块（200ms 节流） |
  | 事件 `link-brain:chat-session`(pageId) | 问收藏页每次写会话成功后 | 别的问收藏页 | 重读会话、强制全量重建，然后看排队；`from === 自己` 或自己在答时不理 |
  | 事件 `link-brain:chat-queue`(pageId) | 改了 `chatQueue` 的那一页 | 别的问收藏页 | 重画排队行 |
- 笔记线（L3）：`body.lb-actions-on`（note-actions attach 时加、卸载时去）。
- 设置线（L4）：`accountCache`、事件 `link-brain:task`、`onTask(cb)`。
- 功能线（L5）：`settings.media = {loop, playlistOrder}`（插件设置，后端不读）。

**形状**
```js
// 共享前导 lb-page-lib.js（由 catalog.py 像 catalog-search.js 一样内联到三张页 + 批注 bootstrap）
const LB = lbPageLib(dv, app, role);     // {root: LB_ROOT, path(p), provider(), state: {load(), save(obj)}, data: {version(), load()}, reuseDom(container) → bool, t(label)}
if (await LB.reuseDom(dv.container)) return;   // 版本同、DOM 在 → 挂回去，结束
```
`sessionStorage['lb:catalog'] = {q, cat, topic, today, todo, media, star, select: [...ids], scrollTop, ts}`。

**迁移点**
- `catalog-view.js:175-185` 每次读 5 MB + 遍历 `dv.page()`、`:443` 读全部 notes.json → 走 `LB.data`；`:188 committed=''`、`:267-269 activeCat…`、`:302 selected` → `LB.state`；`:391 open` 保持同窗格；`:398-400 window.__lbcEsc` 这类全局挂钩进 `LB`。
- `chat-view.js:17-19` 同；`:260 saveSession()` 每次 submit 和 `:273` 每个键入都写 vault（会触发别的页刷新）→ 草稿存 `sessionStorage`，只有 turns 变化才写文件。
- 三份 `LB_ROOT/lbPath`：`catalog-view.js:6-7`、`chat-view.js:8-9`、`render.py:933-937` → `lb-page-lib.js`。
- 三份「插件方法不在就 disable/enable」：`catalog-view.js:170-174, 228-233, 256-262` → `LB.provider({require:'openPlusMenu'})` 一处。
- `catalog.py:305-307` 内联拼接处加 `lb-page-lib.js`；`catalog-view.js:361 sort` 等搜索规则留给第 1 批。
- **第 2 批落地（10-02）与上文的出入**：①版本用 `catalog-data.json` 的 `mtime:size`（先用 Obsidian 文件索引里的同步 stat 挂回旧 DOM，再用 `adapter.stat` 核一次，变了走页面的 `update()`），没用 `built_at`（要先解析才拿得到）；②`render.py` 烤进每篇笔记的批注 bootstrap 不动（改它要重渲全部笔记），前导拼在 `_archive/annotate-view.js` 最前面，批注块的版本是那篇的 `notes.json`；③新增：同一标签页里藏着的编辑视图（实时预览）也会跑一遍 dataviewjs，看不见时先不画（`deferIfHidden`），切到编辑模式再由 Dataview 重画；④星标：`note star` 顺手把 `starred / starred_at` 改进 catalog-data（`catalog.patch_items`，和重建抢同一把锁，拿不到就跳过）；⑤卡片按 id + 内容签名复用（封面图元素不换）；catalog-data 多了 `cover_w / cover_h`，卡片先占位，返回时滚动一次到位；⑥Obsidian 后退时会按行号把滚动容器归零，`restoreScroll` 恢复后再守 1.2 秒（用户动了滚轮 / 键盘就停）。
- **批次 D 地基（10-08）**：lb-page-lib 加 9–13 条的助手（mountHost / style + lb-shared / adopt / dataUpdatedAt / say / progress / undoNotice / confirm / busy / need / ensure 手机只读 / mobileNote / openPage / showMenu / menuOpen / trackFocus / restoreFocus / activeLeafHas），插件末尾 foundation 段加 notify / confirm / showMenu / busyButton / busyText / refreshCatalog / openLightbox 转发。迁移由各页面线做：`catalog-view.js` / `trash-view.js`（目录线）、`chat-view.js`（问收藏线）改挂 host、样式进 head、`window.alert / confirm` 换 `LB.say / LB.confirm`、`provider().X` 换 `LB.need / LB.ensure`；`annotate-view.js`（笔记线）只换提示。lb-page-lib.js 合入后冻结，新的共享接口由主审出地基补丁。

---

## 6. 进程与并发

**规则**
1. 插件起 Python **只有一个入口** `spawnPy`（§1 的 `runPy` 建在它上面）：统一 `cwd/env/windowsHide`、超时、日志；`run()`（互斥长任务）和 `spawnCapture()`（轻量）合成同一个函数的两个选项 `{exclusive, timeoutMs}`。
2. 杀树只有一个函数 `killTree(pid, {exclude})`，实现：PowerShell 枚举 `Win32_Process` 子孙，**跳过映像名 `link-brain-reader*` 和父链里含它的 `chrome*/msedge*`**，其余 `Stop-Process -Force`；禁止直接 `taskkill /T`。Python 侧 `enrich.kill_tree:148-163` 同规则（抽到 `link_brain/procs.py`）。
3. 读取服务**不得是任何 Python 的子进程**：`accounts.ensure_reader:229-237` 改成经由短命中转（`cmd /c start "" /b <exe> …`）拉起，启动后父进程退出。这是 0929 事故的根治；§6.2 是第二道保险。
4. 跨入口文件锁：`storage.file_lock(name, wait_s)`（把 `accounts.py:336-510` 的 O_EXCL + 心跳 + 陈旧判定抽出来，账号锁改成它的一个实例）。必须加锁的临界区：`catalog.build`（remove / pdftext / videos / attachments / 插件都会调）、`problems.jsonl` 压实、`sync-quota.json`、`answers.json`。
5. 写文件**必须**用 `storage.write_json / atomic_write_text / atomic_write_bytes`；追加日志允许 `open('a')` 但单次写入 ≤ 4 KB。JS 端写 vault 文件走 `LB.writeJson(path, obj)`（写 `.tmp` 再 `adapter.rename`）。
6. 子进程超时必须成对出现：`Popen` 处就写 timeout，超时走 `killTree`。CLI 模型（`text_stream.cli_call`）超时 = `cfg.timeoutSec`，默认 180。
7. 后台 worker（`serve.py`）停止 = 插件发 `{"id", "type":"cancel"}` → worker 杀自己起的 claude/codex 子进程并回 `result status=cancelled`；插件兜底超时（`2 × textAI.timeoutSec + 60` 秒，必须长于后端模型超时）也走这条，不再 `worker.kill()` 留孤儿。命令行模型自己退出后留下的子进程（父链已断）由 `procs.kill_leftovers` 收：只认看门狗记过的（pid + 创建时间对上）和父 pid 是它、创建晚于它的孤儿。

**形状**
```python
with storage.file_lock("catalog-build", wait_s=120): ...
procs.kill_tree(pid, exclude=("link-brain-reader",))   # 返回杀掉的 pid 列表
```
```js
await provider().spawnPy(args, {input, timeoutMs, exclusive: false, label})  // → {code, json, out, err, timedOut}
provider().killTree(pid)   // 同一排除规则
```

**迁移点**
- `main.js:340-355 spawnCapture`（`taskkill /T`）、`:618-630 interruptRunning`（`taskkill /T`）、`:668-705 ensureAnswerWorker/requestAnswer`（`worker.kill()`）、`:868-898 run` → `spawnPy` + `killTree`；`:900-906 log` 读整文件再写（无上限）→ `adapter.append` + 1 MB 轮转。
- `text_stream.cli_call:99-112` 无超时 → 加 `communicate(timeout)` + `kill_tree`。
- 自写原子写：`enrich._save_state:53-59`、`topics.save:117-123`、`answer_cache._save:77-86`、`accounts._atomic_write_text:95-104` → `storage.*`；`videos.download:29-31` 直接写目标文件 → 写 `.part` 再 replace。
- `chat-view.js:30-31` `adapter.write` 直写 → `LB.writeJson`；`annotate-view.js:139` 同。

---

## 7. 测试约定

**规则**
1. 三层：`python -m pytest -q`（后端）· `npm test`（node 单测，无浏览器）· `npm run test:ui`（playwright，可选依赖）。仓库带 `package.json`；`tests/run-node.cjs` 跑所有 `tests/test_*.cjs` 并汇总，任何一个失败退 1。
2. **回归查询集** `tests/fixtures/search_queries.json`（合成数据 `tests/fixtures/catalog-data.sample.json`），Python `tests/test_search_regression.py` 和 JS `tests/test_catalog_search.cjs` 读**同一份**：每条 `{query, must_top: [ids], must_include: [ids], must_exclude: [ids], fuzzy_only: [ids]}`。真数据版 `tests/tools/search_real.cjs` 读 env `LB_REAL_CATALOG` 指的文件，只打印不断言，结果不进仓。
3. **真实入口验收记录** `tests/acceptance/YYYYMMDD-<批次>.md`，固定模板：入口（Obsidian 按钮 / 夜跑步骤 / CLI）· 步骤 · 预期 · 实测 · 体验预算实测值（RELEASE-BAR §2 对应行）· 「待她：一步」清单。没有这份文件的批次不算完成。
4. 每个新故障码：pytest 一条判定用例 + registry 对齐用例；每个页面改动：`test_assets_syntax.cjs` 必过 + 对应 `.cjs` 交互用例更新。
5. 测试不碰真库、不联网、不起小红书组件（`conftest.py` 现有闸门不动；node 侧同样不许 `spawn` 真 Python）。
6. （批次 D）**测试架要像真宿主**，冻结的共用件：`tests/_fakedom.cjs`（node 假 DOM：Dataview 容器行内 `overflow-x:auto`、阅读视图 / 实时预览两种祖先链、脱离文档即失焦、`dataviewBlock` 的 rerun / recreate / detach）、`tests/_fakeobsidian.cjs`（Menu / Notice / Modal / Setting 渲染真结构，node 和 playwright 共用）、`tests/_obsidian_shell.cjs`（playwright 外壳：page-reading / page-live / note-reading / settings-modal 四种宿主、亮 / 暗 / 改了橙色三套主题、Obsidian 1.14.4 CSS 子集逐条注明出处）、`tests/_clock.cjs`、`tests/_mini_md.cjs`、`tests/tools/synth_vault.py`。假 DOM 的焦点语义照 Chromium 151 / Edge 150 实测：摘掉（含 `innerHTML=''`、挪到别处）有焦点的子树时，先把 activeElement 交回 body，再在焦点元素上同步发 blur（不冒泡）+ focusout（冒泡，relatedTarget=null），发完才摘。外壳的 C1 探针 `probeSticky` 口径照 L1：`|delta| ≤ 1` 才算贴住滚动容器顶（`top:0` 会停在 32px 的 `--file-margins-y` 内边距下沿，缝里露卡片——判红并在 `gap` 里报出缝里是什么；要不要接受这条缝归主审裁决）。各线只在自己的 `tests/_fake_<线>.cjs` 里加东西；守卫 `tests/test_rig_selfcheck.cjs` 和 `tests/ui/rig_selfcheck_ui.cjs` 必过——别把外壳「修」得不像真宿主。Obsidian 升级后跑 `python tests/tools/obsidian_css.py --check` 复核子集里的规则还在。
7. （批次 D）页面测试一律放 `tests/ui/*.cjs`（run-node 自动发现，不再改 UI_FILES 列表）。没装 playwright 时 UI 层全部 SKIP，汇总最后一行写「UI 层没跑」——验收文件必须照写，不许当通过。worktree 里接共享 node_modules：`New-Item -ItemType Junction node_modules -Target <共享目录>\node_modules`（node_modules 在 .gitignore 里）。
8. （批次 D）**红线规矩**：新写的几何 / 焦点类用例（吸顶、失焦、滚轮够不着这类）必须先在出问题那一版的资产上跑红（外壳的 `pageAssets(kind, {rev})` 用 `git show` 只读取旧版），把红的读数记进验收文件，再开工修；改完同一个用例转绿。

**迁移点**
- 新建 `package.json`（`devDependencies: playwright` 可选）、`tests/run-node.cjs`；修 `test_accounts_ui.cjs:33`（mock `window.confirm`）、`test_catalog_interactions.cjs:63,162`（缺 `workspace.onLayoutReady`、旧文案）。
- `scripts/smoke.py` 的 `check()` 输出格式对齐验收模板，`--offline` 作为 CI 可跑的一层。
- 批次 D：`catalog_ui_smoke.cjs` 早已过期（还在用 `.lbc-sync`、「打字不搜」），装上 playwright 后在基线就挂（目录线按边打边搜重写）；`ui_pages_qa.cjs` 里用 `window.scrollTo` 断言吸顶的那条是假阳性（真宿主滚的是 `.markdown-preview-view` / `.cm-scroller`），改用外壳。

---

## 8. 界面用词（批次 D，X5）

**规则**：界面字符串照下表；已有页面文件名（`星标收藏.md` / `收藏搜索.md`）不改，靠页头 `lb-page` 找页。README 和插件说明里面向用户的描述不在本表管辖内（改之前先问作者）。

| 东西 | 用词 | 不再用 |
|---|---|---|
| ★ | 收藏 / 取消收藏；筛选叫「已收藏」 | 星标收藏、加入星标收藏 |
| 删条目 | 删除（移到回收站） | 删除收藏 |
| 回答书签 | 存到已保存；提示「已存到「已保存」」/「已从「已保存」移除」 | 收藏回答 |
| 页面名 | 目录 · 问收藏 · 已收藏 · 回收站 · 同步记录 · 问题 | 收藏搜索、星标页 |
| 分类 | 分类（「管理分类」「加一个分类」） | 目录大类、目录标签、大类 |
| 导入 | 导入网址（可批量） | 导入收藏、导入链接 |
| 收件箱 | 投喂文件 | — |
| 同步动作 | 立即同步收藏 | 补跑收藏同步 |
| 只读提示 | 手机上只能看：导入、同步、问 AI、收藏要在电脑上用（`LB.MOBILE_ONLY_TEXT`） | 英文报错、「请启用插件」 |
| 占用 | 正在X（进度），完成后再点，或在底部状态栏停止（`plugin.busyText()`） | 「还在跑…等它完事再点」各写各的 |
| 失败回滚 | 没保存上，内容还在，可重试：<原因>（§1.5） | — |

各页面里的字由各自所属的线改（目录 L1、问收藏 L2、批注 L3、插件与设置 L4）；`tests/test_terms_x5.cjs`（L4）全部合入后设为必过。

---
