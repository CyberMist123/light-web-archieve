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
`step` 词表：`sync.favorites / ingest / attachments.download / attachments.convert / attachments.recheck / enrich.summary / vision.layer1 / vision.refine / videos.transcribe / embed / nightly.<stepname> / ask / login`。

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
7. 文件监听只监听 `_archive/sync-status.json` 和 `_archive/problems.jsonl`（`vault.on('modify')`），其它用版本比对。
8. 性能埋点：`console.debug('[lb] <页> <阶段> <ms>')`，默认开，每页四个点（read / parse / render / restore）。

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

---

## 6. 进程与并发

**规则**
1. 插件起 Python **只有一个入口** `spawnPy`（§1 的 `runPy` 建在它上面）：统一 `cwd/env/windowsHide`、超时、日志；`run()`（互斥长任务）和 `spawnCapture()`（轻量）合成同一个函数的两个选项 `{exclusive, timeoutMs}`。
2. 杀树只有一个函数 `killTree(pid, {exclude})`，实现：PowerShell 枚举 `Win32_Process` 子孙，**跳过映像名 `link-brain-reader*` 和父链里含它的 `chrome*/msedge*`**，其余 `Stop-Process -Force`；禁止直接 `taskkill /T`。Python 侧 `enrich.kill_tree:148-163` 同规则（抽到 `link_brain/procs.py`）。
3. 读取服务**不得是任何 Python 的子进程**：`accounts.ensure_reader:229-237` 改成经由短命中转（`cmd /c start "" /b <exe> …`）拉起，启动后父进程退出。这是 0929 事故的根治；§6.2 是第二道保险。
4. 跨入口文件锁：`storage.file_lock(name, wait_s)`（把 `accounts.py:336-510` 的 O_EXCL + 心跳 + 陈旧判定抽出来，账号锁改成它的一个实例）。必须加锁的临界区：`catalog.build`（remove / pdftext / videos / attachments / 插件都会调）、`problems.jsonl` 压实、`sync-quota.json`、`answers.json`。
5. 写文件**必须**用 `storage.write_json / atomic_write_text / atomic_write_bytes`；追加日志允许 `open('a')` 但单次写入 ≤ 4 KB。JS 端写 vault 文件走 `LB.writeJson(path, obj)`（写 `.tmp` 再 `adapter.rename`）。
6. 子进程超时必须成对出现：`Popen` 处就写 timeout，超时走 `killTree`。CLI 模型（`text_stream.cli_call`）超时 = `cfg.timeoutSec`，默认 180。
7. 后台 worker（`serve.py`）停止 = 插件发 `{"id", "type":"cancel"}` → worker 杀自己起的 claude/codex 子进程并回 `result status=cancelled`；150 秒超时也走这条，不再 `worker.kill()` 留孤儿。

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

**迁移点**
- 新建 `package.json`（`devDependencies: playwright` 可选）、`tests/run-node.cjs`；修 `test_accounts_ui.cjs:33`（mock `window.confirm`）、`test_catalog_interactions.cjs:63,162`（缺 `workspace.onLayoutReady`、旧文案）。
- `scripts/smoke.py` 的 `check()` 输出格式对齐验收模板，`--offline` 作为 CI 可跑的一层。

---
