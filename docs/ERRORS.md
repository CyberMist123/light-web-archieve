# 报错台账（ERRORS）

开源前的经验库：每条 = **用户看到什么 → 根因 → 修法 / 自愈动作 → 回归用例**。
目标（作者 10-04 定）：风控以外的报错期待是 0；凌晨跑完出 bug **当场修**，不留到第二天；实际报错都要显示出来；
识图 / 概要 / 附件 / 转写任一步失败都**不阻断入档**（先入档，后补）。

- 故障码规则见 `docs/CONVENTIONS.md` §2；显示文案只在 `link_brain/problems.py` 的 `STATE_REGISTRY`。
- 每个码的修复动作在 `link_brain/repair.py`（`plan()` 归类：`run` 有动作 / `wait` 必须等且写清等到几点 / `human` 风控·登录·key / `manual` 写下一步）。
- 自愈分三层：①**同一次运行里换策略重试**（各模块自己做）；②**夜跑收尾的自愈轮**（`repair.run(since=…, auto=True)`，本次新登记、还没解决的各修一遍，不过 06:50、最多 30 分钟）；③**问题面板「现在修」/「全部修一遍」**。修不好的写清「试过什么、为什么没好、下一步」。
- 新增故障码时：同一个提交里在本文件加一行、在 `repair.plan()` 给它归类（CONVENTIONS §2.7）。`tests/test_self_heal_1004.py::test_errors_md_cites_real_tests` 会核对这里写的回归用例真的存在。

---

## 一、真实出过的事（按时间）

### 1. 收藏只读回一截（F1，10-03 / 10-04）
- **用户看到**：夜跑后「收藏数异常」——收藏一千多条，只读回 50 / 540 / 1120 条；以前还会在连着 3 晚读到同一个截断数后把它认成新基准，之后再截断也不报了。
- **根因**：读取组件判「滚到底」靠「条数稳住一会儿」：页面加载慢、滚动没触发加载时，条数停住就当读完了；Python 侧拿不到「到底有没有读完」的信号，只能按「比上次少一半」猜。
- **修法 / 自愈**：
  - 读取组件（Go）：`GET /api/v1/favorites?expect=N` 接受上次基准；判停看页面状态里的 `hasMore`，换四级滚法、节奏带抖动；读不全如实报 `partial` + `stop_reason`（has_more_false / stable / below_expect / stuck_has_more / budget / cancelled / tab_lost / risk）。滚动预算 420 秒、单次请求上限 10 分钟。
  - Python：有基准才带 `?expect=N`（旧读取服务行为不变）；客户端超时 780 秒（≥ 660）；`partial` = 只读到一截：这一截里的新收藏照抓，同步结果如实标「只读到一截（原因）」；基准只认靠得住的全量（`partial` / 可疑 / 明显低于基准且没读到底的都不认，读取服务明说 `has_more_false` 才认——她真删了收藏）。
- **回归用例**：`tests/test_self_heal_1004.py::test_route_passes_baseline_only_when_known`、`tests/test_self_heal_1004.py::test_partial_read_ingests_new_ones_flags_once_and_keeps_baseline`、`tests/test_self_heal_1004.py::test_baseline_only_from_trustworthy_reads`、`tests/test_review_fixes_1001.py::test_two_truncated_nights_in_a_row_both_flagged_but_pushed_once`；Go 侧 `reader/link-brain-reader.patch` 里的 `TestScrollFavoritesBudgetIsPartial` / `TestScrollFavoritesEndsOnHasMoreFalse` / `TestFavReadSummary`。

### 2. 一晚重读三次收藏列表，撞上滑块验证（10-04）
- **用户看到**：读收藏页弹出拼图滑块，号进入风控暂停。
- **根因**：读到一截被当成「出错」（退出 1），夜跑「exit 1 等 25 分钟再读一次」又读一遍列表；再加手动补跑，同一晚读了三次。读收藏是最容易触发风控的动作。
- **修法 / 自愈**：只读到一截 / 条数可疑 → `sync-favorites` **退出 3**（不是 1）：夜跑不重试、今晚绝不再读列表；问题面板对这一条显示「等到 明早 04:00：今晚已经读到一截…」，不给「现在修」；自愈轮任何情况下都不重读收藏列表；单条「现在修」重读收藏前要求距上次读 ≥ 30 分钟。
- **回归用例**：`tests/test_self_heal_1004.py::test_nightly_partial_sync_no_reread_and_single_problem`、`tests/test_self_heal_1004.py::test_partial_with_failed_notes_still_one_row_and_no_retry_code`、`tests/test_self_heal_1004.py::test_partial_favorites_waits_until_next_nightly_with_reason`、`tests/test_self_heal_1004.py::test_sync_reread_guard_30_minutes`、`tests/test_self_heal_1004.py::test_nightly_exit1_still_retries`。

### 3. 设置存成新格式后向量索引丢 key，语义检索静默停了（10-04）
- **用户看到**：什么都没看到——问收藏的语义召回悄悄退回纯关键词；夜跑日志里 `embed` 报 `no-api-key`。
- **根因**：向量索引（embedAI）没有设置页入口，以前靠旧设置换算顺带生成；设置页一存成新格式就不再补，key 来源断了。失败只写了一句日志，没进问题列表。
- **修法 / 自愈**：data.json 没写 embedAI 时借用已配好的千问兼容接口（同一 key 来源，`/embeddings`）；取向量当场退避重试（网络 / 5xx / 429 最多 3 次）；失败按码登记：以前能用、现在拿不到 key → `NEEDS_HUMAN.AUTH_FAILED`（不再静默），从没配过 → `SKIPPED.NOT_CONFIGURED`，其余按 HTTP 码；`embed` 失败退出 3（原因已登记在 `embed`，夜跑不另报）。
- **回归用例**：`tests/test_providers.py::test_embed_follows_configured_dashscope_endpoint`、`tests/test_self_heal_1004.py::test_embed_retries_transient_then_succeeds`、`tests/test_self_heal_1004.py::test_embed_failure_is_registered_once`。

### 4. 没有人声的视频只报错、不读画面字幕（10-04）
- **用户看到**：卡片 / 问题列表「视频里没人说话」，但视频画面上其实有烧录字幕。
- **根因**：「视频画面文字」开关关着时，没人声 / 没音轨的视频不抽画面字幕；结论（没人声）被当成问题登记。
- **修法 / 自愈**：没人声 / 没音轨的视频即使开关关着也抽画面字幕；**读出字幕就不登记**，旧的「没人声」记录下次补抽并标已解决。仍登记的 `PERMANENT.NO_SPEECH / NO_AUDIO` 文案写明「画面上也没认出字幕」，面板说明「正文和视频都已存好，不用处理」，「现在修」= 重读一次画面字幕（`videos <id> --transcribe --rescreen`），自愈轮不自动跑。
- **回归用例**：`tests/test_videos_transcribe_1001.py::test_no_speech_reads_screen_text_even_when_toggle_is_off`、`tests/test_videos_transcribe_1001.py::test_old_no_speech_record_gets_screen_text_backfilled`、`tests/test_videos_transcribe_1001.py::test_no_speech_and_no_screen_text_is_still_listed`。

### 5. 「旧设置已停用 / 已换算」提示不撤（10-04）
- **用户看到**：设置已经存成新格式了，问题列表「未开启」组里还一直挂着「旧设置已自动换算」。
- **根因**：说明只在换算时登记，换成新格式后没人撤。
- **修法**：读设置时发现已是新格式，就把那条 `SKIPPED.LEGACY_CONFIG` 标已解决。
- **回归用例**：`tests/test_providers.py::test_legacy_note_is_withdrawn_once_settings_are_new_style`。

### 6. 精细识图输出复读，试一次就放弃（10-04）
- **用户看到**：架构图 / 表格的精细识别「AI 结果不可用」，笔记里只有第一层的粗结果；要等后面几晚才再试。
- **根因**：模型偶尔复读（同一段输出几十遍）或截断，结果过不了格式检查；以前同一张图每晚只试一次、跨 3 晚才放弃，当晚不换参数也不换模型。
- **修法 / 自愈**（同一次运行里）：原样 → **换参数**（温度调到 0.6，跳出复读循环）→ **换另一个已配置的模型**（设置里的精细识别模型 / 第一层识图模型，去重）→ 都不合格才当场放弃这张，笔记继续用第一层结果，并在问题里写明「试过 … 都不合格，已退回第一层识图结果」。接口故障（限流 / 断网）不算次数，留待补。「现在修」只重标放弃了的那几张（`vision --refine-mark <id> --retry-failed --now`）。
- **回归用例**：`tests/test_self_heal_1004.py::test_refine_ladder_heals_with_new_params`、`tests/test_self_heal_1004.py::test_refine_ladder_switches_model_then_falls_back_to_layer1`、`tests/test_self_heal_1004.py::test_refine_retry_failed_only_remarks_failed_images`、`tests/test_vision_refine.py::test_refine_object_gives_up_after_three_tries`。

### 7. 同一件事报两条，原因还重复一遍（10-04）
- **用户看到**：问题列表里「夜跑：sync-favorites 步骤出错」和「收藏同步：收藏数异常」两条；原因那句是「收藏只读回 540 条…；收藏只读回 540 条…」。
- **根因**：`sync-favorites` 可疑时退出 1，夜跑按「步骤出错」又登记一条；同步状态的 message 和 detail 写的是同一句，拼原因时没去重。
- **修法**：可疑 / 只读到一截退出 3 = 「原因已登记在 sync.favorites」，夜跑不另登记、只在汇总里留一行指过去（CONVENTIONS §2.8）；拼原因去重；有篇没抓到的附在同一条后面（「另有 N 篇没抓到：…」），不另起一条。
- **回归用例**：`tests/test_self_heal_1004.py::test_nightly_partial_sync_no_reread_and_single_problem`、`tests/test_self_heal_1004.py::test_reason_dedup_message_and_detail`、`tests/test_self_heal_1004.py::test_partial_with_failed_notes_still_one_row_and_no_retry_code`。

---

## 二、故障码对照（用户看到 → 常见根因 → 自愈动作）

「同次」= 那一步自己那次运行里的换策略重试；「自愈轮」= 夜跑收尾自动再修（✔ 自动 / — 不自动）；「现在修」= 面板按钮跑的动作。
风控 / 登录类（`NEEDS_HUMAN` 账号码）一律人工入口：不自动处理验证码、不自动清熔断。

| 码 | 用户看到 | 常见根因 | 同次 | 自愈轮 | 现在修 / 下一步 |
|---|---|---|---|---|---|
| `NEEDS_HUMAN.NOT_LOGGED_IN` / `CAPTCHA_REQUIRED` / `ACCOUNT_RISK` / `RISK_HOLD` / `ACCOUNT_BLOCKED` / `WRONG_ACCOUNT` / `NOT_INSTALLED` | 需要登录 / 需要验证 / 账号风控 / 风控暂停中 / 账号要处理 / 登错号 / 未安装读取组件 | 号掉登录、撞安全验证、被跳到风控页、熔断中、登的不是同步号、组件没装 | 立即停车，不重试 | — | 人工：扫码登录 / 打开验证 / 账号与同步 |
| `NEEDS_HUMAN.AUTH_FAILED` / `QUOTA_EXCEEDED` | AI key 失效 / AI 余额不足 | 401/403、欠费；向量索引拿不到 key | 不重试（重试没用） | — | 人工：打开设置换 key / 充值 |
| `NEEDS_HUMAN.STUCK` | 连续几天没修好 | 同一步的临时故障连着 3 个日历日都在 | — | — | 「现在修」= 那一步各篇一起修 |
| `NEEDS_HUMAN.SYNC_STUCK` | 同步卡住了 | 一次同步占着号几小时没进展 | — | — | 人工：重启 Obsidian / 结束那个进程；下一晚夜跑开头自动消 |
| `NEEDS_HUMAN.BACKUP_DISK_MISSING` / `PORT_IN_USE` | 备份盘没挂 / 远程阅读端口被占用 | 外接盘没插 / 端口被别的程序占 | — | — | 人工 |
| `TRANSIENT.FAVORITES_SUSPICIOUS` | 收藏只读到一截 | 读取组件 `partial`、读回 0 条、比上次少一半以上 | 这一截的新收藏照抓；退出 3 | — 今晚绝不重读 | 等到下次夜跑（写明几点）；之后才给「现在修」= 重新同步（距上次读 ≥ 30 分钟） |
| `TRANSIENT.FAVORITES_FAILED` / `TIMEOUT` / `DISCONNECTED` / `BUSY` / `SYNC_FAILED` / `TOO_MANY_FAILURES` / `ACCOUNT_BUSY` / `INTERRUPTED`（sync.favorites） | 读收藏没成功 / 读取服务超时 / 没在运行 / 正忙 / 同步没做完 / 连续失败 / 号被占 / 被打断 | 机器卡、读取服务没起、号被别的任务占 | 夜跑 exit 1 等 25 分钟重试一次 | — 不重读列表 | 「现在修」= 重新同步（距上次读 ≥ 30 分钟，否则写明等到几点） |
| `TRANSIENT.RATE_LIMITED` | 刚刚同步过 | 读取服务 10 分钟限频 | — | — | 等 10 分钟（写明几点） |
| `TRANSIENT.DISCONNECTED` / `TIMEOUT` / `BUSY`（ingest 步骤级） | 读取服务没在运行 / 超时 / 正忙 | 读取服务没起来 | — | ✔ 检查读取服务、没在跑就拉起 | 同左 |
| `TRANSIENT.WEB_PROBE_BLOCKED`（ingest）/ `PROBE_FAILED`（attachments.recheck） | 网页那侧被拦 / 附件没查清 | 游客网页被登录墙 / 验证挡住 | 当场用登录号再看一次 | — | 等到下次夜跑的附件补查（写明几点；同一晚再开容易被限流） |
| `TRANSIENT.DOWNLOAD_FAILED` | 附件没下好 | 504 / 超时 / 网页占位页 / 文件头不对 | 带退避重下，最多 3 次 | ✔（号没出事、离上次开这一篇 ≥ 20 分钟） | 「现在修」= 重下这篇附件；不行就手动下载后「挂附件」 |
| `TRANSIENT.SERVICE_BUSY` / `STEP_TIMEOUT`（attachments.convert） | 服务正忙 / 步骤超时 | 本地 OCR 没起来、超时 | 歇几秒当场再转一次 | ✔ 强制重转 | 同左 |
| `PERMANENT.PDF_ENCRYPTED` / `PDF_DAMAGED` / `DOC_UNSUPPORTED` / `CONVERSION_FAILED` | 全文没转出来 | 有密码、文件坏、格式不支持 | 字节照存，不删不重下 | — | 「现在修」= 再强制转一次；原件已保存 |
| `TRANSIENT.HTTP_5XX` / `HTTP_429` / `NETWORK` / `SERVICE_BUSY`（vision.layer1 / enrich.summary） | 接口暂时出错 / 限流 / 网络不通 / 服务正忙 | 模型接口抖动、限额 | 识图请求网络抖动重试 1 次；概要：重试 1 次 → 换文本 AI 模型 | ✔ 重跑这篇识图和概要 | 同左；不行到设置里点「测试」 |
| `TRANSIENT.RETRY_EXHAUSTED` | 连着几次没补成 | 识图 / 概要连着 3 次没补成 | — | ✔ 重跑这篇（不等退避） | 同左 |
| `TRANSIENT.STEP_CRASHED`（vision.layer1 / enrich.summary） | 步骤中途出错退出 | 识图 / 概要代码意外异常（正文已入档） | 不阻断入档，照样渲染笔记 | ✔ 重跑这篇 | 同左 |
| `PERMANENT.MODEL_OUTPUT_INVALID`（enrich.summary） | AI 结果不可用 | 概要两次都不是合法 JSON | 第二次把「只回 JSON」说死 → 换文本 AI 模型 | — | 「现在修」= 重跑这篇 |
| `PERMANENT.MODEL_OUTPUT_INVALID`（vision.refine） | AI 结果不可用 | 精细识别复读 / 截断 / 流程图格式坏 | 原样 → 换参数 → 换模型 → 退回第一层结果 | — | 「现在修」= 放弃了的图重新精细识别 |
| `TRANSIENT.SERVICE_BUSY` / `HTTP_*` / `NETWORK`（vision.refine 步骤级） | 接口连着不通 | 免费 key 限额、兜底模型也不通 | 429 换 key、503 歇一会儿同 key 再试、全不行退回设置里的模型 | ✔ 补跑 10 张 | 同左 |
| `TRANSIENT.*`（videos.transcribe） | 服务正忙 / 步骤超时 | 转写服务没起、抽音轨超时 | 转写服务没起：当场拉起（CapsWriter）再转 | ✔ 拉起后重转这条 | 同左；不行到设置里测试语音识别 |
| `PERMANENT.NO_SPEECH` / `NO_AUDIO` | 视频里没人说话 / 没有音轨（画面上也没认出字幕） | 纯音乐 / 没音轨，且没有画面字幕 | 没人声也抽画面字幕；读出字幕就不登记 | — | 不用处理；「现在修」= 重读一次画面字幕 |
| `TRANSIENT.*`（embed） | 网络不通 / 接口暂时出错 / 限流 | 向量接口抖动 | 每批退避重试最多 3 次 | ✔ 重建语义索引 | 同左；不行确认千问兼容接口的 key |
| `TRANSIENT.STEP_TIMEOUT` / `STEP_CRASHED`（nightly.<步骤>） | 步骤超时 / 中途出错退出 | 那一步超时被停、崩溃 | — | ✔ 补跑那一步的一小段（目录 / 识图 / 概要 / 转写 / 索引 / 补附件） | 同左；碰号的那几步号出事时不跑 |
| `TRANSIENT.INTERRUPTED`（nightly.run） | 被打断 | 上一晚夜跑被系统强停 / 断电 | — | — | 等下一晚夜跑走完自动消（写明几点） |
| `TRANSIENT.SECRET_TIMEOUT` | 取 AI key 超时 | 密码库卡住 | 没 key 照跑，退回设置里的模型 | — | 人看一眼密码库 |
| `PERMANENT.STEP_ARGS` | 程序和夜跑脚本版本对不上 | 夜跑脚本给的参数程序不认 | — | — | 更新程序或夜跑脚本 |
| `PERMANENT.NOTE_GONE` | 原帖已删除 | 原帖删了 / 不可见 | — | — | 不用处理，本地存档还在 |
| `PERMANENT.REMOTE_TASK_FAILED` | 远程阅读的计划任务没弄好 | 计划任务注册失败 | — | — | 设置 → 远程阅读 关掉再打开 |
| `PERMANENT.CHECKSUM_MISMATCH` / `BAD_PACKAGE` / `DISK_FULL` | 组件校验不过 / 包不对 / 磁盘不够 | 只在安装命令结果里出现 | — | — | 设置 →「开始」重装；先腾空间 |
| `SKIPPED.*` | 未配置 / 已关闭 / 额度到了 / 已退回普通方式 / 旧设置已换算 | 没开、没配 | — | — | 不是问题，不计数 |

入档不被阻断（B2.4）：同步 / 导入时识图、概要、附件、转写都在入档之后单独做；渲染时识图或概要出意外只登记一条（`TRANSIENT.STEP_CRASHED`，正文已入档），笔记照写——`tests/test_self_heal_1004.py::test_render_survives_vision_crash`。
