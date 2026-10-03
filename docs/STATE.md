# Current State

## 2026-10-03 第 10 批：问收藏「宁广勿漏」——多路召回 + 扩词默认开 + 批注进检索 + 来源分层可删（分支 batch10-recall）

- **不再丢候选**：`_select_sources` 去掉 `min(count, 5)`；「挑选材料」只排序（挑中的排前，没挑中的照样送 / 照样列），挑空也不再直接答「候选收藏中没有符合」，改为提示作答模型逐条核对。送进作答模型的篇数 `ask.primary_count` = 按字数预算（每篇约 700 字，默认 8000 字 → 11 篇；最少 topK、最多 20）。
- **多路召回**（`ask.recall`，生产和 `tests/tools/ask_eval.py` 共用）：原词 BM25 ∪ 语义（`semantic.query_hits` 改为按篇聚合：每篇取最像那块的分，前 40 篇，相对下限「中位数 + 0.2 ×（第一名 − 中位数）」；以前只看前 80 块）∪ 小模型扩出的每个词一路（BM25 前 30，同属一组取最好名次不累加）∪ 原问题 + 扩词的语义一路；加权 RRF（`retrieval.fuse`，扩词路权重 0.15，真库扫过 0.15–0.5 定的）。候选池 `ask.candidate_pool`：各路前几名保底（词法 40 / 语义 40 / 每个扩词 20），融合顺序补满到 80，**全部回给页面**。
- **扩词默认开**（设置键改名 `retrieval.queryExpand`，默认 true；旧 `expandTerms` 不再读——她 data.json 里那个 false 是 09-16 走命令行模型慢 15 秒时关的）。她 10-03 定：不做手工实体别名表，常识交给模型。每问一次文本 AI 接口（设置里的 textAI 本身，不随问答页下拉换成命令行模型；不是 http 就用归档摘要模型；都没有 = 不扩），`noThinking`（千问关 `enable_thinking`，DeepSeek 关 thinking），和这一问的 embedding 并行，最多等 6 秒（超时先答，后台结果照样进缓存）。缓存 `_archive/query-expand-cache.json`（模型 + 问题 → 词，500 条）。扩出的词去掉原词 / 同义词 / 库里没有的 / 全库四成以上都有的。`search-aliases.json` 不动。
- **批注进检索**：`catalog-data.items[].search_fields.notes`（`note.annotation_text`：没删的、非空的批注，一条一行）；词法权重同标签（10）；语义单独成块（≥2 字就成块，改批注只重算那一块）；问收藏按各篇 notes.json 的修改时间现读（`ask._with_live_notes`），不等目录重建；目录页要等下一次 `catalog`。
- **英文按词边界**（`retrieval.has / count / find` ↔ `catalog-search.js termRegex / hasTerm / termIndex`）：字母数字开头的词前面不能紧挨字母数字；4 字母以下的纯字母数字词后面也不能紧挨字母（允许 s / es），长词按词首。`cafeine` 不再命中 `ai`，`dream` 仍命中 `dreaming / dreams`。中文照旧。
- **目录搜索**：保持关键词精确筛选（不接扩词 / 语义：每敲一次回车调模型太重，她要的「搜广」交给问收藏），结果顶部一行「按关键词筛选。想把同义词、相关内容也找出来 → 去问收藏搜「…」」，点了带着这个词去问收藏（`catalog-view.js` 只加了这 2 行）。`rankItems` 每条多 `row.hit`（懒算）：`{kind: exact|alias|typo|pinyin|gap, confidence: high|low, crossLanguage, term, variant, snippet: {field, label, text, marks}}`，低置信度 = 错字 / 拼音 / 漏字 / 换语种的同义词，给另一路做卡片标题下的浅色小字。
- **问收藏页来源**（`chat-view.js`）：「主要依据 · N」（送进模型的，带 [来源N]）+「其他相关 · M」（候选池其余，默认收起）；每条 ×（记在这一轮的 `removed`，随会话存）；删过之后「按剩下的 N 条重新回答」（`answerArchive({sourceIds})` → worker `source_ids` → `ask.answer(source_ids=…)`：只用留下的来源，主要依据在前、其他相关按原顺序补到预算篇数，不重新检索、不挑材料、不撞 / 不记答案缓存）和「恢复删掉的」。结果多 `related`、`expansion`，`sources[].tier`。
- 评测（真库只读，题目在 workdesk 本地）：31 题（第 8 批 22 题 + 她的失败例 9 题）recall@8 0.825 → 0.878、recall@20 0.668 → 0.894、候选池覆盖 0.633 → 0.972（改前页面最多 8 篇、挑选时 5 篇）；失败例那 9 题候选池覆盖 1.0。语义层不可用时 0.781 / 0.887。合成回归：`tests/test_recall_b10.py`（18 例）、`tests/test_ask_sources_b10.cjs`、搜索回归集加 cafeine / 批注两条；`tests/test_ask_eval.py` 挑选语义改了 2 例。pytest 857 过；`npm test` 23 过 0 败 4 跳。
- 部署：ff 进 main → 拷插件 → `python -m link_brain catalog`（目录带上批注、页面脚本换新）→ `python -m link_brain embed`（只补批注 3 块，1 次接口调用）→ 重载插件。没在 Obsidian 里点过（待她：一步）。

## 2026-10-03 第 7 批（后端）：「开始」页向导 `setup plan / check / install / estimate / backfill`（分支 batch7-setup）

- 新包 `link_brain/setup/`（契约 `docs/SETUP-CONTRACT.md`），`python -m link_brain setup <子命令>`，输出 §1 形状、退出码 0 成功 · 1 失败 · 5 只能手动（Dataview / 填 key / 发布地址没配 / 别人装的 CapsWriter 缺模型）。
- **plan**：9 项功能（core / reader / dataview / ocr / asr / capslock / ai_text / ai_vision / remote）+ 三个预设，每项带 `disk_mb / ram_mb / basis`。装了的现量（目录和 Python 包按文件逐个 stat、跟着目录联接走；CapsWriter 服务端 / 客户端在跑就读它们的峰值工作集，Windows ctypes 只读查询），没装的按官方包 / 模型解压大小；量不到的用 `components.RAM_MEASURED`（10-03 开发机实测：后端进程 151 MB；PP-OCRv6 识别峰值 medium 672 / small 397 MB，在临时进程里真加载认一张 1080×1440 图量的；CapsWriter 客户端 143 MB；服务端 Qwen3-ASR-1.7B 三个进程峰值之和 2187 MB）。读收藏时开的浏览器没实测（开发中不许起读取服务），按 300 MB 估并写明。
- **check**：只读。status 多一个 `needs_key`（ai_text / ai_vision 没配 key：不算没装好，`all_ready` 不被它拖住，前端放到 ⑤）。`ok` = 没有 failed；`all_ready` = 除 needs_key 外全 ready。
- **install**：stdout 一行一个 `{"type":"progress",…}`，最后一行 `{"type":"result",…,"status","check"}`（装完自己再 check）。core / ocr 缺包用当前 Python 的 pip 补（没有 pip 如实说用 `uv tool install --reinstall`）；ocr 缺 PP-OCRv6 medium 模型时按 rapidocr 自带清单（default_models.yaml 的官方地址 + sha256）下到 `~/.link-brain/models/rapidocr` 并写 `ocr.modelDir`，加载模型认一张测试图自检；reader 调现有 `reader install`（发布地址空 = 手动）；dataview / ai_* / remote 只报怎么手动做。
- **CapsWriter 一键安装**（`setup/capswriter.py`）：官方 v2.6 `CapsWriter-Offline-20260914.zip` + 模型 `Qwen3-ASR-1.7B-q4_k.zip`（可 `--asr-model sensevoice`），地址 / 大小 / sha256 取 GitHub Releases API 的 asset digest（10-03 核对，许可 MIT）。下载到 `~/.link-brain/downloads/`（`.part` 续传，HTTP Range）→ 校验 → 解到 `capswriter.staging-<pid>` → 只改这份新解出来的 `config_server.py`（`addr` 改成 127.0.0.1，上游默认 0.0.0.0 会对局域网开放；选模型）→ 写安装记录 → 整目录一次改名成 `~/.link-brain/capswriter`（中途断掉不会留半截）→ 删下载包 → 写插件设置（`asrAI` 地址端口、`voice.capsWriterDir`；同时在 result 里带 `settings_patch`，插件开着时请它自己 merge 保存，免得被内存里的旧设置盖掉）→ 经 `procs.spawn_detached` 拉起服务端 → 随包 3 秒样例真识别一次。**已装的不管谁装的都不重装、不改文件和设置**：服务端在跑 = ready；没在跑只拉起来自检（别人装的先试计划任务「CapsWriter Server」，和插件同规则）；别人装的缺模型 = 手动。包里中文文件名是 GBK，解压时还原；装前核磁盘空间（新码 `PERMANENT.DISK_FULL`，只出现在命令结果里）。在作者本机只读跑过：detect 认出正在跑的那份，install asr / capslock 都是「没动它」；自检函数对本机服务端真识别出「你好，这是语音识别测试。」。**没在真机上走过一次完整下载安装**（1.5 GB，待她：一步——找台没装过的 Windows 点一次）。
- **estimate**：价格表 `link_brain/pricing.json`（DeepSeek / 通义千问 / OpenAI / Gemini / OpenAI 转写 / 阿里 Paraformer、Fun-ASR，官方页 10-03 核对，查不到的 whisper-1 记 null；美元按 9-29 人民币中间价 6.7411 换；`~/.link-brain/pricing.json` 可覆盖）。量取自收藏库：概要用 extracted.json 记的 token、识图用 vision.json 每张真调过模型的 tokens、视频用 duration_sec；设置里配的模型在表里就按它算，否则按推荐。作者库（361 篇）算出每 100 篇：概要 qwen3.7-flash ¥0.08（DeepSeek ¥0.75）、识图 qwen3.8-flash ¥0.82、视频转写（用 API 时）¥0.47，问答一次 DeepSeek 约 ¥0.02。
- **backfill**：总数 = sync-status 的 last_favorites，已入库 = favorited_by 不空的篇数，还剩 = 上次同步的 deferred → 退到总数 − 已入库，预计天数 = 还剩 ÷ 每天上限向上取整（0 = 不限 → 1 晚）。
- 另：doctor 必需文件加 `setup-ui.js`（前端 aa62bcc）；pyproject 的 package-data 加 `pricing.json`。测试 `tests/test_setup.py` 26 例（本地假发布包 + 支持 Range 的小 HTTP 服务，不联网）；pytest 822 过。

## 2026-10-03 热修（分支 hotfix-scroll）：目录页 / 问收藏页滚轮偶尔滚不动 + 点来源后问收藏回首行

- 滚不动根因：图片导航（`media-nav.js` 与旧插件 `link-brain-native-media-nav` 同一段）每篇笔记往 `.markdown-preview-view` 挂一个滚轮监听、闭包攥着那篇笔记、到卸载才摘；Obsidian 同一标签页换文件复用这个容器，看过「钉住媒体」的笔记后再回目录页 / 问收藏页，旧监听把滚轮转给已脱离页面的 `.lb-scroll` 并 preventDefault。现在每个预览容器只挂一个监听（新旧两份共用挂点 `__lbMediaWheel`，后来的替换先前的），事件来时才现找容器里此刻钉住的笔记 / 光标下的图片，找不到不拦并清掉残留 `lb-pane-locked`；点图大图加 `defaultPrevented` 判断，两份同开不弹两层。旧插件 manifest 0.0.2。
- 回首行根因：问收藏的对话区是页内滚动容器 `.lbchat-body`，浏览器摘下再挂上元素会把 scrollTop 归零——第一次点「查看」/引用编号时 Obsidian 拆分标签页把本页 DOM 挪进新分栏；Dataview 重跑 `reuseDom` 也是摘下再挂回。现在 chat-view 记 `lastTop`（只记用户滚动），没有用户输入的「归零」不记、滚回原处（在底部跟随的回到底部）；打开来源后、layout-change、重跑挂回、尺寸变化时各确认一次。页头 / 输入框上滚滚轮也滚对话区。
- `lb-page-lib.restoreScroll` 加固：整页任何地方按键、触摸都算用户动了；同一容器新一次恢复先停掉上一次；结束摘监听。
- 测试：`tests/test_scroll_hotfix.cjs`（假 DOM 复现两处，修前失败）；`npm test` 21 过 0 败 4 跳；pytest 796 过；`test_annot_side.cjs` 照过。没在 Obsidian 里点过（待她：一步）。

## 2026-10-03 问收藏漏查 / 不准复盘（分支 batch8-search）

- 复盘她的真实提问（10-03 一次会话里连着换话题的 5 问 + 答案缓存和 09-18 验收里的提问，共 14 题 + 8 道工程补题；原题和结果只在本地报告里），逐题只跑检索看漏在哪一环（`tests/tools/ask_eval.py`，读真库只读，不调生成模型）。**主因是追问判断**：`_answer_qa` 以前「问题短于 18 字 + 有对话历史 = 追问」，把候选按上一问的结果重排；她换话题的短问题全被拖成上一问的东西（换了地方问吃的，前 8 还是上一问那个地方的；换成问某部小说，前 40 条候选全是吃的 → 挑材料挑空 → 答「候选收藏中没有符合」）。单独问时词法和语义其实都排在前 5。次因：跨词的虚字 2-gram（「的减」「宜的」「手的」）让 50 万字的超长附件到处混进前 8。向量层（semantic.db 6695 chunk 全覆盖）本身没问题，**不用重建向量**。
- 改法（`ask.py`）：候选排序抽成 `qa_matches(question, items, terms, sem, history)`（生产和评测共用）——这一问去掉指代词（第二个 / 详细 / 展开…）后还有话题词，且话题词是「标题 / 标签 / 分类里常见」的（`retrieval.term_stats`：小说 CP 名、地名这类大多在标题标签里；属性词如调料 2/24、步骤 0/50 不算）或问题不短 → 新话题，只按这一问检索、上文不掺进来（证据开窗也不再带上文的词）；「那 X 的呢 / 换成 X」这类换主语的省略式追问 → 上一问 + 这一问一起检索、先满足这一问的话题词；没话题（「第二个详细说说」）或只有属性词（「需要哪些调料？」）→ 追问，上一问的结果排前（主语取最近一个自己带话题的提问，不再把所有历史提问拼在一起）。`query_terms` 去掉含虚字的 2-gram 片段和单个虚字，「好吧 / 几个 / 一些」进停用词。挑材料兜底：小模型一篇没挑、但前 topK 里有标题/标签/分类/概要把这一问每个话题词都占了的篇 → 交给作答模型核对（结果带 `selection_kept`），库里真没有（话题词只在评论正文里）照旧答没有。
- 全文覆盖核对：词法 = 标题 / 标签 / 分类 / 概要 / 作者 + 正文 / 评论区（含楼中楼）/ 图片（本地 OCR + 识图，精细识图成功时替代第一层）/ 视频转写（含画面文字）/ 附件转出的 Markdown 全文；语义 chunk = 标题+标签+概要一块 + 正文 / 评论 / 图片 / 转写 / 附件（不含分类和作者，影响可忽略）。两边都没有的：她自己在笔记里的批注（notes.json，目前 3 条）和留言。
- 评测：真实 22 题 recall@8 0.712 → 0.839（连问那 5 题 0.457 → 0.893），词法-only 0.764；查询向量缓存后复跑 0 次 embedding。合成回归 `tests/test_ask_eval.py` + `tests/fixtures/ask_eval_synthetic.json`（14 例；旧逻辑 0.633、新 0.967）。BENCH.md 有复跑命令。

## 2026-10-03 10-03 小改（第 6 批）：目录页「本周同步情况」+ 机读版外链拆开（分支 batch6-tweaks）

- 目录页标题区：删掉第 4 批加的「上次同步 · 本次新收 · 还剩」那行（`.lbc-syncinfo`）；「N 篇 · 更新 …」那行可点（灰字不变、悬停下划线、提示「看本周同步情况」），点了 `LB.ensure('openWeekReport')`。问题入口照留。
- 「本周同步情况」窗口（新文件 `report-ui.js`，main.js 两行接入，doctor 必需文件已加）：最近 7 天按天一块——新收几篇；正文 / 机读版生成几篇；附件该有的下好几个、还缺几个、PDF/Word 转文字几个；识图 / 概要还差几篇；那天夜跑一句话（有问题带「看问题」→ 问题列表）；还没完成的列标题，点了同一窗格打开笔记（没正文的不给链接）。底部合计 + 「还剩 N 篇收藏逐晚处理」。
- 后端 `python -m link_brain report week [--days 7]`（`link_brain/report.py`）：只读本地（index.db 只读打开，没有就扫 meta.json），不联网。「那天新收」按 meta.json 的 `first_archived_at`（本机时区日历日）；附件「该有」= 有文件编号或已下到的，只是正文提到附件的线索不算；识图 / 概要差不差用 `enrich.needs`（夜跑补处理同一判断）。夜跑走完没有：有包内夜跑日志（`~/.link-brain/nightly.log`）按开始 / 结束标记判；没有（作者本机还在用仓外脚本）不判走没走完，只列那天登记的问题（problems.jsonl，设置换算 / 问收藏 / 远程阅读不算）+ sync-status.json 说得上的那天。
- 机读版（agent.md）「外链」里小模型建议的链接：以前 `- https://x.com（小模型建议：…）` URL 和全角括号粘在一起被 Obsidian 认成一整条链接；现在 `- [x.com](https://x.com) — 小模型建议：…`，URL 先按 `URL_RE`（到空白 / 全角括号 / 中文为止）切干净再去句末半角标点（`render.suggested_link_url / link_label`）。旧笔记要重渲染才更新：`python -m link_brain render --all`（agent.md 全由程序生成，没有手改内容；可见笔记照旧走保护手写的合并逻辑）。
- 远程阅读能看原图（GPT 实测：只回文本时「看得到图片路径 ≠ 看得到图片」，OCR 有小错）：新工具 `read_asset(path)` 回 MCP 图片块 + 一段说明（路径 / 宽高 / 字节）；`read` 读收藏对象里的文本（agent.md / 附件全文 / notes.json / 可见笔记）时带 `images: [{n, path, width, height, role}]`（取当前版本 manifest.json，缺了退回 vision.json，只列读得到的），`include_images=true` 顺带附前 N 张（默认 4、上限 8、一次总 12 MB）。图片白名单另走 `policy.asset_rule`：只开 `_archive/xiaohongshu/<id>/raw/vNNNN/assets/*.{webp,jpg,jpeg,png,gif}`（扩展名小写），规范形 / 文件系统两道照旧；用户开放文件夹里的图默认不开（`USER_FOLDER_IMAGES`，待主审定）；Pillow 打开核实是真图，超 4 MB 或长边 > 2048 等比缩到长边 2048 转 JPEG。read_asset 每次计一次每令牌限速，read 附图第二张起每张再计一次（超了不附、标 RATE_LIMITED）。工具描述写明「OCR / 识图文字只用来找，原图用来判」。测试 `tests/test_remote_images.py` 14 例。
- 测试：`tests/test_report_week.py`、`tests/test_render.py` 加 3 例、`tests/test_batch6_report_ui.cjs`；`test_batch4_ui.cjs` 的同步概况断言改成「那行没了」。pytest 781 过；`npm test` 19 过 0 败 4 跳。没在 Obsidian 里点过（待她：一步）。

## 2026-10-03 第 5 批（B2 插件侧接线）：后端命令 + LINK_BRAIN_VAULT / 首次引导 / 定时接包内夜跑 / 媒体导航并入 / Dataview 必装（分支 batch5-delivery）

- 后端入口：插件所有 Python 调用（spawnPy / runPy / 问答 worker）走 `pyChild` 一处，每次都带 `LINK_BRAIN_VAULT=<收藏库真路径>`。收藏库上一级或插件目录上两级是 LWA 仓库（有 `link_brain/__init__.py`）= 仓库模式，照旧 `python -m link_brain`、cwd 仓根（作者本机不变）；否则用设置「更多 → 运行环境 → 后端命令」（默认 `link-brain`，PATH 找不到再看 uv 的 `~/.local/bin`；Windows 只认 .exe/.com），调用点的 `-m link_brain` 自动去掉。找不到后端：不起进程，提示「没找到后端程序：先运行 `uv tool install link-brain`」，设置页顶部和启动提示都带「复制安装命令」。
- 首次引导（`onboarding-ui.js`）：这个库没走过引导、后端找得到、收藏库里还没有 `_archive` 才弹（作者本机不弹）。① 收藏存放位置（库根或库内子文件夹；存插件设置，后端命令模式顺手写 `~/.link-brain/config.json` 的 `vault`）② 读取组件（`reader status` 新增 `release_configured`；发布地址没配时按钮写「发布地址还没配置（测试版）」+ 手动放置说明，不调 install）③ 扫码（就是账号卡片）④ AI（跳设置页）。每步可跳过，状态如实；关窗 = 走过，命令面板「打开首次引导」可再来。
- 定时同步：任务名 LinkBrainNightly 优先 → 没有就旧任务 XhsFavSync（作者本机照旧管它）→ 都没有时「开启」= `sync-schedule --install --at <时间> --vault <收藏库>`（每周再 `--set weekly`），「关闭」不起进程。任务名经 env `LINK_BRAIN_SYNC_TASK` 传给 Python，读写逻辑没动。
- 媒体导航：`link-brain-native-media-nav` 的代码原样搬进 `media-nav.js`（只换外壳），main.js 两行接入；旧插件还开着时不接管（避免点图弹两层），设置页提示停用旧插件后重启。旧插件目录保留，manifest 写明已并入。doctor 必需文件加 `onboarding-ui.js`、`media-nav.js`；Dataview 行不再是可选项。
- Dataview：插件读 Obsidian 插件表判断没装 / 没启用 / 没开 JS 查询，启动提示一次、设置页顶部一块、打开目录类页面（页头 lb-page）时页面顶部一块，按钮打开第三方插件页（没开 JS 时打开 Dataview 设置）。
- 测试：`tests/test_batch5_delivery_ui.cjs`（假 spawn / 假 runPy）；`npm test` 18 过 0 败 4 跳；pytest 767 过。没在 Obsidian 里点过（待她：一步），没在无作者环境的 Windows 上走过安装流程。

## 2026-10-03 第 5 批（A 设置一致）：每日上限默认 / 测试按钮测实际执行器 / 定时触发器只改自己那个 / 设置页同步状态实时刷新（分支 batch5-delivery）

- 4.1 每天最多新抓：插件 `DEFAULT_SETTINGS` 200 → 50，和 `ai_config.DEFAULTS` 一致；规则一份两写（`ai_config.daily_new_limit` / main.js `dailyNewLimitOf`）：**0 = 不限**，空 / 乱填 / 负数 = 50。`favorites._Quota` 不再 `or 0`（以前清空 = 不限）。设置页说明写明 0 的含义；评论楼层说明改成「默认前 10 楼」（和下拉、ai_config 一致）。
- 4.3 测试按钮：「测试文本 AI」按问答页下拉**此刻显示**的模型测（`ask.chat_model_name`：activeModel 在列表里就是它，否则列表第一个——和 chat-view.js 同规则），结果写明测的是哪个；「测试识图」先跑本地 OCR（`vision.run_ocr`）再带着 OCR 文字问识图模型（`visual.understand`），两层分别报；识图模型没配 = 「识图模型没配（原因），只测了本地 OCR：…」（skipped，不算失败）；识图通但 OCR 关 / 失败不报正常（生产里没 OCR 文字识图那层不跑）。
- 4.4 定时（`sync_schedule.get_schedule / set_schedule`）：读全部触发器（JSON），认第一个间隔为 1 的每日 / 每周触发器（启用的优先）；保存只替换它（没有就追加），其余原样写回，写前核对触发器个数和那一个的类型，被别处改过就不动；每周的 DaysOfWeek 按位掩码解（旧代码会拿到数字）；认不出的显示「自定义触发器（…），未改动」、下拉默认「不改动」；时间格式不对直接报错，不拼进 PowerShell。「关闭」照旧 = 停用**整个任务**（关闭 = 不再自动同步；别的触发器也停但不删，改回每天 / 每周恢复），弹窗说明写明。单测全用假 PowerShell 输出（`tests/test_sync_schedule.py`）；读脚本在本机三个真任务上只读跑过、写脚本只做了语法解析，**没在真计划任务上执行过写**。
- 4.5 设置页（和账号弹窗）的「收藏同步」行：开着时监听 `_archive/sync-status.json` / `problems-summary.json`（vault modify / create，300ms 合并），关设置页（`hide()`）/ 关弹窗 / 整页重画时注销；同步中显示后端写的阶段（message），状态里有 `done / total / remaining` 才显示完成数 / 剩余——**后端现在没写这几个数**，所以眼下只有阶段文字。
- 测试：pytest 765 过；`npm test` 17 过 0 败 4 跳（playwright 没装）。`test_settings_layout.cjs` 加了 6–8 节，「一项不少」照过。

## 2026-10-03 第 5 批（B1 打包 Python 侧）：夜跑进包 + 自己注册计划任务 + 收藏库位置解耦 + 读取组件下载（分支 batch5-delivery，插件侧接线另派）

- `python -m link_brain nightly`（`link_brain/nightly.py`）：仓外夜跑脚本第 4 批改好稿的逻辑搬进包。步骤表 `nightly.STEPS`（11 步，限时 / 碰号 / 预留照旧脚本）、总预算 405 分钟、同步 exit 1 等 25 分钟重试一次、碰号步骤 exit 5 后跳过、exit 6 登记 ACCOUNT_BUSY、上一晚没走完登记 INTERRUPTED、同步占号卡住登记 SYNC_STUCK、每步失败登记 / 成功 resolve（`nightly.<步骤>`，slug 和旧脚本一致，问题记录接得上）、附件闸门缺附件退出 2。超时走 `procs.kill_tree`（放过 link-brain-reader 及其浏览器 + xiaohongshu-mcp / xiaohongshu-login；`LINK_BRAIN_KILL_EXCLUDE` 追加）。日志 `~/.link-brain/nightly.log` 边跑边写，>10 MB 转存。精细识图免费 key：环境变量 → `~/.link-brain/config.json` 的 `gemini_keys_cmd`（限时 60 秒、输出不进日志）/ `gemini_keys_file`，只注入那一步；取 key 失败记在 `nightly.gemini-keys`。报警不直调，全走 problems。另一趟夜跑在跑 → 退出 6（文件锁 `nightly`）。`--dry-run` 只打印计划。
- `sync-schedule --install [--at HH:mm] [--vault 路径]` / `--uninstall`：注册 / 删除计划任务 **LinkBrainNightly**（当前用户、普通权限、登录时运行；每天定点、错过尽快补跑、执行时限 7 小时、IgnoreNew、用电池也跑；动作 = 当前解释器旁的 pythonw `-m link_brain nightly --vault <库>`）。名字撞 XhsFavSync 直接拒绝。macOS / Linux 只返回 cron 行和 launchd plist。`sync_schedule.py` 里只追加了这些新函数，触发器读写没动（`--set` 仍按 LINK_BRAIN_SYNC_TASK / XhsFavSync 找任务，插件接线时要决定开源用户的 `--set` 指向 LinkBrainNightly）。
- 收藏库位置：`storage.vault_root()` = LINK_BRAIN_VAULT → `~/.link-brain/config.json` 的 `vault` → 旧默认「程序目录/vault」（作者本机不变）。`link-brain = link_brain.cli:main` 入口本来就有。
- 读取组件：`accounts.tool_dir()`（LINK_BRAIN_XHS_TOOL_DIR → config.json `xhs_tool_dir` → 默认 `~/.xiaohongshu-mcp`）；找 exe 顺序 `~/.link-brain/bin` → 程序目录 tools/ → 组件目录；relatedfile 同（`xhs.relatedfile_exe()`）。`reader install --url <包> --sha256 <hex>`：下载（https / file://）→ 校验 → 解压（防 zip-slip）→ `~/.link-brain/bin`；`reader status` 只看装没装。发布地址常量 `reader_install.RELEASE_URL` 留空。新码 `PERMANENT.CHECKSUM_MISMATCH / BAD_PACKAGE`（只出现在命令结果里）。
- 千问 CSV 默认目录：第 1B 批已删（text_stream 不再去任何作者路径），本批核实无回归。
- 测试：`tests/test_batch5_delivery.py`（假子命令跑夜跑；计划任务只验生成的 PowerShell / cron / launchd；本地 http.server / file:// 假包）。

## 2026-10-02 第 4 批：故障分类接进调用点 + 目录页顶部问题入口（分支 batch4-problems，叠在第 3 批上）

- 页面：目录页顶部「!」升级为问题入口：读 `_archive/problems-summary.json`，要你处理橙色数字、自动处理中 + 已放弃灰色数字、未开启不计数、都为 0 不显示；「· 同步中…」照旧；标题下一行灰字同步概况（上次同步 · 本次新收 N 篇 · 还剩 N 篇逐晚处理）。文件一变只重画这几个字，不重建整页。页面和插件都不再自己查 pid：以 summary 的 sync 段为准；看到「同步中」而插件没在跑任务时，请 Python 跑一次 `problems summary` 核对。
- 点开是问题列表（新文件 `problems-ui.js`，main.js 两行接入，doctor 必需文件已加）：分「等你处理 / 正在自动处理 / 已放弃 / 未开启」四组，每行时间 · 标题 · 标签 · 系统已做什么 · 次数 · 查看；登录 / 验证类带「扫码登录」「打开验证」（`fixFromCatalog(kind)`）；「复制报错」走 `problems export --plugin-version`，复制前已脱敏。卡片按 `it.problems` 出灰色小标（要你处理用醒目色），悬停看原因；状态文案只从 `state_registry` 取。
- 推送口径（主审定）：升级 STUCK 按「步骤」记一条（各篇同一原因连着 3 个日历日 → 一件事，顶部橙色 +1、推一次；这一步各篇都好了才解决）；key 失效 / 欠费（AUTH_FAILED / QUOTA_EXCEEDED）至少在 2 个日历日出现过才推（产品规则「连续几晚没修好」），第一晚只进列表。
- 夜跑脚本（仓外）配合：每步失败 `problems report --step nightly.<步骤>`、成功 `problems resolve`；汇总报警删掉；收藏同步 exit 1（非风控）等 25 分钟自动再试一次。报警出口 lwa-alert.py 加了 kind=problem。

- 17 处 `alert_mod.alert` 全部迁到 `problems.report`；`alert.alert` 改名 `_alert`（模块私有，仓内只有 `problems._push` 调，`tests/test_problems_alert_exit.py` 扫源码守住）。推不推只由 problems 判：NEEDS_HUMAN（掉登录 / 验证 / 风控 / 熔断 / 登错号 / key 失效 / 欠费 / 收藏数可疑）推一次，按「同一步骤 + 同一码」去重；账号类不管哪步撞见都记在 `login`；TRANSIENT / PERMANENT / SKIPPED 只记不推，TRANSIENT 同 key 连续 3 个日历日 → STUCK 推一次。
- 同步：结论由 `sync_state.record` 统一登记 / 解决（读取服务挂了、读收藏 500、连着几篇抓不到 = TRANSIENT；同步成功把收藏同步和账号问题都标已解决）；`account_problem / account_ok` 记 / 清 `login`。账号文案唯一源 = 登记表（`_ACCOUNT_MESSAGES` 删除）。`current()` 把「running 但进程已死」落盘成 INTERRUPTED，页面不再自己判 pid。sync-status.json 新增 `new / deferred` 两个键（旧键不动）。
- 附件转 md：PERMANENT（加密 / 损坏 / 不支持）同一份字节不再转；TRANSIENT（OCR 故障 / 超时）按 `conversion_failed.next_at` 退避 1 / 2 / 4 / 7 个日历日（到那天 0 点起可再转），第二晚的夜跑就会重试。下附件 / 附件补查的失败逐篇 TRANSIENT 登记。
- enrich：连着 3 次没补成不再报警、不再永久放弃——登记 `TRANSIENT.RETRY_EXHAUSTED`（action=gave_up）并按 2 / 4 / 7 天退避自动捡回来；以前已放弃（fails≥3、没有 retry_after）的下一晚就会再试一次。`--pending` 本来就会捡概要失败 / 从没生成过的。问答资料筛选失败记 `SKIPPED.FALLBACK`。
- 给页面：`_archive/problems-summary.json`（计数 + sync 段），catalog-data 顶层 `state_registry`、每篇 `problems`；CLI `problems list`（带 label / hover / group）、`problems resolve`、`problems summary`。契约见 CONVENTIONS §3「第 4 批落地」。
- 设置页收纳（作者拍板的方案）：第一层只留账号卡片 · 收藏同步（说明行 = summary sync 段的「上次 · 新增 N 篇 · 还剩 N 篇」，缺值不显示那段；定时… / 立即同步）· 每天最多新抓 · AI（问收藏用）的文本 AI + 三格 + 测试 · 「其他 AI 能力」一行摘要（点「展开设置」原地展开归档摘要 / 识图 / 视频画面文字 / 语音识别 / CapsLock）· 批注昵称；其余收进可折叠的「更多」（收藏同步细项 → 问答模型 → 外接 MCP → 电脑需求 → 下载文件夹 → 原「高级设置」全部原样）。只挪位置，存储键 / 默认值 / 保存逻辑不变；唯一删掉「搜索收藏 · 打开目录」一行。两处展开状态记在插件对象上（本次 Obsidian 会话内保持，不写 data.json）。`tests/test_settings_layout.cjs` 拿改前的设置项清单逐项对。

## 2026-10-02 第 3 批：用户操作的结果如实反馈 + 问答停止（分支 batch3-feedback）

- 问答：后端阶段（检索收藏 / 挑选材料 / 生成回答）经 `serve.py` 发 `{"type":"phase"}`，页面只显示这些；作答中有「停止」，走 `{"id","type":"cancel"}`：worker 用 `text_stream.CANCEL` 叫停——命令行模型整棵杀（`procs.kill_tree`，跳过读取服务）、HTTP 关流，回 `status=cancelled` 带半截，页面标「已停止生成」且不给收藏 / 导出；排队中的被取消就直接跳过；插件兜底超时也走这条，worker 8 秒不回才 `killTree` 整个 worker。
- 写盘失败如实说：问收藏页收藏回答 / 存判断 / 删 / 编辑 / 清空，批注删除 / 提交 / 编辑都是「写成功才改界面，失败回滚 + 『没保存上，内容还在，可重试：原因』」；批注提交失败撤回那条，重试不重复。
- 删除收藏：`remove.py` 逐条 try、`finally` 重建目录，JSON 加 `ok/code/message`、和退出码一致；页面只摘确认删掉的，没删掉的保持选中并说原因。回收站页头 `lb-page: trash`（`catalog.library_pages` 认旧版无标记页），菜单走 `openLibraryPage('trash')`。
- 投喂回写只把成功的那段链接换成 `[[笔记]]`，附言 / 其他链接原样，整行成功才打勾，导入期间新贴的行不动；附件原因与逐个错误拼接显示；挂附件退出码 2 的提示带原因。
- 人工验收第一轮的返工（她测的②④不过）：④ 的真根因在 worker：Windows 上读请求线程一直挂着同步读标准输入，预热线程此时载 numpy 等 DLL，DLL 初始化探标准输入被堵、攥着加载锁，新线程起不来——`cli_call` 卡在启动看门狗、提示词送不进命令行模型，直到插件再写一行（第一问空等到超时）。`serve._private_stdin` 让读线程读复制的句柄、进程标准输入换成 NUL（`tests/test_serve_stdin.py` 对照：不修就卡到被杀，修后 0.2 秒）。另外：命令行模型自己退出了、但它起的子进程还活着并拿着输出管道时，读循环会等子进程睡完，插件 150 秒先超时；那时模型已退出，看门狗也不收它的子进程。现 `text_stream._watch_cli` 活着时每秒记一次子孙，模型退出 2 秒管道还没关、或停止 / 超时时模型已退出，就按「记下的 + 父 pid 是它的孤儿」收尾（`procs.kill_leftovers`，pid 和创建时间都对上才杀，跳过读取服务）。插件兜底超时改为 `2 × textAI.timeoutSec + 60` 秒（`answerBackstopMs`），不再比后端短。阶段带真实条数：「检索收藏：共 N 条」「检索收藏：相关 M / 共 N 条」「挑选材料：从 K 条候选里挑」「生成回答：用 S 条材料」。排队那条多「↳ 立即发送」（停掉当前回答、马上问它），× 改叫「取消发送」。
- 验收：`tests/acceptance/20261002-batch3.md`。部署：拷插件 + `python -m link_brain catalog` + 重载 Obsidian（问答 worker 随插件重载重起）。

## 2026-10-02 第 2 批：减摩擦 + 页面状态恢复 + 来源阅读（分支 batch2-smooth）

- 共享前导 `link_brain/assets/lb-page-lib.js`（CONVENTIONS §5）：catalog.py 内联进目录 / 星标 / 问收藏三张页，并拼在 `_archive/annotate-view.js` 前面。Dataview 重跑时数据版本（catalog-data / 批注是 notes.json 的 mtime:size）没变就把旧 DOM 挂回，变了只换数据、卡片按 id 复用；5 MB 解析结果缓存在插件对象 `catalogCache`；页面状态（搜索词、筛选、多选、滚动、问答草稿）存 `sessionStorage['lb:<role>']`，换页回来恢复；藏着的编辑视图看不见时不渲染；`[lb]` 计时埋点。星标不再每次读几百份 notes.json（`note star` 顺手改 catalog-data）；catalog-data 加封面宽高。问收藏页草稿不再写 vault、去掉假进度轮播（只显示「正在生成…」）；来源只由引用编号 / 标题 / 「查看」打开，复用一个右侧窗格，「加入对照 / 退出对照 / 收起来源」是明确按钮，「单篇 / 对照」下拉删除。CapsLock 语音启动挪到窗口开好 3 秒后。验收和改前改后数字见 `tests/acceptance/20261002-batch2.md`。部署：拷 link-brain-actions 插件 + `python -m link_brain catalog`（页面脚本、annotate-view.js、catalog-data 新字段一起换）+ 重载 Obsidian。
## 2026-10-02 第 6 批：远程阅读（MCP，高级）（分支 batch6-remote）

- 新包 `link_brain/remote/`：只读 MCP over HTTP（mcp SDK Streamable HTTP，无状态 + JSON 应答），只监听 127.0.0.1；独立后台服务，不挂在 Obsidian 下——Windows 上「启用」注册计划任务 `LinkBrainRemote`（登录时启动 + 每 5 分钟看门狗，IgnoreNew），「停用」停掉并删除；macOS / Linux 手动 `python -m link_brain remote serve`。配置唯一来源 = 插件 data.json 的 `remote` 段（开关 / 域名 / 端口 / 文件夹），按 mtime 热重载；关掉开关或改端口服务自己退出（计划任务按新端口拉起，设置页也会主动重启）。
- 认证照私人桥的协议做法并收紧：OAuth 动态注册（回调只收 https 或本机 http）+ **强制 PKCE S256** + 口令批准页（scrypt；错 5 次锁 15 分钟）+ 授权码 5 分钟一次性 + 访问令牌 1 小时 / 刷新令牌 90 天轮换；另有「给其他客户端的访问令牌」（不过期、可单个撤销）和「撤销全部访问」。口令 / 令牌在 `~/.link-brain/remote/auth.json`，只存哈希，不进 data.json。Host 只认设置里的域名和本机，Origin 只认这几个来源，不发 CORS 头，每令牌每分钟 120 次。
- 工具只有 search（复用 `retrieval.rank_query` 词法 + 语义，只回白名单路径；用户加的文件夹逐文件匹配）/ read（分页）/ list；没有写入、执行、问答（lb_ask）。白名单三道：规范形（拒 `..`、绝对路径、反斜杠、`:`、空段、段尾点空格、设备名）→ 规则（`.` 开头、`_trash`、`_archive` 里除机读版 / 附件全文 / notes.json 外一律拒，只读 .md/.markdown/.txt）→ 文件系统（非链接 / 非联接点、单硬链接、realpath 与规范形逐字相等，挡住大小写 / 8.3 / 父目录链接）。
- 设置页：`obsidian-plugins/link-brain-actions/remote-ui.js`（整节在「高级设置」末尾），main.js 只两行接入。状态 / 出错原因 / 最近访问来自 `remote status`；新故障码 `NEEDS_HUMAN.PORT_IN_USE`、`PERMANENT.REMOTE_TASK_FAILED`（step `remote`）已登记。
- 部署要点：插件目录多一个 `remote-ui.js`（doctor 已把它列进必需文件）；不开开关什么都不跑。接域名由作者决定（插件不管隧道）。

## 2026-10-02 第 0 批公共件（分支 batch0-base）

- 插件唯一 Python 入口 `spawnPy`/`runPy` + 唯一杀树 `killTree`（跳过 link-brain-reader 及其浏览器，不再 `taskkill /T`）；读取服务经 `cmd /c start` 中转拉起、不再是任何 Python 的子孙（0929 根治）；`storage.file_lock`（账号锁是它的实例，目录重建 / answers.json / sync-quota 加锁）与原子写收口；`cli_call` 默认 180 秒超时杀树；`problems.py` 骨架（问题记录、分类、登记表、推送出口、`problems list|report|export`），未接调用点；`package.json` + `tests/run-node.cjs`。验收见 `tests/acceptance/20261002-batch0.md`。

## 2026-10-02 第 1B 批：provider 接口 + 收编 media.py（分支 batch1b-media）

- `providers.py`（resolve / key 顺序 apiKey→keyFile→env / HTTP 状态→故障码 / 统一返回形状）；`asr.py`（本机 CapsWriter-Offline websocket、OpenAI 兼容 `/audio/transcriptions`、关；长音频按静音切 ≤50 秒段）；`docconv.py`（PDF：pypdfium2 + 本地 rapidocr，Word：python-docx）。仓库外脚本、`LINK_BRAIN_MEDIA_PY`、本机默认 key 目录全删，PyMuPDF（AGPL）不再用。概要走设置里的「归档摘要模型」（summaryAI，默认同文本 AI），没配 = skipped；识图 / 语音 / OCR / 附件转换的失败和跳过都进 `problems.jsonl`。旧的 `mode=media` 配置在 `ai_config.load` 里内存换算（不改 data.json），记一条 `SKIPPED.LEGACY_CONFIG`。设置页每个能力块一个「测试」按钮，调 `selftest text|summary|vision|ocr|asr`。验收见 `tests/acceptance/20261002-batch1b.md`。

## 2026-10-02 第 1 批：搜索找回

- 目录页和 `link-brain search` / MCP `lb_search` 同一套规则（`catalog-search.js` ↔ `retrieval.py`）：原词（含 search-aliases 同义词）命中 = 精确；原词不中才认标题错字、拼音整音节（「西尼」→悉尼，「xin」撞不上 xi·ni，至少两个音节）、漏字，这些整篇放「可能相关」区排在后面；多词 AND；排序分数优先，星标 ×1.15，同分星标在前。整串短语库里没有时拆成库里有的词（「悉尼咖啡」「AI做梦」）。问答 BM25 只在某个词原词一篇都不中时退到拼音整音节（低权）。
- 目录卡片有查询词就显示命中摘录：按第一个有原文命中的词定位，标出来源（正文 / 图片文字 / 附件 / 视频转写 / 评论），关键词高亮；模糊命中写明「拼音相近 / 标题错字 / 漏字」。问收藏页的死代码 runSearch 删除。
- catalog-data：`pinyin` 改成空格分隔的整音节（标点处 `/` 断开），`pinyin_chars` 补 GB2312 一级常用字；图片检索文字在精细识图（refined）成功时用它替代第一层识图，问答检索和 embed 切块随之读到。只读已有 vision.json，不调模型。
- 回归：`tests/fixtures/search_queries.json` + `catalog-data.sample.json`（合成），`tests/test_search_regression.py` 与 `tests/test_catalog_search.cjs` 共用；真数据对照 `tests/tools/search_real.cjs`（读 env LB_REAL_CATALOG，只打印）。
- 部署要点：`python -m link_brain catalog` 重建（页面脚本和新格式数据一起换），再 `python -m link_brain embed` 补精细识图那部分的向量。搜索状态保存 / 恢复不在本批（第 2 批按跨模块约定 §5 统一做）。

## 2026-10-01 现状：防伤号 + 审计修复两批

- **现行做法（以本条为准，下文 0925 以前提到的 18060 / favdump / agent-browser 小号 / sessioncheck 均为历史）**：一个号、一个读取服务 `link-brain-reader`（默认 18061），读取、私密收藏、评论、附件都经它；掉登录或撞验证在 Obsidian「Link Brain Actions」设置页账号卡片扫码 / 打开验证，或 `python -m link_brain login`。目录分组按 tag + 设置里的「目录大类」关键词，`_archive/catalog-overrides.json` 从 0915 起不再读取。
- **批一 `f6adbd6` 防伤号**：读取服务统一识别风控页（登录异常跳转、验证浮层）并持久熔断，之后所有用号开页的请求拒绝，直到人工扫码 / 验证；关浏览器限时、锁看门狗；Python 侧展开 ExceptionGroup、首个风控即停（exit 5），跨进程账号锁（exit 6），任意两次开页间隔 20–40 秒；收藏同步篇间 60–180 秒、连败 3 篇停、默认每天新抓 50 篇、已在库的不重渲，识图 / 概要移到离线 `enrich`；收藏条数骤降报警；命令行模型锁工具、自带 key 不被覆盖；测试不碰真库、不起真浏览器。
- **批二 审计修复（分支 audit-fix-a / audit-fix-b，合入后以 git log 为准）**，b 分支：不可信文本 Markdown 清洗（`link_brain/mdsafe.py` + 插件 `neutralizeMarkdown`：agent.md、附件全文 md、问答回答、导出包、插件渲染都过，Dataview 代码块 / 行内 `=` `$=` 不再可执行）；问收藏把语义层命中的片段当证据（不再只送开头 + 结尾），资料筛选格式不对时退回普通检索（`selection_failed`）；catalog-data.json 去掉重复的 search_text（约 10MB → 5.5MB）；视频转写失败记原因，「没人声 / 没音轨」算完成，同一原因连败 3 次退避 7 天且不再让这步 exit=2；文档漂移更正（本条、TASKBOOK 第 0 节顶部、README）。
- 部署要点：插件 main.js 拷进 vault 后 Obsidian 重载；`python -m link_brain catalog` 重建目录页和数据；`render --all` 重写机读版、`pdf2md --all` 补洗旧附件 md。

## 2026-09-25 一个号、一个读取服务、一键扫码

实测（Owner 主号，同一持久浏览器目录、串行）：私密收藏 1077 条、评论（10 一级 + 7 楼中楼）、附件下载（sha256 与原件一致）全部走 `link-brain-reader`（xiaohongshu-mcp 扩展版，默认 18061）。旧的三套登录（读取 / favdump / agent-browser）合并为一个；agent-browser 附件路径删除。

「经常登录不了」的根因三条，均已修：①扫码等待期间轮询 `/login/status`，该接口每次导航会冲掉二维码（现只轮询内存态 `/login/session`）；②站点下发会话 cookie，浏览器每次调用后关闭即丢登录（现关闭前落盘）；③全新浏览器目录首页不自动弹登录框、游客态无旧 class 标记（现点侧栏「登录」出码，`loggedIn:false`/`guest:true` 满 12s 判游客）。另修：出码失败时浏览器不关、profile 锁不放导致整个服务永久卡死（现 45s 限时 + 任何失败必关）。

防卡住：安全验证（拼图滑块）识别即 `CAPTCHA_REQUIRED` 停车、不重试不自动通过，界面给「打开验证」窗口；收藏 10 分钟限频；扫码中其它请求 409 立即返回；每种错误码在 `accounts.SOLUTIONS` 里配原因、下一步和按钮。开发中短时间连读收藏约 10 次真触发过验证，已据此加限频。

界面：设置页顶部账号卡片（logo · 账号 · 状态胶囊 · 主按钮），收藏同步一行（定时 / 立即同步），AI、常用，其余收进「高级设置」。目录页同步失败显示「! 需要登录 / 需要验证」，点击直达修复。

未完成：扩展版读取组件未公开发布（开源用户暂无下载途径）；Obsidian 原生界面待 Owner 重载插件目视验收。Python 全套测试通过，Node 账号 / 目录 / 语法测试通过（4 个 playwright 用例本机未装 playwright 未跑）。

## 2026-09-24 P0 补验：目录同步状态与扫码反馈

同步结果写入本地 `_archive/sync-status.json`，目录篇数旁展示暂停/失败/进行中/成功；点击打开账号与同步窗口。状态检查先返回本地能力，再逐项验证账号；登录期间打开设置也显示操作状态。扫码页自动更新结果，读取组件暂时返回 500 时继续等待，避免程序提前退出、用户仍对着静态二维码扫码。结果保留在页面及设置区。

实机已读到目录「236 篇」旁的「⚠ 同步暂停 · 登录」以及账号弹窗。实际限量同步返回收藏登录失效，并落盘；测试时禁用 TG 通知。用户第一次扫码未保存成功，读取组件日志显示等待期间 500、最终超时，cookie 文件未更新。正在重新扫码验证；不能据此宣称单账号共用、不会顶号或同步已恢复。生产读取程序及原登录目录未替换。

## 2026-09-24 P0：首次使用与登录入口

新增 `doctor [--json]` 和 `login [xhs|favorites|attachments]`，Obsidian Actions 设置页顶部直接显示能力状态。doctor 区分基础存储、在线读取和可选能力，连接错误不会被判成账号过期；login 复用已有组件、打开扫码、验证结果。读取组件未启动可启动，`--install` 下载官方 Windows x64 程序；不改系统启动项、不替换已有生产服务。附件登录与下载共用目录并只关闭自己的 session；移除收藏/附件的作者绝对路径兜底。README 顶部改为 clone→安装→插件→状态→扫码→首篇归档的 Quick Start。

审计、游客真实 probe、干净环境 smoke 和验收边界见 [CAPABILITIES.md](CAPABILITIES.md)。读取/收藏/附件当前仍是三套能力状态，未宣称共用 session；单账号同会话附件下载尚未实现。私密收藏依赖的修改版组件尚未公开分发，陌生用户没有一键安装途径，界面如实显示可选未配置。实际手机扫码与 Obsidian 原生界面验收未完成。

验证：全套 Python 255 项通过，后续账号用例 15 项与相关回归通过；Node 账号按钮契约、worker、目录交互、静态资源语法通过。真实隔离环境验证官方读取程序下载、启动和二维码返回；真实附件登录态关闭重开保持有效。插件 main.js 已同步到 vault，需重载 Link Brain Actions 才运行新代码。没有改写插件 data.json，没有替换/重启原读取服务，没有提交实际登录态。

## 2026-09-24 Lot D：答案缓存

新增 `link_brain/answer_cache.py`：`vault/_archive/answers.json` 追加式索引（`{version:1, entries:[{id, ts, question, terms, item_ids, item_titles, export_path, first_line, vec?}]}`；vault 整体 gitignored，仓里没有任何回答样例）。`ask` 的 qa 路径模型成功出答后自动记一条（links/github 纯本地清单不记，模型失败不记）；`export_bundle` 带回答导出时按「同一问题 + ts 离 asked_at 最近（24h 内）」回填 `export_path`（vault 相对路径），回填失败不挡导出。写入走同目录临时文件 + `os.replace`；读到坏文件 = 空，写之前把坏文件挪成 `answers.json.corrupt` 留证再重新开始。

撞索引：只对无对话历史的独立提问做（追问依赖本轮上下文）。有语义层（semantic.db 在、查询向量拿得到，与 hybrid 检索共用 LRU，不额外发 HTTP）时，历史问题向量以 base64 float32 存在条目的 `vec` 里，同模型同维度才比，余弦 ≥ **0.80** 命中，且有可比向量时以向量为准不再词法兜底；否则 `cache_terms`（query_terms 去单字、去含虚字的二字切片、去可由 ≥2 个其它词拼出的整句块）Jaccard ≥ **0.60** 且共享 ≥2 词命中。命中时模型输入在【原始材料】前注入「上次问题+日期+当时用的收藏（优先当前标题，已删的用存档标题）+上次回答首句+此后新增的相关收藏（本次实际送进上下文的来源里 item.ts 严格晚于缓存 ts 的，带 [来源N]）」；回答开头由代码加一行 `> 以前问过类似问题（YYYY-MM-DD），本次结合 N 条新材料`（N=0 为「此后没有新增相关收藏，结论沿用」），流式时作为第一个 delta 先发。结果另带 `answer_cache` 元信息。UI / chat-view.js 未改。任何环节异常 = 当全新问题。

验证：`tests/test_answer_cache.py` 31 项（阈值正反例钉住、语义/词法两条路、新增材料筛选、命中/未命中/索引损坏三态、坏索引下模型输入与空索引逐字相同、追问不撞缓存、原子写失败保旧文件、导出回填、probe 入口；全 mock，不打真网）；`tests/conftest.py` 加 autouse 把 answers.json 指到 tmp，测试不碰真 vault。全套 pytest 238 passed。

真机探针（不改 cli.py）：`python -m link_brain.answer_cache list` / `python -m link_brain.answer_cache probe "问题"`（打印历史问题余弦/Jaccard 与是否命中，不调问答模型）。

遗留：真实「问两次相近问题」的端到端未跑（待主审）；0.80 余弦阈值按经验定，本机 `qwen3.7-text-embedding-flash` 上需用 probe 校准；词法兜底对只差地名的问法会误命中（上海/成都吃火锅 0.67）；answers.json 读改写无跨进程锁（serve worker 与 MCP 同时成功出答极小概率丢一条）；条目不设上限（每条约 6KB 含向量）。0921 前端 `writeExport`（答-<ts>.md）已无调用方，现行导出是 export-bundle zip。

## 2026-09-24 Lot E：星标主题

新增 `link_brain/topics.py` + CLI `python -m link_brain topic add "<名>" | list | remove <id|名> | rename <id|名> <新名>`（输出一律 `read.dump_json`；增删改名后默认顺手重建目录，`--no-catalog` 可跳过）。存 `vault/_archive/topics.json`（`[{id, name, keywords, created}]`，id 为 t1/t2…），读写 fail-open：缺/坏 JSON/坏条目 = 没有主题。`add` 走问答同一条模型通路（插件 textAI / answer_model，`text_stream.call`）扩关键词，模型输出当不可信数据：只从回复里抠 JSON 数组、只收 ≤24 字且字符白名单内的字符串、丢单字、casefold 去重、主题名打头、上限 10；模型不可用/输出不合规 → `keywords=[名]`。同名 add 幂等（status=exists，不再调模型）；改名不动关键词。

catalog 重建：`retrieval.score(item, keywords) > 0` 算隶属，写 `items[].topics`（名字列表）+ 顶层 `topics` 顺序表；不进 `retrieval.fields`、不参与检索权重。目录页 `catalog-view.js`：cats 栏下（仍在 sticky `.lbc-top` 内）加一排 `★ 名` 胶囊 chip，单选、再点取消、与大类 AND 叠加，「全部」一并清掉；选中时计数显示 `n / 总数`。没有主题时整行不建。瀑布流 / `.lbc-grid` / `.lbc-cols` 未动，不设 aria-label/title，主题数据走已有的 `lbPath('_archive/catalog-data.json')`，没有新增 vault 路径。

验证：`tests/test_topics.py` 21 项（模型全 mock：fail-open、恶意模型输出、CLI 全动作、catalog 集成、不进检索）；`tests/test_catalog_interactions.cjs` 加了假 DOM 真跑整页脚本的 chip 用例；另用临时脚本对比了 dccf662 版 `catalog-view.js`，无主题时两种数据形态下（初始 + 3 次点击）DOM 完全相同，新 CSS 只命中 `.lbc-topic*`。真 vault 实跑 `topic add "AI 记忆层"`：模型 5.2s 返回 10 个关键词，236 篇中命中 30 篇；Playwright 截图 chip 行正常、点击后 30/236。随后已 `topic remove t1` 恢复成无主题状态（`topics.json` 为 `[]`）。Obsidian 实机未验（待 Owner 过目）。

遗留：关键词没有 CLI 编辑入口（按「不做表单」只给了改名）；泛关键词导致命中过宽时，目前只能删了重建。

## 2026-09-24 Lot B：chunk 索引 + embedding 旁挂 + hybrid 检索

新增 `link_brain/semantic.py`：catalog-data.json 的 items 切 chunk（body/ocr/attachments/transcript/comments 按自然段合并到 200-500 字，另加 title+tags+summary 的 meta 块），存独立 `vault/_archive/semantic.db`（chunks + embeddings 两表，content-hash 增量；不动 index.db / catalog-data.json / ingest 链路）。CLI 新增 `python -m link_brain embed`（增量，`--all` 重算）。Provider 是 OpenAI 兼容 /embeddings；模型/endpoint/dimensions/查询超时在 `assets/llm-config.yaml` 的 `embedding` 节。key 取法与问答一致（env DASHSCOPE_API_KEY 或仓外 CSV），不落盘不打印。实测本机 key 的 MaaS 网关没有 text-embedding-v4（403 Unpurchased）、公网 DashScope 欠费，配置改用网关有的 `qwen3.7-text-embedding-flash`（dimensions=1024 实测可用）。

查询侧：`retrieval.rank_query` 升级 hybrid——semantic.db 存在且 query 向量拿得到（一次 HTTP，超时 5s，LRU 缓存 64 条）时，numpy 暴力余弦扫 chunk、chunk→item 取 max，与 BM25 做 RRF（k=60）混排，语义可召回词法零分的 item；`retrieve_payload` 里命中 chunk 的原文优先充当 excerpts 证据（meta 块不当证据）。fail-open 是硬约束：没 key / 没 semantic.db / numpy 缺失 / HTTP 失败/超时，全部退纯词法，行为与今天一致（有专门测试钉住）。

验证：改动前基线 18 题 recall@8 = 1.0（`vault/_archive/qa-20260924/retrieval-baseline.json`）；改动后词法与 hybrid 双跑数字见同目录 `retrieval-lotb-*.json`。fixtures 新增 8 题 paraphrase 集（`"set":"paraphrase"`，换说法探针，不冒充金标），bench 分开统计并同时输出词法/hybrid 两列。新增 `tests/test_semantic.py` 9 项（全 mock provider，不打真网）；全套 pytest 通过。未碰 assets js / serve.py / mcp。

遗留：夜跑挂载（在仓外 `xhs-fav-sync.ps1` 的 catalog 之后加一行 `python -m link_brain embed`，失败只告警不挡同步）尚未加；cats 检索权重清零等 bench 证明语义接住「搜大类名」再动（押后项照旧）。

## 2026-09-24 Lot C：MCP stdio server

新增 `link_brain/mcp_server.py`（`python -m link_brain.mcp_server` 启动），手写 MCP stdio
JSON-RPC（协议 2024-11-05：initialize / tools/list / tools/call），不加新依赖、不起 HTTP，
不改 `cli.py`（避让并行的 Lot B）。三个 tool：`lb_search`（转发 `retrieval.search`）、
`lb_retrieve`（转发 `retrieval.retrieve_payload`，不调模型）、`lb_ask`（转发 `ask.answer`，
description 里写明会产生模型用量）。stdout 只发协议 JSON（UTF-8 字节直写，绕开 Windows
控制台 GBK，做法照 `read.dump_json`），日志/异常走 stderr；工具异常包成
`isError:true` 的 tool result 或 JSON-RPC error，进程不崩、坏 JSON 输入也不崩。
vault 定位复用 `storage.vault_root()` / `LINK_BRAIN_VAULT`，未加新配置项。

已真实通过：`tests/test_mcp_server.py`（子进程真起 server，握手+tools/list+
lb_search/lb_retrieve 结构校验+空 vault fail-open+坏参数/坏 JSON/未知方法不崩），
`python -m pytest -q` 全套（本机 152 passed）。README 加了「把归档接给你的 AI（MCP）」
一节，含 Claude Code / Claude Desktop / Cursor 配置片段。

已知缺口：lb_ask 只做了「tools/list 里存在、description 标注会调模型」的验收，未跑真实
模型问答（按任务要求不打真网）；未接 Lot B 的 hybrid 检索（Lot B 落地后 lb_search/lb_retrieve
自动受益，因为都是转发现有函数）。

下一步：等 Lot B/D 合入后视情况要不要给 lb_ask 加流式（当前 MCP tools/call 走一次性返回，
`ask.answer` 的 `on_delta` 未接，够用先不加）。

## 2026-09-23 第二轮：钉选与导出规则修正

优先修复钉选：锁住外层阅读视口，图片/视频上的滚轮路由到正文；正文内部滚动隔离。证据跳转改为只滚动轮播或正文容器，避免 scrollIntoView 连带移动整个阅读页。高度在证据条插入后重新测量。无命中时不再显示提示/摘录框；图片证据仅显示第 N 张图。

目录文件角标打开本地附件（多附件显示选择菜单），视频角标交给本机默认播放器。问答导出限定所点问答与该回答引用的来源；不拼入 session 历史。资料包名：提问名_几篇_提问时间.zip；帖文件名：标题_作者_渠道.md。新提问记录 askedAt，旧问题没有时间则显式用“提问时间未记录”，不伪造提问时间。重复导出恢复原按钮，文件名冲突自动加序号；目录和问答均有复制文件包按钮，通过 Windows FileDropList 支持粘贴文件而非文本路径。

定向 Python 命名/重复/原图导出检查、证据定位浏览器检查、实际 wheel 事件的视频固定检查、页面导出重复/复制开关/视频角标检查通过。原生 Obsidian 和外部程序播放/粘贴仍未实机验收。需重载 Actions 与 Native Media Nav 两个插件。

## 2026-09-23 证据定位、图文资料包与侧栏整理

来源引用现在携带字段化摘录进入原生右侧阅读栏；正文、已归档评论、视频转写按连续原文匹配并短暂高亮，图片 OCR 由 vision.json 映射到本地原图。多处证据可前后跳转；无法定位时明确显示未定位并展开摘录（附件正文尚不支持原文件内定位）。旧回答若没有图片标识，会保留摘录回退；新回答返回图片标识。没有新增评论抓取或视频时间点定位。

选帖和回答统一提供 ZIP 资料包：完整 agent.md、原网页链接、本地路径、可选原图；回答包附答案与命中摘录。图片缺失记在包内索引。实际 Ombre 帖测试打包 16 张原图、零缺失，ZIP 可读取。导出从 … 菜单进入所在文件夹。加号移至 Collections 旁；问答 … 进入模型/提示词设置；导出图片选项折叠。

星标只写 notes.json，不再复制/删除正文；根目录 7 份历史副本（含 1 份与原文不同）已完整移动到 星标笔记/历史副本。移动前检查可见笔记内无指向这些旧路径的链接，文件名不变。个人笔记没有移动。移动记录在本任务 outputs/sidebar-moves-20260923.json。CSS 只隐藏本库 _archive、_trash 的文件树项目，数据未删除，回收站入口保留。

验证：全套 Python 171 项通过后，星标行为变更补跑 note/export/evidence 12 项通过；原生 API 模拟阅读分栏、目录交互、浏览器证据定位、亮暗/窄屏/瀑布流/追问/书签编辑/导出选项/挂载路径均通过；媒体浏览器回归通过。已同步插件和 CSS，重建 236 篇目录。仍未进行原生 Obsidian 实机验收；运行中的插件和问答 worker 需重载才生效。临时专题、微信、语音、视频时间点、评论深取未做。

## 2026-09-20 最新修复与交接

用户反馈全屏追问框截断、图片页码/箭头改坏、上下对照入口消失、已收藏不能取消。追问框现按实际pane可见高度计算；媒体按各自pane高度计算，适配右侧上下两篇。问答页增加显式单篇/上下对照入口，首次对照先填右上。图片撤销新增缩略图及下方工具条，恢复居中翻页与单份原计数；视频仍禁翻页覆盖，保留倍速。星标页再次点已收藏或全部返回普通目录。浏览器pane模拟、页面及媒体回归通过，原生实机待用户重载验收。

余项按用户要求交接到 `<作者本机私有工作区>`：＋移标题右侧及图标对齐、AI专属…菜单模型/提示词、语音输入与快捷键、灰色计数在标题内居中、确认多标签筛选意图。不要把这些未做项当完成。

## 2026-09-20 瀑布流滚动修正

根据用户实机反馈，去掉目录固定视口高度和卡片区内部滚动。恢复整页自然向下延伸的瀑布流，顶栏/搜索/分类通过sticky吸顶。目录与星标页已重建；不再采用下文“只有卡片区滚动”的旧方案。

## 2026-09-20 第二轮界面反馈

已部署：视频小图标与文件角标对齐；目录星标仅悬停/键盘聚焦可见（触屏保留可点）；移除卡片三点，右键管理仍可用；「已收藏」进入独立星标收藏.md纯文本目录；移除导航tooltip及清空对话入口。回答空心/实心书签切换收藏，双击正文编辑，追问框下移并增加间距。

媒体：确认用户指的是CSS轮播翻页箭头，已删除该覆盖层而保留视频原生播放控件。视频仅显示视频帧，不再翻到重复封面；倍速按钮点击循环、水平拖动连续调速。图片默认位置锁定，右上pin可解锁；页码点开缩略图，直接跳任意张，前后按钮可首尾循环。改动在 link-brain-native-media-nav 插件，需重载它和Link Brain Actions。

页面亮暗/390px/双路径、星标悬停、书签切换、双击编辑、纯文本目录浏览器验证通过；媒体锁定位置、12张直跳/循环、视频无翻页覆盖、点击及拖动倍速验证通过。实际Obsidian交互仍待用户重载后验收。本轮仅目录Python定向4项及相关Node/浏览器检查；未重复跑不受影响的全套后端。

长评论研究：203篇审计快照的评论图片总数0；默认导入前10楼；reply_limit实际是超过阈值跳过整楼，现有全量适配器100会跳过几百回复楼；Go Comment结构与Python归一化均未保留图片。拟仅对指定帖深取，调高一级楼数与回复跳过阈值、补MCP图片字段、复用现有下载渲染；尚未实际深抓或更改MCP。详细调查在本次任务outputs/长楼层与评论图片调查.md。后续重建目录为202篇，用户期间可能有正常删改，未覆盖其归档操作。

## 2026-09-20 目录和检索交互

后续摘录核查发现：旧窗口会被AI/系统泛词抢占，曾误把Non附件和Ombre图片中已有的做梦机制说成未披露。已将摘录按具体主题、窗口稀有度、命中标题段排序，并保留预算内短作者正文。Non的checkDreamTick门控与Ombre共振设置现可取到；新增4条回归测试，连同相关检索/问答共36项通过。新真实问答见本任务 outputs/dream-search-verified.md，替代此前演示结果。没有重载用户正在查看的页面；运行中的stdio worker须自然退出或重载插件后才使用新Python代码。

已部署源和 vault 页面：目录星标与正文 notes.json 联动并排前、视频/附件/收藏过滤、固定顶栏搜索分类、统一问答入口、底部追问、右上已保存、回答/笔记编辑、来源绝对路径复制。引用及带引用文本块调用原生右分栏并复用，来源「上下对照」复用右侧下栏；阅读区图文评论上下排列。新增可自定快捷键的「跳转目录并搜索收藏」命令。视频中央播放覆盖按钮 CSS 隐藏，底部 controls 保留。

检索取消硬编码600字限制；相关主题也参与重点来源筛选，回答要求原文细节与短摘录，来源返回字段化原文片段和本地正文绝对路径。重点项证据窗口扩大，仍守原有总输入和输出预算。真实做梦主题问答返回1282字、未截断；具体引用结果保存在本次任务 outputs/dream-search.md。

全套pytest通过；随后证据窗口修改后定向30项通过。Node交互、worker、分栏复用测试通过；浏览器页面亮暗/390px/两种挂载路径以及收藏、固定搜索、引用、编辑和保存通过。已复制插件、重建203篇目录并同步CSS。原生Obsidian分栏/视频交互未实机验收，需重载插件再确认；黑色箭头按视频中央覆盖控件处理，是否正是Owner指的箭头尚未实机确认。保留本轮开始前的大量未提交改动，没有混合提交或推送。

## 2026-09-18 六项优化收尾（优先于旧记录）

①回收站：后端/页面/恢复/墓碑与实际删除恢复通过；完整外部夜跑和原生UI未验，标部分。
②视频：27条MP4全部下载、ffprobe均h264，共637.01MiB；新RAW版本引用旧图片、复用其OCR。1条真实本机转写并纳入检索；3条实机播放/拖动和LER验收待做，标部分。
③纯＋样式完成。④BM25、密集原文片段、常驻stdio、DS Flash流式已接通；18题暂定召回94.44%→100%，热首字约1秒，冷2.882秒；没有成功的旧模型速度基线，标部分。⑤Fable --ask/--full CLI完成，共用检索、不调用模型。⑥统一两页工具栏，浏览/问答分开；普通文字直接提问，保存/复制与来源折叠；管理进…，加号保留纯＋。

全套159项pytest通过，随后新增1条转写检索/字数预算/不调模型测试并定向18项通过；共160项。Node交互、worker崩溃重启、浏览器旧回归及新页面亮暗/390px/双路径验证通过。证据在 `vault/_archive/qa-20260918`，截图在本任务 outputs，浏览器截图不是Obsidian实机。已复制插件源并重建页面；运行中的Obsidian须Ctrl+P重新加载才可验证新插件。

Owner已确认手机排除MP4；电脑无Remotely Save配置可代改，手机需在插件的排除路径正则中加入 `\.mp4$`。Obsidian排除文件另加入 `_trash`（LER用 `知识库【小红书】/_trash`）。仅本地提交，无推送；密钥只从Owner指定仓外CSV读取，仓内没有密钥；本轮不做SHA匹配。卡片由CC回写。

## 2026-09-18 六项优化：①回收站

已接通 delete → _trash + tombstones、恢复/彻底删除/清空、手动导入提示和夜跑屏蔽。路径使用 lbPath，插件已复制、目录已重建。真实 vault 删除恢复日志：`vault/_archive/qa-20260918/trash-roundtrip.json`；批注未变，孤儿已移走。新增三条 pytest + 原全套 147 项、两套 Node 通过。外部完整夜跑与 Obsidian 实机尚未验收，因此①暂标部分。仅本地提交；无 SHA 匹配、无密钥变更。①提交 `7d72200`。Obsidian 截图/输入工具分别报 `0x80004002` / `0x80070057`，未完成实机验收。②批量下载前按「问她」暂停，待确认手机是否排除 MP4。

Owner 设置：Obsidian 重载 Link Brain Actions；排除文件加入 `_trash`（LER 库用 `知识库【小红书】/_trash`）。给 CC 更新卡片的要点：回收站入口；CLI `delete <id>`、`trash restore <id>`、`trash purge <id>`、`trash empty`；彻底删除仍屏蔽同步，恢复解除屏蔽。

## 2026-09-16 本轮收尾与交接（优先于下方旧记录）

Owner 要求：完成难点后交接余项，额度有限；不做 SHA 匹配，不推远端。以下基于当前代码和实测，不沿用旧版“问 AI 仅摘录”的描述。

### 已实现

- 普通文字 Enter 搜收藏，`/问题` Enter 调真实文本模型回答；支持继续追问、折叠来源、正文复制。普通搜索不调用模型。
- 中英文别名（音乐/music/音、菜谱/recipe 等）+ 模糊/拼音搜索；自然语言分词。权重：标题 12、标签 10、正文 7、附件 Markdown 6、OCR 5、评论 3、摘要 2、作者 1。别名为显式词表，并非任意中英文语义翻译。
- 统一界面字体；保留加号，只去其外框；文件图标改 SVG；标签末尾 …、分类右键编辑/隐藏/调整顺序；另有 `vault/收藏搜索.md` 简洁页。
- 正文顶部长链接移至内容下方；机读 Markdown 包含实际附件文件与附件 Markdown 链接。
- 附件面板支持拖入、选择文件、配置下载目录、推荐匹配。打开原网页后监看新下载的同名稳定文件，挂载→转换→重建目录；停止/关闭/超时终止监看。提示用户关闭浏览器标签，不自动关闭用户浏览器。
- `ask --request-stdin` JSON：question/history/include。默认 `delivery.body`；include 可选 links/files；调用方继续传返回 history。文件含真实本地路径和 Markdown 路径，链接取自归档记录，不让模型编造。README、FORMAT 有接口说明。未接入微信账号或新增 HTTP 服务。
- 附件状态逐文件核对，部分下载不再显示全部完成；自动补跑失败保留原因，浏览器自动流程 finally 关闭它自己的会话。
- 仓外 `%USERPROFILE%\.xiaohongshu-mcp\xhs-fav-sync.ps1` 已改 UTF-8、审计附件、传递未完成退出码。此文件不随本仓提交。

### 转 Markdown 的实际链路

`pdftext.py` → `media.py pdf --no-ocr --out` 先抽文字层；乱码/扫描件才逐页 `vision.run_ocr` → `media.py image --ocr` → CMX。当前 OCR 配置 cmx；运行服务源码 `D:\AI\PI-Personal-Instance-OS\mcp\src\cmx_mcp\ocr.py` 默认使用 `D:\AI\models\rapidocr` 的 PP-OCRv6 ONNX。docx 走 media.py 的本地文字提取。没有用本次 Codex 对话逐页转录。

注意：CMX 既有 `/files/recognize` 还可能调用其配置的云端描述服务；`--ocr` 选取 local.text 输出，不等于该服务完全不调用云端。没有改外部 CMX 服务或新增 SHA 逻辑。

PDF 不再静默截断至 50 页；任一页 OCR 失败即报告转换失败，不把部分文字当完整成功。附件文件更新时间晚于 Markdown 会重转，无需 SHA 比较。

### 本机证据与边界

- 160 篇目录；21 个已确认附件均有文件与 Markdown，3 条只有正文线索（无 doc_id）未解决。`python -m link_brain attachments --audit` 可重查。
- 已补转此前缺失的 5 份 Markdown；已从 Downloads 挂载 `扒 system prompt.docx` 并转换、重建目录。
- 真实 PDF 一页 OCR 成功（845 字）；真实模型菜谱问答、追问成功；真实 stdin API 请求返回 WrenWen 的 1 个来源链接和 PDF 文件。
- 实际 Obsidian 曾通过弹窗打开、998 个本地候选扫描、加号边框 0px、无横溢出验证，证据 `vault/_archive/ui-verify.json`。最终代码又已复制到 vault；关闭重开目录可刷新视图，插件最新模块需在 Obsidian 禁用/启用 Link Brain Actions 后加载。
- 新浏览器 DOM 测试覆盖 Enter/AI追问/390px布局、下载监看不误收旧文件、稳定文件挂载与失败反馈。实际浏览器从打开网页到人工下载完成的全流程尚未人工验收。

最终验证：Python 全套 **147 passed**；两组 Node/浏览器测试均 PASS；夜跑 PowerShell 语法解析通过。

### 接手只需做这些（不扩架构）

1. Obsidian 禁用再启用 Link Brain Actions，打开收藏搜索/原目录，按真实使用检查视觉、标签编辑、拖入文件和多轮问答。
2. 对 3 条无 doc_id 的线索人工查看原文；找到附件后拖入对应条目。不要假定有文字提及就一定有可下载附件。
3. 下一次 XhsFavSync 计划执行后核对日志和退出码；新脚本未经历下一次真实夜跑。确认失败/未完成能在设置中看见。
4. 微信等渠道后续调用现有 stdin JSON 接口，只展示 delivery，发送文件时使用 files.path。外网设备不能直接读取本机绝对路径，需要渠道发送器实际上传；这部分本轮未实现。
5. 转换失败已有即时告警/退出码；若需要在关闭弹窗后继续展示转换错误，尚可补附件持久状态。目前持久状态主要记录自动下载错误。


## 2026-09-16 附件：夜跑自动下 + 卡片角标 + 头部未同步 + 头部对称

- **附件角标**（Owner：有文件标有文件、未下载标 logo）：目录卡片右上角 `待补→「📎 未下载」(橙)`、
  `downloaded→「📎 文件」(灰)`；数据来自 catalog-data 的 `attachment` 字段。待补卡右键加「下载附件（要开浏览器）」。
- **头部「X 篇未同步 · 补跑」**：toolbar 显示待补篇数，点击跑 `attachments --all`（headed，会弹浏览器）。
- **夜跑自动下附件**（Owner：登录态脚本能跑，加到夜跑）：`xhs-fav-sync.ps1`（仓外）在 catalog 后加
  `attachments --all` 自动补下（headed agent-browser 小号；任务 LogonType=Interactive，凌晨她登录会话里能弹窗下）。
  失败不致命；补完仍扫残留记日志。
- **头部对称重排**（Owner：排版丑/不对称）：真因是 `.lbc-sub` 和 `.lbc-import` 各有 margin-left:auto、
  把「更新/全部/今日」挤到中间、左边空一块。改成**左=全部/今日，右=计数·更新+未同步+导入**；
  搜索框去掉 660px 上限填满。
- **大类改单选**（一次一个）、**图片放大 bug**（封面 pointer-events:none 点击穿透开笔记）见上批已修。

catalog-view.js 本地提交（未推 github）；node PASS。

## 2026-09-16 开源上传 + 大类单选 + 图片放大 bug

- **大类筛选改单选**（Owner：标签别同时点，一次一个）：`activeCat` 单值，「全部」或再点当前项清空。
- **修卡片点击被图片放大截走**（Owner 报）：点卡片本应开笔记，却被 Obsidian 阅读视图的**图片放大**抢了——
  封面图 / 小图 `pointer-events:none`，点击穿透到卡片/缩略图容器的 onclick。
- **开源上传**：加 **MIT LICENSE**（© CyberMist）+ README 许可说明；`git push origin main` 推到
  github.com/CyberMist123/light-web-archieve（PUBLIC），一次推 20 个提交，pre-push 密钥闸放行、无泄漏。
  上传前审计确认 git 不跟踪任何 data.json/key/cookie/vault。

## 2026-09-16 反馈批 4（多选退不出 / 旧链接留言 / 删TTS / 大类恢复 / 巡检周期）

- **多选退不出（真因）**：`.lbc-selbar{display:flex}` 盖过 `[hidden]`，`selectMode=false` 后条也不消失。
  修：`.lbc-selbar[hidden]{display:none!important}`。并按 Owner 要求**去掉顶部「多选」按钮**，
  改成**右键菜单「多选删除」**（预选当前卡）；退出靠「退出多选」按钮或 **ESC**（ESC 监听器跨重渲染去重）。
- **旧链接留言清理**：`render.strip_auto_link_comment` + CLI `tidy-comments` 扫全库，去掉纯链接的自动 cmt1。
  实跑清了 4 篇（含「明日方舟×P3」）。只动自动生成、去链接后没剩真话的 cmt1，手写留言不碰。
- **删 TTS**：卡片朗读去掉后 TTS 无消费者 → 删设置页 TTS 段 + `speak()` + tts 配置（不留空壳）。
- **大类误删恢复**：她在设置里把大类编成一行「生活，娱乐」盖掉了内置 → 把 data.json 的 catalogCats 清空回内置 12 类。
- **巡检周期可设**：`sync_schedule.py` + CLI `sync-schedule [--set daily|weekly|off]`（改 Windows 计划任务
  XhsFavSync 的触发器/启停，PowerShell ScheduledTasks，只换触发器不重建；无需管理员实测通过）。
  设置页加「每晚收藏巡检 · 频率」下拉（每天/每周/关闭，载入当前值）。**巡检本体确认健康**：XhsFavSync daily 04:00。
- 插件 manifest 描述更新到 0.2.0（提瀑布流/大类/模糊检索/问AI/删除/巡检）。

测试：test_remove 加 strip 留言用例；全套 **134 passed + node PASS**。

**Owner 给的后续路线图（还没做，记着）**：① 其他网页导入（B站等，非小红书 adapter）② 视频识别 + 存储
③ 笔记 tag 管理功能（更顺手的批量/全局标签管理）。开源必备的 **LICENSE 还没加**（问过她用不用 MIT，待她定）。

## 2026-09-16 反馈批 3（Owner：红按钮 bug / AI 慢 / 回答改小图+原文）

- **多选删除的红按钮文字看不见**（我引入的 bug）：`.lbc-selbar button.mod-warning` 设成了红字红底
  → 改成白字实心红 + 计数「删除选中 (N)」+ 无选中时禁用。
- **AI 检索慢（真因找到）**：不是模型本身——是她 data.json 里存着旧的 `expandTerms:true`（上一版默认），
  每次问答都多跑一次 ~15s 的「扩检索词」模型调用。改法：`expandTerms` 默认改 False（ai_config + main.js），
  并把她 data.json 的这个值改掉。实测 `ask "吃鸡的菜谱"` 从 **15.3s → 0.01s**。
- **/问AI 回答改形态**（她要的）：不再要「我的推断/补充说明」那套分析。qa 默认**纯本地检索**出
  **小图（封面，点击跳笔记/xhs）+ 选取的原文摘录**（`_local_excerpt` 截命中处原文，不改写不概括）；
  **链接不进正文**，只在**复制结果**时按设置附上「正文 + 本地路径 + xhs链接」。
  设置新增「回答形态」：用模型挑摘录(默认关)、摘录字数、复制附 xhs / 本地链接开关、本地链接形式
  （obsidian:// 深链 / [[wikilink]] / vault 路径）。ask.answer 返回 `kind:"cards"` + results[{id,title,cover,note,url,excerpt}]；
  github/links 意图仍走 markdown。DEFAULT_ANSWER_PROMPT 改成「只挑原文摘录、输出 JSON、不分析」（仅 useModel 时用）。

测试：test_ask 的 qa 用例改成卡片（默认无模型 / 开模型挑摘录 / 模型失败退本地）；全套 **133 passed + node PASS**。

## 2026-09-16 反馈批 2（Owner 5 条）

1. **URL 尾巴粘中文识别不出**（真 bug）：分享文案常把「…&xsec_source=pc_share增加的内容」中文直接粘在链接后，
   `URL_RE`（xhs.py）+ 插件 cleanLinks 正则原来不在 CJK 处截断 → 把中文吞进 URL、整条废掉。已给两处正则
   加 CJK / 中文标点 / 全角区排除。实测她那条 rednote 粘尾链接现在正确截断 + 清参数 + token 完整。
2. **附件短链留言很烦**（图1）：投喂时附言只是分享链接 → 之前在留言层留一条 `「日期 人」<短链>` 的 cmt1 噪音。
   `render._is_link_only` 判定「去掉 URL 和小红书模板句后没剩真话」就不生成 cmt1（留言层留给真正的话）。
3. **卡片 hover 浮框**（图2 那个带尖角的「悬浮的点的字」）：真来源是 **Obsidian 把 `aria-label` 渲染成 tooltip**，
   上轮删 `card.title` 不够——已把卡片 aria-label 也去掉。
4. **右键删除 + 多选删除收藏**（她要的）：新 `python -m link_brain delete <id...>`（remove.py：删可见笔记 +
   对象目录 + 索引行，外键 cascade，删完顺手重建目录）+ 插件 `deleteItems`。目录页：右键出小菜单
   （编辑标签 / 删除收藏）、toolbar「多选」进多选模式（点卡=勾选、选中描边、「删除选中」批量），
   删除走 window.confirm 二次确认、删完本地从 items 摘掉即时重渲染。**导入按钮保留**（她上轮说原本挺好）。
5. **检索失败要有 error**：`/问AI` 失败从一行小字改成醒目 error 框（`.lbc-ai-error`，标题「⚠ 检索失败」+
   原因提示「文本 AI 未配置/不通、后端未起」+ 问题保留可重试）。

测试：新 `test_remove.py`（delete 删文件+索引 / 删不存在 / URL 粘中文截断 / catch 认粘尾链接 / 链接-only 附言不留 cmt1）；
`test_catch.py` 已有 rednote 断言；cjs 补 deleteItems 解析。全套 **132 passed + node PASS**。main.js 同步 vault、目录重建。

## 2026-09-16 修正批（Owner 反馈）

- **「+ 导入」按钮恢复**：上一轮误把它从目录页拿掉了，Owner 说原本挺好——已还回 toolbar（连旧插件实例
  缺 openImportModal 时 disable/enable 恢复的逻辑一起）。
- **去掉卡片悬浮 tooltip**：删了 `card.title`（那个 hover 时冒出来带尖角的浮框，她不要）。
- **补掉真正的漏：catch.py 的 `XHS_HOSTS` 缺 rednote.com**——她的分享链接大多是 rednote 域，之前
  JS 放行了但 catch 检测不到、投喂得 0 条。已加 `rednote.com`（`test_catch.py` 加断言锁住）。
  （SHORTLINK_HOSTS 只管 xhslink 短链、不用动；xhs.py 的 NOTE_ID_RE 本就认 /discovery/item/。）
- **每晚自动收藏核对无碍**：`XhsFavSync` 计划任务 Ready、昨晚 04:00 跑成功(result=0)、今晚 04:00 再跑；
  夜跑脚本 `清 slate → sync-favorites --extract → catalog 重建 → 附件缺字节质量闸`。我这几轮没碰 favorites.py，
  catalog/llm 改动全 fail-open 兼容，这条链没被连累。

## 2026-09-16 目录大类筛选 + URL 清洗规范 + 导入进度条（本轮追加）

Owner 追加的一批 UI/清洗需求，都做完：
- **URL 清洗按规范**（她写的 spec）：`xhs.clean_url` / `clean_share_text`（新）+ CLI `python -m link_brain clean`——
  短链 `xhslink.cn/.com` **跟随 redirect 换最终长链**、保留 host+path 原样（不改 /explore、/discovery/item）、
  query 只留 `xsec_token`/`xsec_source`（source/xhsshare/app_platform/share_id/track_code/apptime/author_share/shareRedId 全删）、
  `xsec_token` 完整不截断、**没 token 就如实标 has_token=False 绝不拼裸 note_id**。插件 `cleanLinks` 白名单**补上 rednote.com**
  （她的分享链接大多是这个域，之前被丢）；「清洗链接」按钮改走 Python（真展开短链）。
- **目录页大类筛选条回来了**（09-16「收藏墙调整」把它藏了）：`catalog-view.js` 顶部小红书式 tab，
  **灰竖线 `│` 分隔**（`.lbc-cat-sep` 用 border 色），多选=**「或」**（命中任一大类即显示），「全部」清空。
  数据用 catalog-data.json 已有的 `cats_order` + 每篇 `cats`。
- **隐藏「+ 导入」按钮**（她要的）：目录页不再放导入入口（导入仍在命令面板/ribbon/设置里）。
- **导入进度条**：ImportModal 加动态进度条（`importText` 多一个 progress 回调，逐条 done/total 填充）。
- **设置页可编辑大类**：文本框「名称: 关键词1, 关键词2」逐行（好编辑），「载入当前大类」按钮读
  `catalog --print-cats`、「清空用内置」、「重建目录使其生效」三个按钮 + 提示（改完要重建才生效）。
  存 data.json 的 `catalogCats`；`catalog.effective_big_cats()` 读它、空则用内置 `BIG_CATS`（fail-open）。

测试：`test_ask.py` 追加 5 例（clean_url 只留 token+source / 无 token 不伪造 / 跟随短链 / clean_share_text 去重+白名单 /
大类覆盖）；`test_catalog_interactions.cjs` 补 rednote 清洗、parseCatsText/serializeCats、进度回调、expandAndCleanLinks，
删掉已移除的导入按钮那段。全套 **126 passed + node PASS**。main.js 同步 vault、目录已重建（cats_order 12 类）。

## 2026-09-16 知识库 /问AI + 插件设置 + 开源移植（本轮做完）

**/问AI 真接模型了**（不再是「未接入」占位）：
- 后端 `link_brain/ask.py`（新，CLI `python -m link_brain ask "<问题>"`，输出一行 JSON）：
  读整个本地 `catalog-data.json` **自己重新检索**（不依赖页面传来的 shown），只把挑出的少量片段送模型。
  **先规则后模型**：`提取github地址` / `所有…链接` 纯本地出（0 token，给真实计数 + 完整可点链接列表）；
  普通问题可选一次小模型扩检索词 → OR 召回排序 → 取 topK(8) 篇、每篇 ≤fragChars(800) 字、
  总输入 ≤totalCharLimit(8000) 字 → 一次回答。模型调用复用 `llm.call_media_text`（media 模式）
  或自定义 HTTP（httpx，OpenAI 兼容）。实跑 156 篇：`提取github地址` 出 5 个真实地址；
  `AI记忆系统相关…` 命中 20 篇、送 8 篇、返回结构化 markdown（笔记出处 + URL + 分析）。
- 插件 `answerArchive({question})` 改成薄壳：spawn `ask` → 解析 JSON → 用 Obsidian `MarkdownRenderer`
  渲染（`[[笔记]]` / `[原文](url)` 可点）+ **一键复制完整 markdown**（复制不重调模型）+ 材料/命中计数 + usage；
  配了 TTS 才出现「🔊 朗读」。只点「提问」才发请求，打字不花 token。
- **插件设置页**（`LinkBrainSettingTab`）：文本AI（media / 自定义HTTP：endpoint/model/key/maxTokens）、
  识图OCR（cmx/qwen 通路，接 `vision.py`）、TTS（endpoint/model/key/voice）、两类提示词（摘要 / 搜索回答，
  各带默认与恢复）、检索/token 上限。每条接口有「测试」按钮走真实最小调用（`selftest text|ocr` + TTS 朗读），
  **不做空壳**。数据只落 `vault/.obsidian/plugins/link-brain-actions/data.json`（gitignore，key 不进仓/不打印）。
- **摘要提示词真接 `llm.py`**：`extract` 读 data.json 的 `prompts.summary`，留空用内置 INSTRUCTION（fail-open）。

**开源移植（Owner：本来接本机，现在准备开源）**：4 处硬编码本机路径全改成「env 覆盖 + 作者本机兜底」——
`LINK_BRAIN_MEDIA_PY`（llm/vision）、`LINK_BRAIN_AB_PROFILE_PREFS`（attachments 的 agent-browser 小号登录 profile）；
`favorites.py` 的 favdump/profile 本就 env 可覆盖。审计确认 git **没跟踪任何 data.json/key/cookie/vault**。
清单写进 README「本机依赖与环境变量」。没有 media.py 的用户走插件「自定义 HTTP」，浏览器登录/收藏是可选重活。

测试：`tests/test_ask.py`（8 个网络无关：切词/召回/意图/github&links 本地 only/qa 片段限量/模型失败仍列笔记）；
`test_catalog_interactions.cjs` 补 answerArchive 解析 + 设置默认；全套 **121 passed** + node PASS。
main.js 已同步 vault，目录已 `catalog` 重建。**待 Owner 实机**：在插件设置里配好接口（或用默认 media），
开「小红书收藏目录.md」→ 搜索框输 `/问题` 点「提问」验证回答 + 复制。

## 最新交接 2026-09-16

- Owner 追加：AI 回答区支持一键复制完整 Markdown 回答及链接，成功/失败反馈；待随 AI 回答功能实现，详见 TASKBOOK 顶部第7项。

- Owner 提醒额度约剩30%，允许未完工作交其他模型。完整可执行交接放 docs/TASKBOOK.md 顶部。
- 本轮：导入按钮改直调+旧插件恢复+可见错误；目录减密度增加留白；本地数据补原文和真实 GitHub URL（与模型链接线索分开）。源插件已同步 vault，目录已生成。
- 已测：4 个 catalog 测试、node 交互测试（含导入按钮恢复 mock）。未实机验收按钮/视觉。
- 未做：answerArchive 真正接模型；设置页 OCR/识图/TTS/文本接口和两类提示词。当前 / 面板仍未接 AI，不能当作已完成。

## 2026-09-16 目录与导入交互

- 修复 Owner 误清空目录 cssclasses 引起的限宽；重建恢复 lb-catalog，脚本也补 class，目录隐藏属性和文件内联标题。
- 卡片底部显示归档时点赞数；顶部显示目录更新时间；全部/今日新增切换按本地日期过滤。
- 普通搜索支持拼音近似、中文漏字；# 按标签查询（多个标签 OR）；/ 打开 AI 回答面板。
- AI 未接服务：未来插件 `answerArchive({question, items})` 返回文本即可接入，当前页面如实显示未接入。
- 导入插件新增弹窗和批量导入；清洗分享文案、去重、保留 xsec_token，stdout 独立解析；投喂页去掉重复一级标题，导入结果逐条转换，失败保留 URL。
- 正文右栏作者固定，标题/正文/评论独立滚动；单图隐藏原生翻页箭头。已全量生成 156 篇，插件同步至 vault。
- 验证：32 个相关 Python 测试通过；node tests/test_catalog_interactions.cjs 通过。实机截图两次报 SetIsBorderRequired 不支持此接口；已发送重载指令，视觉和真实联网批量导入尚未验收。

## 2026-09-16 收藏墙调整

- 目录隐藏分类条和卡片标签，封面圆角、透明卡片底、标题两行、作者日期弱化，列宽约 210px 随容器调整，解除目录阅读限宽。
- 本地模糊检索覆盖标题、完整概要、正文和当前属性标签；支持分词、非连续字串和英文单字符拼写近似，非 AI 语义检索。
- 右键卡片编辑 tags，直接写回笔记属性；重渲染保留用户标签删除/清空，目录打开时读取 Dataview 当前属性。
- 当前未做其他软件导入；Obsidian 实际窗口铺满效果仍待实机确认。

current_lot: 4
current_main: 5330cbb  # catch + 报警 + 实机反馈那批（docs 提交在它后面）
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
- **字节也拿到了（2026-09-04 当天打通）**：`python -m link_brain attachments <item_id>` 用
  agent-browser 的小号登录态开 headed 浏览器点下载，字节落对象级 `attachments/`，
  写 `attachments.json`（doc_id / sha256 / 大小），`meta.attachments_status=downloaded`，
  可见 md 的 📎 变成指向本地文件。**`raw/vNNNN/` 一个字节不动。**
- 样本 A 实测：`p模式教程-机教版.pdf` 1,436,001 字节，自动下的 sha256 与手工点击下载完全一致。
- 踩到并记进 `docs/POC-xiaohongshu.md` 第 4b 节的坑：headless 下载 POST 会挂死（必须 headed）、
  Chrome“问保存位置”会让自动点击变成取消、`open <url>` 在登录态小红书页面永不返回、
  Windows 上 `subprocess.run(capture_output, timeout)` 杀不掉 `.cmd` 的子孙进程会假超时。

### 给主模型的摘要通路（2026-09-04，STATE 上一版「下一步 1」）
- `catch "<消息全文>" --origin tg|cmx|cc --actor human`：自己从消息里找小红书链接
  （`xhs.URL_RE` + host 白名单 `xiaohongshu.com`/`xhslink.cn`/`xhslink.com`）→ 逐条 `ingest`
  （命中索引就是 HIT，不联网）→ **stdout 只有一行 JSON**，日志全在 stderr。
  没链接就是 `{"found": 0, "items": []}`，零成本。同一篇在一条消息里出现两次只算一条。
- item 字段：`item_id / status(new|hit|error) / title / summary / tags / kind /
  visible_note / agent_md / attachments / url`，路径全是绝对路径。整条消息当 `--note` 传下去。
  `summary` 用 `derived/extracted.json` 的小模型概要，没有退回正文前 120 字（`--extract` 才花钱调模型）。
- 一条链接抓挂了只让那条变成 `status=error`（带 `error` 文本），其余照常，退出码 1、JSON 照样打全。
- 顺手加了 `read --brief --json`（同一份 item 结构，没有 status 键）、`read --full --json`
  （带整篇 agent.md 的 `markdown`）、`search --json`（只查 SQLite，所以 summary 是正文前 120 字）。
- **不做 HTTP / MCP 服务**（硬约束 8）：TG/CMX 就是 Bash 直调 CLI。结构写死在 `docs/FORMAT.md` §10。
- 机器可读输出走 `read.dump_json`，直接写 stdout 的 UTF-8 字节：Windows 控制台是 GBK，
  `print()` 碰到标题里的 emoji（如「无线水吧台‼️」）会 UnicodeEncodeError 让调用方拿到崩溃而不是 JSON。
  人看的那几条 print 也顺手降成 `errors="replace"`（在 `cli.main` 里），不改编码、中文照常。
- `tests/test_catch.py`：链接检测/白名单、无链接零成本、new→hit 不联网、一条消息两个同篇算一条、
  抓失败仍是合法 JSON、`--json` 三条通路。全套 78 个测试绿。

### 附件链接回归修复（2026-09-04，Owner 实机报的）
- 症状：上个版本的 📎 点得开，附件字节下下来之后点不开了。
- 真因：字节下下来后 href 从 `https://www.xiaohongshu.com/file/<docId>` 换成了本地相对路径，
  而**裸 HTML 里的 `<a href="../../_archive/…">` Obsidian 一律当外部 URL**，本地文件打不开。
  `<img src>` 能显示是另一条通路，别拿它当反证。跟 Lot 3b 第 2 条「原图链接要放 HTML 块外面」同一个坑。
- 修法：`render._attachments_md` 取代 `_attachments_html`，附件行改成 content 层里、
  HTML 容器**外面**的一行 Markdown——本地文件 `📎 [[_archive/…/attachments/x.pdf|x.pdf（19 页 · 已存本地）]]`，
  只有元数据的仍是普通 Markdown 链接指原站。5 篇已 `render --all` 重渲染过。
  **等 Owner 在 Obsidian 里点一下确认。**

### 评论区图片（Owner 问的）
- 现在拿不到，**不是解析漏了**：MCP `get_feed_detail` 返回的评论对象只有
  `id/noteId/content/likeCount/createTime/ipLocation/liked/userInfo/subCommentCount/subComments/showTags`，
  64 条评论里 `pictures`/`picture`/`image` 一个键都没有；全库 6 份 manifest 的 `comment_image` 数都是 0。
- 下载通路其实早写好了（`ingest.download_media` 认 `comment_image` role），数据源一给字段就自动下。
- 真要拿到只能照附件那条路：agent-browser 小号登录态开 headed 浏览器抓评论区（硬约束 10 允许）。
  是独立一个 Lot 的量，且会弹窗口打扰 Owner —— **等 Owner 点头再排**。

### Owner 实机反馈这一轮（2026-09-04 夜 → 09-05）
- **附件点不开**（她报的）：真因是裸 HTML 里的 `<a href="../../_archive/…">`——Obsidian 一律当外部
  URL，本地文件打不开；`<img src>` 能显示是另一条通路，别拿它当反证。现在附件/原文/机读版是
  content 层最上面一个 callout（`> [!link-brain-file]`，CSS `data-callout="link-brain-file"`），
  **必须在 HTML 容器外面**，本地文件用 `[[vault 路径]]`。
- 那条灰字长这样：`原文 · 机读版 · 附件`。「机读版」直接进 `derived/agent.md`（她说在 Obsidian 里
  看不到机读视角）。样式按她要求：**没有灰框、字是灰的**，不写 📎 字符，悬停才变强调色。
- **文件名去掉 `__<id8>`**（她原话「__080119fe 就这些别写」）。撞名才退回带后缀：判断读对方
  frontmatter 的 `link_brain.item_id`，Owner 手写的同名老文件绝不覆盖。同一对象有两份 md 时
  `merge_existing` 把 tag / 她手写的 frontmatter 键 / 留言层并起来再删旧的
  （`家克…` 那篇的 `time/finder/from/comment` 就是这么保住的）。
- **收藏链接的形状**：从主页/收藏页复制出来是 `/user/profile/<作者id>/<note_id>`，
  老正则一条都解不出来（前面那截是作者 id）。已加分支 + 回归测试。

### 报警：出事不许不知不觉挂着跑（2026-09-05）
- 三类分开：`AccountBlockedError`（登录态失效/验证码/限流）、`ServiceDownError`（18060 或它的
  浏览器起不来/连不上）、普通 `AdapterError`（这篇没了，批量继续）。前两类 → 退出码 **5** + 报警 + 停车。
- `link_brain/alert.py` 只认环境变量 `LINK_BRAIN_ALERT_CMD`（stdin 收 UTF-8 JSON），
  **公开仓里没有任何推送地址/key**。本机出口是 `cyberlink\Fluffy-SelfHood\tools\scripts\lwa-alert.py`
  = Bark（`bark.mjs`，key 在 `~/.bark/config.json`）+ TG（`tg-mirror.py --send --force`，
  末尾写「Fable 不用处理」）。两条都实测通过。
- anyio 把 `ConnectError` 包进 `ExceptionGroup`，`str()` 只剩「unhandled errors in a TaskGroup」——
  要 `xhs.flatten_exc` 摊开子异常才认得出"连不上 18060"。
- **18060 挂掉的真因是本机内存**，不是掉登录也不是风控：它每次调用都新开一个 Chrome，
  可用物理内存 <1G 时高发 `[launcher] Failed to get the debug url`（2026-09-04 夜实测：
  0.5–0.9G 时连挂 14 条）。所以 ingest 对 ServiceDown **先退避重试 3 次（20s/60s）** 再停车；
  批量脚本另加内存闸（<1.4G 就等）。重启服务只是治标。

### Owner 的 31 条收藏（2026-09-04 夜）
- 源文件 `%USERPROFILE%\Downloads\_.md`，31 条去重后 31 篇。第一轮 17 篇成功落盘，
  14 篇卡在上面那个内存问题；补抓脚本带内存闸在等（会自己跑完再统一 `render --all --extract`）。
- 有附件（`metadata_only`）的 7 篇；只有 P 模式那篇的字节已经在本地。
- `vault/Web/Xiaohongshu/` 里有一个 `20260904-文档体系整理-裁决.md` 不是归档产物，是别的会话丢进来的
  cyberlink 文档，没敢动，等 Owner 处置。

### 2026-09-05 凌晨这一轮做完的
- 31 条收藏全部补抓完（30 篇落盘，`6a74946c…` 那条每次都在 MCP 侧 300s 超时，单独挂着）。
- 附件字节 10 个已下（含 4 个 .docx）；`pdf2md` 把 8 个 PDF 转成 `derived/attachments/<doc_id>.md`，
  坏字形全部 0%——只有子集化字体那份走了逐页 OCR，其余直接抽文字层。
- 原文链接带 `xsec_token`（裸 canonical 会 404，实测验过）；顶部灰字变成
  `原文 · 机读版 · 附件 · 全文`。
- **布局折腾了两轮最后回滚**：想把正文从 HTML 搬出来变 Markdown（为了能划 `==重点==`），
  试过 float、也试过把 grid 建到 sizer 上，Owner 实机两次都说更差，最后 `git checkout 62c9024`
  整体回到她认可的那版（`.lb-cols` 两栏 grid + 图片 sticky + 正文在 `.lb-detail` 里）。
  **教训写在这里，别再重蹈**：正文一旦是 Markdown，它在 DOM 里必然是 sizer 的直接子节点
  （Obsidian 遇空行闭合 HTML 块），两栏只能靠 sizer 级 grid / float 兜，视觉细节对不齐；
  真要划重点得走 `<mark>` 这条不碰布局的路。
  - **2026-09-15 更新（Owner 拍板，别当回归改回去）**：上面这套 float + 正文 Markdown 已被**刻意换掉**。
    需求：图片左栏 sticky 固定；**作者在正文上方**（右栏顶部，随页滚动）；正文+评论右栏可滑。做法：整块
    `.lb-note` 改成一个**连续 HTML 块（内部无空行）**——`.lb-side`(只有图片) + `.lb-main`(作者→正文→评论)，
    CSS 用 grid（48.5% 1fr）+ `.lb-side{position:sticky}`；**正文从 Markdown 改成 HTML `<p>`**
    （`render._body_html`），因为 Markdown 一遇空行就把容器闭合、两栏立不住（这正是当年 float 的根因）。
    手机宽(600px)收单栏。**全文搜索不受影响**（搜的是文件文本）。
  - **高亮已实现（`<mark>`）**：正文转 HTML 后原生 `==` 不生效，改走 `<mark>`。`highlight <item_id> "原文片段"
    [--remove]` 加/去一处高亮（`render.set_highlight`）；marks 存在 md 里，每次 render 由 `collect_highlights`
    /`reapply_highlights` 从上一版收集、原样贴回，自持久（她在源码模式手写的 `<mark>` 也认，兼容旧 `==`）。
  - `tests/test_ui_render.py`/`test_render.py`/`test_cli.py` 已同步断言。已 `render --all` 全量重渲染。
  过程中量到两条硬知识：**元素响应不了自己的容器查询**（sizer 自己当容器时 display 改不动、
  子节点规则却生效）；老 `auto-fit(minmax(390px,1fr))` 在 795px 仍是两栏，断点别定在 700/800。

### Lot 6：收藏同步（2026-09-07，✅ 实机验收通过 —— momo 10 条私密收藏全部归档）
- **实机结果**：`python -m link_brain sync-favorites` → `synced=10`（new 9 + hit 1），`vault/Web/Xiaohongshu/` 落 9 篇新收藏 md（各带图片 + 前10楼评论 + 楼中楼 + OCR）。
- **两个关键修**才跑通：① `fetch_detail` 默认改 `full_comments=False`（只前 10 楼+楼中楼；热门笔记滚全评论区在本机负载下超时，Owner 拍板评论主体够）；② streamablehttp 要同时设 `sse_read_timeout`（原来只设 timeout，SSE 响应仍卡 300s）。
- **僵尸浏览器**：18060 每请求开浏览器，残留 chrome 堆积会 `Failed to get the debug url`——干净 slate 就好；nightly 任务开头结尾各清一次。
- **卡了很久的真卡点已解**：`user_profile(tab="fav")` 对私密收藏只回游客视图（`feeds:null`），
  MCP 无法读私密收藏。解法不是 MCP：外部读取器 `favdump.exe`（在 `%USERPROFILE%\.xiaohongshu-mcp`，
  Codex 的 persistent-profile 方案 + 客户端路由点侧边栏「我」→ 收藏 tab）**已实测读到 momo 10 条
  私密收藏**（`guest:false / privacyWall:false`），并且**扫一次后跨无扫码重启持久**
  （headless 连开两次都读到，exit 0）。**关键：读收藏必须 `XHS_HOST=https://www.xiaohongshu.com`**——
  rednote.com 的 web_session 在登录浏览器关掉后被服务端作废，只有 xiaohongshu.com 的会话持久。
- `link_brain/favorites.py`：`fetch_favorites()` subprocess 调 favdump（可用 `LINK_BRAIN_FAVDUMP` /
  `XHS_FAV_HOST` / `XHS_FAV_PROFILE` 覆盖）→ 逐条走**和 `catch` 一样的** `ingest_url(ingest_kind="favorite")`：
  命中索引就是 HIT（不联网、不下载，硬约束 7 去重只认 `xiaohongshu:<note_id>`），未命中才连 18060。
  ServiceDown / 未登录（favdump 退出码 3）→ 停车 + 报警（复用 `alert.py`，公开仓不含推送地址）。
  stdout 只一个 JSON `{"favorites":N,"synced":M,"items":[...]}`，退出码 0/1/5 同 `catch`。
- `sync-favorites --limit N [--extract] [--actor]` 已接进 CLI；`tests/test_favorites.py` 5 个网络无关
  用例（全量遍历、note_id 去重、ServiceDown 停车+报警、未登录整批 blocked、CLI 派发）全绿；
  `python -m pytest -q` 全套 83 个绿。
- **✅ 整批实机通过（2026-09-07 17:xx）**：`sync-favorites` `synced=10`（new 9 + hit 1），9 篇新收藏 md 落 `vault/Web/Xiaohongshu/`，已归档的报 HIT 不重抓。见上「Lot 6」节的两个关键修。
- **每晚调度已挂**（仓库外）：Windows 计划任务 `XhsFavSync` 每天 04:00 跑 `xhs-fav-sync.ps1`（清 slate → sync-favorites → 掉登录才 Bark/TG 报警），脚本在 `%USERPROFILE%\.xiaohongshu-mcp\xhs-fav-sync.ps1`，日志 `~\.xiaohongshu-mcp\fav-sync.log`。

## 已知缺口

- 图片左右箭头暂不作为稳定功能；当前主要用横向滚动 / 触控滑动切图。
- 复杂评论数据仍受 MCP 返回结构限制；V1 不为了 UI 自建额外小红书抓取器。
- 评论图如 MCP 未返回对应媒体字段则无法补抓。
- 附件下载依赖 agent-browser profile 里的**小号登录态**；那个登录掉了就要重扫
  （主号绝不能扫这个 profile——会顶掉 18060 MCP / TG 端，2026-09-04 实际发生过一次）。
- 附件下载要开 headed 浏览器，会在屏幕上弹窗口，跑批量时会打扰 Owner。
- `inbox / resolve / comment` 尚未完成。
- `catch` 只在**第一次**归档时把消息写成留言 cmt1；已经归档过的（HIT）那条消息只进 relations 表，
  不会追加到可见 md 的留言层——那是 Lot 5 `comment` 的活，等 Lot 5 一起接。
- 评论区图片全库为 0，MCP 不返回该字段（见上）。
- PDF 附件还没转成 md。通路是现成的（`media.py pdf`，本地 pymupdf + 扫描页走 CMX OCR），
  但实测 `p模式教程-机教版.pdf` 的文字层字形映射是坏的（人→⼈、：→9、括号→df，子集化字体），
  这类必须退回「页面渲成图 → OCR」。判据用康熙部首 / CJK 兼容区字符占比。
- 附件字节要 headed 浏览器，批量下会在屏幕上弹窗打扰 Owner；还没接进 ingest 自动跑。
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

按这个顺序做，都不需要再问 Owner 要决定（她 2026-09-05 凌晨已经拍完板）。

1. **Lot 5 留言层**（主线最后一块）：`comment / inbox / resolve` + `scripts/smoke.py`；
   顺带把 `catch` 在 HIT 时把新消息追加成留言接上（现在只进 relations 表）。
2. **Lot 7 评论图补抓**（Owner 已批，规格见 `docs/TASKBOOK.md` Lot 7）：MCP 没有那个字段，
   走 agent-browser 小号登录态读页面 DOM 拿 URL、httpx 下字节，落**对象级** `comment-media/`，
   不碰已封存的 `raw/`。
3. ~~**目录页 / OB 首页瀑布流**~~ **✅ 代码已做（2026-09-15），改法推翻了 09-07 的方案，等 Owner 装 Dataview 实机验**：
   - **09-15 Owner 拍板：组织轴改成 tag，不是 category 文件夹分组**。理由：文件夹一条笔记只能进一个夹子、
     丢多维信息，移文件还是破坏性的（E2N 就得靠「只在子目录移、不删正文」自保）；tag 不动文件、能加减组合、
     贴合她习惯、给以后 AI 模糊搜索留轴。**tag 本来就在每篇 frontmatter 里**（Lot 4），直接拿来当筛选轴，
     不再动 `llm.py` 加 category。**上面那套固定分类清单作废，别再照它做。**
   - `catalog.py` 重写成：Python 出 `_archive/catalog-data.json`（封面取 manifest 第一张成功图、
     tag 读可见笔记 frontmatter、概要读 extracted.json、💬/📎/日期/kind 全带），md 页面 `小红书收藏目录.md`
     是一段 **dataviewjs**（读那个 JSON 渲染封面瀑布流 + 点标签**加/减**筛选 + 搜索框；样式 JS 自注入、
     卡片点击用 `openLinkText` 开笔记——绕开「裸 HTML a href 打不开本地笔记」和「md 不跑 script」两个坑）。
   - 硬约束 #8「不做 Obsidian 插件」不违反：用的是**用户装的** Dataview 社区插件，不是自研插件。
   - 实跑 156 篇：全有封面 + tag（1097 个唯一 tag，chip 条按热度显示 top 28、其余折「更多」）；
     `tests/test_catalog.py` 3 个网络无关用例绿，全套仍全绿。
   - **差 Owner 一步（待她验）**：OB 里装 **Dataview** 插件 + 其设置里打开 **Enable JavaScript Queries**，
     打开 `小红书收藏目录.md` 看封面墙、点标签实时筛。没装/没开 JS 时页面显示的是 dataviewjs 源码。
4. **docx → 文本**：4 个附件是 .docx，`pdf2md` 只吃 PDF。通路加进
   `Fluffy-SelfHood/tools/scripts/media.py`（硬约束 3：不自研，和 pdf 一条路），再让 `pdf2md` 认 .docx。
5. ~~**Lot 6 收藏同步**~~ **代码+读取已通，只差整批实机验收**（见上「Lot 6」节）：
   `get_my_profile(tab="fav")` 走不通（私密收藏回游客视图），已改用外部 `favdump.exe`
   （persistent profile + 客户端路由）。差的一步：机器有 RAM 余量时跑一次
   `python -m link_brain sync-favorites` 落至少 1 篇 md，然后把它挂进每晚调度（仓库外）。
6. **附件自动接线**：ingest 发现 `metadata_only` 就自动下一次字节；批量用 `--no-browser` 跳过 +
   结尾汇总缺哪几篇。
7. **高亮**（等 Owner 说做才做）：唯一可行的是 `<mark>` 这条**不碰布局**的路——给一条命令把她选中的
   句子写进 content 层，rerender 时按原文匹配贴回去。**不要**再为了高亮去动两栏布局（今晚栽了两次）。
8. **作者头像本地化**（Owner 2026-09-05 看着那个圆点"有点怪"）：`source.json` 的
   `note.author.avatar_url` 一直有（`sns-avatar-qc.rednotecdn.com/avatar/…`），只是没用。
   按附件那套下到**对象级** `author-avatar.<ext>`（不碰已封存的 `raw/`），渲染时优先用它、
   拿不到再退回现在的占位圆点。**别直接在 md 里写远程 URL**——那样每次打开笔记都会去小红书
   CDN 取图，离线看不到、也等于每次阅读都上报一次。
9. Issue #2 的 UI 实机验收：回滚之后再确认一次。
10. `docs/BENCH.md` 最后三列 Owner 说不做 20 条了，以后手工填，不再挡路。

### 明确不做 / 不用管（Owner 2026-09-05 拍板）
- `6a74946c…` 那条笔记每次抓都 300s 超时——**不用管**，别再花时间查。
- `vault/Web/Xiaohongshu/20260904-文档体系整理-裁决.md`（别的会话丢进来的 cyberlink 文档）
  ——**不用管**，别动它。
