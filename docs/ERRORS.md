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
  - 读取组件（Go）：`GET /api/v1/favorites?expect=N` 接受上次基准；判停看页面状态里的 `hasMore`，换四级滚法、节奏带抖动；读不全如实报 `partial` + `stop_reason`（has_more_false / stable / below_expect / stalled / hidden_widget / api_refused / budget / cancelled / tab_lost / risk；1008 读取组件 d7：`stalled` 取代 stuck_has_more——卡住只换第 1 级滚法，还不动就停）。滚动预算 420 秒、单次请求上限 10 分钟。
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
  **1008 补一种根因：我们自己的判据误判**——「有一行超过 600 字就截掉、看到截断标记就报复读」，论文页的长段落、聊天截图里的长气泡没有一个字重复，也被判「出现复读」→ PERMANENT，换模型重跑多少次都一样、每次都花钱（见第 11 条）。
- **修法 / 自愈**（同一次运行里）：原样 → **换参数**（温度调到 0.6，跳出复读循环）→ **换另一个已配置的模型**（设置里的精细识别模型 / 第一层识图模型，去重）→ 都不合格才当场放弃这张，笔记继续用第一层结果，并在问题里写明「试过 … 都不合格，已退回第一层识图结果」。接口故障（限流 / 断网）不算次数，留待补。「现在修」只重标放弃了的那几张（`vision --refine-mark <id> --retry-failed --now`）。
- **回归用例**：`tests/test_self_heal_1004.py::test_refine_ladder_heals_with_new_params`、`tests/test_self_heal_1004.py::test_refine_ladder_switches_model_then_falls_back_to_layer1`、`tests/test_self_heal_1004.py::test_refine_retry_failed_only_remarks_failed_images`、`tests/test_vision_refine.py::test_refine_object_gives_up_after_three_tries`。

### 7. 同一件事报两条，原因还重复一遍（10-04）
- **用户看到**：问题列表里「夜跑：sync-favorites 步骤出错」和「收藏同步：收藏数异常」两条；原因那句是「收藏只读回 540 条…；收藏只读回 540 条…」。
- **根因**：`sync-favorites` 可疑时退出 1，夜跑按「步骤出错」又登记一条；同步状态的 message 和 detail 写的是同一句，拼原因时没去重。
- **修法**：可疑 / 只读到一截退出 3 = 「原因已登记在 sync.favorites」，夜跑不另登记、只在汇总里留一行指过去（CONVENTIONS §2.8）；拼原因去重；有篇没抓到的附在同一条后面（「另有 N 篇没抓到：…」），不另起一条。
- **回归用例**：`tests/test_self_heal_1004.py::test_nightly_partial_sync_no_reread_and_single_problem`、`tests/test_self_heal_1004.py::test_reason_dedup_message_and_detail`、`tests/test_self_heal_1004.py::test_partial_with_failed_notes_still_one_row_and_no_retry_code`。

### 8. 一把 key 坏了，问题面板刷出 300 条「AI key 失效」（10-06 / 10-08）
- **用户看到**：手动同步一次，问题列表「等你处理」里 254 条识图 + 42 条概要，每条都是「接口拒绝了 key（HTTP 403）」；看不出是哪把 key、为什么、要花多少补回来。
- **根因**：概要 / 识图按篇登记问题（`enrich.summary|<篇>`、`vision.layer1|<篇>`），接口那一侧出事（key 无效 / 欠费 / 断网 / 限流）时每篇一条；而且这类失败还给这篇记失败次数，3 次就「连着没补成」退避几天——明明不是这篇的错。
- **修法 / 自愈**（1008 Owner：一个原因一条）：接口那一侧的码（`AUTH_FAILED / QUOTA_EXCEEDED / NETWORK / HTTP_429 / HTTP_5XX / SERVICE_BUSY`）不再按篇记，归并到 `ai.summary / ai.vision / ai.refine / ai.embed` 一条（`link_brain/ai_health.py`）：原因写清**哪个接口、哪个模型、key 从哪来（尾号）、HTTP 多少、是 key 无效还是欠费还是断网、怎么办、影响了几篇、补齐这些篇约多少 token / 多少钱**（按库里实际平均量 × 官方单价，和「开始」页的估价同一套）。受影响的篇只记在 `_archive/ai-health.json`，本身留在待补、不记失败次数；同一批里连着 2 篇撞接口就收手（别逐篇白试）；接口再成功一次这条就消。换好 key 后点这条的「现在修」= 补跑。老记录里按篇登的那几百条在下次打开面板时自动折成一条。
- **回归用例**：`tests/test_ai_health_1008.py::test_record_folds_many_items_into_one_row_with_cause_key_and_estimate`、`tests/test_ai_health_1008.py::test_enrich_api_failure_is_one_row_no_fails_and_batch_stops`、`tests/test_ai_health_1008.py::test_legacy_per_item_rows_fold_into_one`、`tests/test_ai_health_1008.py::test_item_own_failure_still_counts`。

### 9. 选了轻量版还在报「AI 概要失败」（10-08）
- **用户看到**：「开始」页选的是「轻量版（不要任何 key）」，问题面板却有概要 / 识图失败。
- **根因**：功能选择只影响「开始」页的勾选，后端照旧按设置里有没有配接口来决定跑不跑 AI。轻量版本来就是另一种模式，不该跑、更不该报失败。
- **修法**：`providers.resolve` 按 `setup.selected` 门禁——没勾「AI 问答 · 概要 · 打标」就不跑概要 / 问答 / 向量索引，没勾「识图」就不跑识图，`extracted.json` 记 `skipped`（灰色「未开启」，不是失败），原因写明去「开始」页勾上。门禁只在插件把「已配好 key 的 AI 组件」对齐回 `selected` 之后生效（`setup.aiSynced`），升级当晚不会把人家在用的 AI 关掉。
- **回归用例**：`tests/test_ai_health_1008.py::test_light_preset_turns_ai_off_with_reason`、`tests/test_ai_health_1008.py::test_light_preset_enrich_marks_skipped_not_failed`、`tests/test_ai_health_1008.py::test_recommended_or_no_selection_keeps_ai`。

### 10. 超长评论区的楼中楼拿不全，页面还写着「展开 N 条回复」（10-07 / 10-08）
- **用户看到**：一楼有上千条回复的笔记，归档里只有几百条；可见页每楼下面一句「展开 1153 条回复」像个能点的按钮，其实什么都没有；同步记录里也看不出评论少了。
- **根因**：①读取组件一次请求的评论预算 480 秒用完就 `cancelled`，Python 没把 `comment_load.replies_partial` 存下来，下次同步又从头读、读到同样的地方停；②读取组件把「已展开完但页面状态里 `subCommentHasMore` 陈旧为 true」的楼也算缺口，`floors_expanded` 一直是 0 / 1，真缺口被淹没；③渲染层拿 `sub_comment_count` 和已有回复数一比就写「展开 N 条回复」。
- **修法 / 自愈**：读取组件（r03）：没按钮且已加载 ≥ 显示数的楼算展开到底；新参数 `expand_floors`（只展开指定楼）+ `floors_not_found`。Python：`capture.comment_load` 存判停原因、读到几楼、每楼缺多少（只留 `missing>0`）；可见页顶上一行「评论读到 N 楼，楼中楼还缺 M 条（原因，下次同步接着读）」、每楼如实写「还有 N 条回复没拿到（原因）」；机读版同样标；同步记录多一项「评论 ❌ 楼中楼还缺 M 条」带续读命令。续读 `comments <id> --fill` 只展开缺口楼（预算 540 秒），合并进新 RAW 版本（其它楼沿用上一版）；夜跑新步骤 `comments --fill-pending` 每晚最多 2 篇、同一篇间隔 ≥ 20 小时、最多 3 次，之后页面写「已续读 3 次，剩下的太长不再读」。不进问题记录（不是故障，是如实标缺）。
- **回归用例**：`tests/test_comments_fill_1008.py::test_compact_drops_zero_missing_and_sums`、`tests/test_comments_fill_1008.py::test_ingest_records_gap_everywhere`、`tests/test_comments_fill_1008.py::test_fill_expands_only_gap_floors_and_merges`、`tests/test_comments_fill_1008.py::test_pending_fills_respects_attempts_and_gap_hours`、`tests/test_comments_fill_1008.py::test_fill_pending_cli_and_nightly_step`。

### 11. 「AI 结果不可用」其实是我们自己的复读判据误判长段落（10-02 / 10-08）
- **用户看到**：两篇的精细识图一直「AI 结果不可用」，点「现在修」、换模型都一样；另一张卡片上有灰标，问题面板里却没有这一条。
- **根因**：①`visual.tidy_output` 把超过 600 字的行一律截断、`shaky_reason` 看到截断标记就报「出现复读」（第一层识图同样误判，误判后自动排进精细识图）；②`vision.refine_object` 一张图成功就把整篇的问题消掉，同一篇别的图还 failed 时出孤儿灰标、下一张失败计数从头算；③当时问题面板还没接上这类报错。
- **修法**：只收真复读（同一段 ≥12 字连着 ≥4 次，或一行里不重复的 20 字片段不到一半；分隔线 / 省略号不算），单行超过 4000 字才硬截断并另报「输出过长」；「出现复读」只在真收掉复读时报；整篇跑完、没有任何一张还 failed 才解决这篇的问题。卡片有标、面板没有的精细识图失败做成一次性迁移（问题面板打开时补登记一次，ts 用 vision.json 的 refine.at）。**不 bump VISUAL_VERSION**（会让全库第一层重跑）。
- **回归用例**：`tests/test_vision_refine.py::test_long_paragraph_is_not_repetition`、`tests/test_vision_refine.py::test_true_repetition_still_flagged`、`tests/test_vision_refine.py::test_separator_line_is_not_repetition`、`tests/test_vision_refine.py::test_refine_ladder_passes_long_paragraph`、`tests/test_vision_refine.py::test_one_image_ok_does_not_resolve_item_while_another_failed`、`tests/test_card_problems_1008.py::test_orphan_refine_backfilled_once_with_refine_time`。

### 12. 已放弃的问题删不掉，顶部灰色数字一直挂着；「全部修一遍」拿它们反复花钱（10-08）
- **用户看到**：问题面板「已放弃」两条永远在，顶部灰色数字不归零；卡片上 5 个橙色「AI key 失效」其实 key 早好了；10-08 04:38 又有一轮「全部修一遍」付费重跑了那两张图。
- **根因**：①问题记录没有隐藏态，一条只有被修好才消失，而已放弃的靠程序永远修不好；②`repair._select` 在「全部修一遍」里对当场修过没好的 PERMANENT 照样再跑（会花钱的精细识图）；③卡片角标只看每篇自己的对象文件，接口那一侧的码在 1008 改成以 ai-health 为准后卡片没跟上。
- **修法**：加「隐藏」——只收没解决的 PERMANENT，她手动、可恢复、照样导出（「复制报错」里状态写「已隐藏」）；隐藏到这个 key 解决为止（同一件事复发照样藏着、记「隐藏后又出现 N 次」，解决后再坏才重新出现；压实不丢）；NEEDS_HUMAN / TRANSIENT 一律不能隐藏。这不违反 1004「实际报错照实显示」：藏的是她看过、决定不管的那条，诊断记录一行不丢。面板：已放弃的行「再试一次」+「隐藏」、组标题旁「全部隐藏（N）」、底部默认收起的「已隐藏 · N」可恢复；状态句说实话（「同样原因已失败 N 次，再点多半一样，不想看就隐藏」）。「全部修一遍」跳过当场修过没好的已放弃条目和隐藏的（第一次照样试，点名单条照样跑）。删笔记时撤掉这篇名下的问题（`problems.resolve_item`，唯一的「真删除」）。卡片角标减去隐藏集合；接口那一侧的码只在 ai-health 里这个能力还开着时照原码出，否则降成灰色「待补识图 / 概要」。
- **回归用例**：`tests/test_problems_dismiss_1008.py::test_dismiss_only_gave_up_rows`、`tests/test_problems_dismiss_1008.py::test_dismiss_survives_same_cause_recurrence`、`tests/test_problems_dismiss_1008.py::test_dismiss_reappears_after_resolve_then_recur`、`tests/test_problems_dismiss_1008.py::test_dismiss_survives_compaction`、`tests/test_problems_dismiss_1008.py::test_export_marks_hidden_rows`、`tests/test_problems_dismiss_1008.py::test_repair_all_skips_failed_permanent_but_single_still_runs`、`tests/test_problems_dismiss_1008.py::test_delete_note_resolves_its_problems_via_remove`、`tests/test_card_problems_1008.py::test_item_problems_skips_dismissed_pairs`、`tests/test_card_problems_1008.py::test_item_problems_drops_stale_api_codes_when_ai_health_clear`、`tests/test_problems_dismiss_ui.cjs`。

### 13. 「附件没查清」挂好几天不动，面板天天写「等到明早」；附件检查谎报「全部已保存」（09-27 起 / 10-08）
- **用户看到**：「正在自动处理」里两条「附件没查清 · 稍后再查」挂了 3 天，什么都没发生；附件检查说「已知附件全部已保存」，其实有一份 PDF 从 09-29 起就没下到。
- **根因**：①补查九成只走游客，却整步算碰号，号一要验证整晚跳过；②每篇按最坏 370 秒预留、只给 20 分钟，「每晚补查 20 篇」做不到；③没有「原帖打不开」这个终态，查过的永远排队尾；④一直用入库时的旧口令；⑤面板状态句按当前时间现编，跳过只写日志不写记录；⑥补查探到但没下好的附件没记进声明，附件检查数不到它。
- **修法**：拆两段——游客段（不碰号、熔断夜照跑但守 ≤10 篇和离验证 ≥60 分钟、号被占就让路、无条件保险丝）和收尾段（碰号、每晚 ≤5 篇、服务失败第一次就收工）；每篇按 220 秒预留，积压期上限 40；查过的按上次查的时间轮流；登录号落 /explore 或 /404 两晚各一次（或新口令一次）才判「原帖打不开」，落 /login 一律停车；本地对账（每晚游客段开头）把探到的附件记进声明、旧的双路证据转终态；下载跨夜退避；状态文件每次运行都写、跳过也写；面板状态句按真实队列位置写。
- **「附件下不了 / 没查清」的每种原因**（上线前清零的清单）：

| 原因 | 码 / 状态 | 修法 | 回归用例 |
|---|---|---|---|
| 游客读不到（登录墙） | `web_recheck.stage=guest_unseen` → 收尾段 | 号正常的晚上登录号看一眼（≤5 篇） | `tests/test_attachments_recheck_1008.py::test_tail_only_looks_at_guest_unseen_and_gone_needs_two_nights` |
| 登录号落 /explore、/404（删了 / 仅作者可见 / 审核中 / 口令过期） | `gone_suspected` → `gone`（卡片「原帖打不开」） | 两晚各一次或新口令一次才定；30 天游客复查 | `tests/test_attachments_recheck_1008.py::test_tail_fresh_token_settles_gone_in_one_night` |
| 登录号落 /login、是游客 | 账号类（停车、要人处理） | 绝不判删帖 | `tests/test_attachments_recheck_1008.py::test_tail_login_wall_stops_and_never_judges_gone` |
| 读取服务超时 / 忙 / 断开 | 收尾段收工 | 第一次就停，不接着开页 | `tests/test_attachments_recheck_1008.py::test_tail_stops_on_first_service_failure` |
| 游客页出现安全验证 / 访问频繁（页面有验证词、没有 SSR 状态的验证页、461 / 471 状态码、跳到 website-login / captcha） | `TRANSIENT.WEB_PROBE_BLOCKED`（步骤级） | 游客段当晚停、不起浏览器兜底，没碰号 | `tests/test_attachments_recheck_1008.py::test_guest_fuse_and_captcha_stop`、`tests/test_attachments_recheck_1008.py::test_captcha_page_stops_before_guest_browser`、`tests/test_attachments_recheck_1008.py::test_captcha_variants_stop_without_browser` |
| 号正被同步 / lwa 占着 | 游客段让路 | 同 IP 不和号的活动叠在一起 | `tests/test_attachments_recheck_1008.py::test_guest_yields_when_account_is_busy` |
| 探到了附件但下载失败（超时 / 占位页） | `TRANSIENT.DOWNLOAD_FAILED` + 跨夜退避 1/2/4/7 天 | --all 退避到点后一晚试 1 次 | `tests/test_attachments_recheck_1008.py::test_download_backoff_across_nights` |
| 探到了但没记进声明（「全部已保存」谎报） | 本地对账 `_remember_probed` | 附件检查如实数「未下载」 | `tests/test_attachments_recheck_1008.py::test_reconcile_declares_found_file_and_turns_explore_evidence_into_gone` |
| 文件早下好了、标记没清（download_error） | 本地对账清标 | 算查清 | 同上 |
| 时间预算到了 | 不算失败，留给下次 | 按 220 秒/篇预留，积压期 40 篇 | `tests/test_attachments_recheck_1008.py::test_guest_budget_reaches_limit_with_220s_reserve` |
| 收尾段被跳过（号要处理） | 状态文件 `tail.skipped` | 面板如实说、不写「等到明早」 | `tests/test_attachments_recheck_1008.py::test_skipped_tail_is_recorded_and_shows_in_last_runs`、`tests/test_attachments_recheck_1008.py::test_nightly_skipped_tail_writes_status` |
| 附件页没下载按钮 / 有密码 / 损坏 / 转不了 | `NO_DOWNLOAD_BUTTON` / `PERMANENT.PDF_*` | 原件已保存；手动下载后「挂附件」 | 见上表与第 6 条 |

- **回归用例**：`tests/test_attachments_recheck_1008.py::test_guest_only_never_touches_account_and_runs_during_old_hold`、`tests/test_attachments_recheck_1008.py::test_guest_skips_when_hold_is_recent_or_switch_off`、`tests/test_attachments_recheck_1008.py::test_order_never_checked_first_then_oldest`、`tests/test_attachments_recheck_1008.py::test_tail_limit_five`、`tests/test_attachments_recheck_1008.py::test_repair_describe_recheck_reports_real_state`。

### 14. 验证窗口里没看到验证就解除，面板过时，手动同步再撞（10-04 / 10-08）
- **用户看到**：04:01 夜里「需要验证」；她点「打开验证」，窗口里没有滑块，关掉后面板还是「需要验证」；再点一次又空开了 12 分钟；05:11 点同步，05:19 又撞了验证。
- **根因**：①验证窗口只开到主页默认「笔记」页签，不碰出事的「收藏」；②关窗即解除，不要求窗口里出现过验证（读取组件 d7 已改：没出现过就保持熔断，给 `verify_result=no_captcha_seen`）；③Python 侧打开窗口就返回，不等结果、不先看熔断还在不在，面板靠下一次登录检查才变；④「页签点不动 / 列表卡住」这两个前兆出现后还在加码（d7 已改成前兆即停，回 `FAV_TAB_STUCK` / `stalled`）；⑤出事不留证据（d7 已落 `~/.link-brain/risk-evidence`）。
- **修法**（Python + 插件）：「打开验证」先只读看熔断，不在就不开窗口、按内存登录态刷绿；在才开，`--wait` 只轮询内存状态等窗口关掉，按 `verify_result` 如实回报（not_logged_in 优先）；关窗后熔断还在才给「没看到验证，恢复」，她亲手确认才发一次 `risk/clear`（`login --clear-hold --by-owner`，问题记录留痕，绝不进「全部修一遍」和夜跑）；扫码成功不等于熔断已解，看 `risk_hold`；验证提示改成「窗口打开后先点一下『收藏』页签」；撞验证当时就通知（面板没刷掉之前又撞一次新的照样推），熔断行写清「几点、在哪一步判到验证」，有证据给「查看截图」（证据路径不进记录 / 复制报错 / 通知，只给目录名）；设置页「立即同步」旁如实写「上次 HH:MM 判到验证」，**不拦、不冷却**（她 1008 定）。`HIDDEN_WIDGET`（看不见的验证组件）/ `FAV_TAB_STUCK`（页签点不动）只停这一次读收藏：TRANSIENT、退出 3，不挡当晚其它碰号步骤。
- **回归用例**：`tests/test_verify_hold_1008.py::test_open_verify_skips_window_when_no_hold`、`tests/test_verify_hold_1008.py::test_open_verify_wait_reports_no_captcha_seen`、`tests/test_verify_hold_1008.py::test_clear_hold_requires_owner_and_posts_once`、`tests/test_verify_hold_1008.py::test_login_success_with_captcha_hold_still_reports_hold`、`tests/test_verify_hold_1008.py::test_soft_stop_codes_do_not_exit_5`、`tests/test_verify_hold_1008.py::test_evidence_never_leaves_the_machine`、`tests/test_problems_dismiss_1008.py::test_captcha_pushes_again_on_new_incident`、`tests/test_problems_dismiss_ui.cjs`。

### 15. 评论楼层选了 10–50，很多笔记楼中楼还是缺（「楼中楼还缺 7 条（只存了前几楼的回复）」）（10-09）
- **用户看到**：笔记页顶上「楼中楼还缺 N 条（只存了前几楼的回复）」，挂着不动；她的理解是设定的 N 楼、每楼全部回复都要抓全。
- **根因**（10-09 真库只读实查 601 篇）：①521 篇是 10-08 以前入库的（读取组件还不报 `comment_load`），其中 195 篇前 10 楼缺回复、共 5863 条；
  续读排程（`pending_fills`）只认 `comment_load` 里登记的缺口，这批**永远排不上**（旧用例甚至断言它们不排）；②夜跑每晚只续 2 篇、
  一篇总共最多 3 次、同一篇隔 20 小时；③新读取组件入库的 80 篇前 10 楼 0 缺口——540 秒预算、每楼回复上限都不是这次的原因（每楼上限在读取组件里早已停用）。
- **修法 / 自愈**：缺口按存下的评论现算（`comment_fill.scope`，设置楼数内，老笔记照算）；两种续读：只展开缺口楼（expand_floors）/
  存下的楼不够就按楼数重读；一律并集合并（调小不删、删掉的评论留着），没多拿到不出新 RAW 版本，写新版本时图 / 视频引用旧文件（不重下、不重识图）；
  同一篇两次开页至少隔 45 分钟；不再按总次数封顶——**连着 3 次没多拿到**才停、进问题面板 `PERMANENT.COMMENTS_INCOMPLETE`（原因照实写，
  「再试一次」= 续读这篇一次，不进自愈轮）；原站多显示（`count_mismatch`）、楼已删（`floors_not_found`）不算缺口，页面照实标。
  后台补跑 `comments --fill-pending --until-done`：单实例、每篇自己拿账号锁、别的任务在等号就先让（「我在等」标记）、夜跑在跑 / 20 分钟内要开始就暂停、
  撞验证 / 掉登录就停下只看内存状态等她处理，处理好自动接着；夜跑那一步 40 分钟内没补完就转后台（`--then-background`）；
  楼数调大由插件自动拉起后台补跑。进度写 `_archive/comments-fill-status.json`，插件状态栏 / 设置页显示。
- **回归用例**：`tests/test_comments_fill_1009.py::test_old_note_gap_inside_floor_setting_is_scheduled_and_filled`、`tests/test_comments_fill_1009.py::test_raise_floors_loads_more_and_lower_never_deletes`、`tests/test_comments_fill_1009.py::test_union_merge_keeps_replies_the_site_no_longer_shows`、`tests/test_comments_fill_1009.py::test_no_progress_three_times_goes_to_problem_panel_then_resolves`、`tests/test_comments_fill_1009.py::test_count_mismatch_and_missing_floor_are_settled_not_gaps`、`tests/test_comments_fill_1009.py::test_fill_reuses_downloaded_media_and_does_not_redownload`、`tests/test_comments_fill_1009.py::test_worker_waits_out_captcha_without_opening_pages_then_resumes`、`tests/test_comments_fill_1009.py::test_worker_yields_to_nightly_and_waiting_tasks`、`tests/test_comments_fill_1009.py::test_polite_session_lets_waiting_task_go_first`、`tests/test_comments_fill_1009.py::test_nightly_step_has_no_two_note_cap_and_hands_over_to_background`。

### 16. 网页版要验证才给看的笔记：每晚补评论 / 附件 3 次「已放弃」，原因看不懂（10-10 / 10-11）
- **用户看到**：问题面板里同几篇反复「评论没补全」「附件没下好」，原因是 `feed <id> not found in noteDetailMap` 这种看不懂的字；
  她在浏览器里打开这些笔记是好的，「只是需要验证」。
- **根因**（10-11 诊断）：616 篇里约 59 篇在网页版被限制——收藏列表里不出现（`fav-tokens.json` 没有它）、读取服务打开详情页时页面上没有这篇
  （关键容器 8 秒不出现 → 评论 0 楼白滚 → 抽取找不到）；页面上没有看得见的验证（否则早按风控停了），读取组件当普通失败报，
  Python 评论补齐 / 附件补下各自重试 3 次再「已放弃」，第二晚再来一遍。
- **修法 / 自愈**：读取组件 1011 认出 `NOTE_RESTRICTED`（只是这一篇，不写熔断；号的事照旧按风控停，一点不放宽：看得见的验证 / 安全跳转写熔断，
  页面上有登录框记 `NOT_LOGGED_IN`）。Python 见到它：今天没为这篇搜过就用标题搜一次（`POST /api/v1/notes/search-token`，按 id 认出这篇拿新口令），
  歇 `LWA_FETCH_REST` 再用新口令开一次（开页前照旧 pace、拿着账号锁；每篇每天最多一次）；还不行就记进 `derived/restricted.json`、问题面板一条
  `note.restricted` · `PERMANENT.NOTE_RESTRICTED`（一篇一条、不推送、不刷次数，不算评论「没进展」、不报「附件没下好」），
  之后后台补评论 / 附件补下 / 碰号的附件补查都跳过这篇。笔记页评论区顶上一行「这篇在小红书网页版要验证才能看」+「打开验证」，
  问题面板那一行也有「打开验证」：开读取服务的笔记验证窗口到这一篇，她过完验证关窗——看到过这篇就清掉标记、记下窗口里的新口令、
  续读计数清零、附件退避清掉、拉起后台补评论（同一篇照旧隔 45 分钟再开），附件今晚 4 点补；没看到就照实说「再点一次」。
  号本身在熔断中时先走原来的熔断验证。
- **回归用例**：`tests/test_restricted_1011.py::test_reader_text_is_note_restricted_not_account_trouble`、`tests/test_restricted_1011.py::test_fill_restricted_searches_once_then_opens_with_fresh_token`、`tests/test_restricted_1011.py::test_fill_restricted_not_found_is_one_quiet_item_and_is_skipped`、`tests/test_restricted_1011.py::test_fill_pending_run_does_not_loop_on_restricted`、`tests/test_restricted_1011.py::test_search_hitting_account_trouble_stops_like_before`、`tests/test_restricted_1011.py::test_attachment_restricted_no_triple_retry_and_skipped_after`、`tests/test_restricted_1011.py::test_note_verify_passed_requeues_capture`、`tests/test_restricted_1011.py::test_note_verify_not_passed_keeps_mark`、`tests/test_note_restricted_1011.cjs`；读取组件 `note_verify_test.go`、`xiaohongshu/note_restricted_test.go`、`xiaohongshu/note_restricted_localbrowser_test.go`。

---

## 二、故障码对照（用户看到 → 常见根因 → 自愈动作）

「同次」= 那一步自己那次运行里的换策略重试；「自愈轮」= 夜跑收尾自动再修（✔ 自动 / — 不自动）；「现在修」= 面板按钮跑的动作。
风控 / 登录类（`NEEDS_HUMAN` 账号码）一律人工入口：不自动处理验证码、不自动清熔断。

| 码 | 用户看到 | 常见根因 | 同次 | 自愈轮 | 现在修 / 下一步 |
|---|---|---|---|---|---|
| `NEEDS_HUMAN.NOT_LOGGED_IN` / `CAPTCHA_REQUIRED` / `ACCOUNT_RISK` / `RISK_HOLD` / `ACCOUNT_BLOCKED` / `WRONG_ACCOUNT` / `NOT_INSTALLED` | 需要登录 / 需要验证 / 账号风控 / 风控暂停中 / 账号要处理 / 登错号 / 未安装读取组件 | 号掉登录、撞安全验证、被跳到风控页、熔断中、登的不是同步号、组件没装 | 立即停车，不重试 | — | 人工：扫码登录 / 打开验证 / 账号与同步 |
| `NEEDS_HUMAN.AUTH_FAILED` / `QUOTA_EXCEEDED`（step `ai.summary / ai.vision / ai.refine / ai.embed`，1008 起不按篇记） | AI key 失效 / AI 余额不足：一条写清哪个接口、哪把 key（尾号）、HTTP、原因、影响几篇、补齐约多少 token / 钱 | 401/403、欠费；向量索引拿不到 key | 不重试（重试没用）；同批连着 2 篇撞上就收手 | — | 人工：打开设置换 key / 充值，然后点这条的「现在修」补跑 |
| `TRANSIENT.NETWORK` / `HTTP_429` / `HTTP_5XX` / `SERVICE_BUSY`（step `ai.*`） | 连不上接口 / 限流 / 接口那侧出错：同样一条，带影响几篇 | 断网、代理没开、接口地址错、限额、服务抖动 | 同批连着 2 篇撞上就收手，这篇不记失败次数 | ✔ 补跑待补的识图 / 概要 | 接口好了自动补；也可点「现在修」 |
| `NEEDS_HUMAN.STUCK` | 连续几天没修好 | 同一步的临时故障连着 3 个日历日都在 | — | — | 「现在修」= 那一步各篇一起修 |
| `NEEDS_HUMAN.SYNC_STUCK` | 同步卡住了 | 一次同步占着号几小时没进展 | — | — | 人工：重启 Obsidian / 结束那个进程；下一晚夜跑开头自动消 |
| `NEEDS_HUMAN.BACKUP_DISK_MISSING` / `PORT_IN_USE` | 备份盘没挂 / 远程阅读端口被占用 | 外接盘没插 / 端口被别的程序占 | — | — | 人工 |
| `TRANSIENT.FAVORITES_SUSPICIOUS` | 收藏只读到一截 | 读取组件 `partial`、读回 0 条、比上次少一半以上 | 这一截的新收藏照抓；退出 3 | — 今晚绝不重读 | 等到下次夜跑（写明几点）；之后才给「现在修」= 重新同步（距上次读 ≥ 30 分钟） |
| `TRANSIENT.FAVORITES_FAILED` / `TIMEOUT` / `DISCONNECTED` / `BUSY` / `SYNC_FAILED` / `TOO_MANY_FAILURES` / `ACCOUNT_BUSY` / `INTERRUPTED`（sync.favorites） | 读收藏没成功 / 读取服务超时 / 没在运行 / 正忙 / 同步没做完 / 连续失败 / 号被占 / 被打断 | 机器卡、读取服务没起、号被别的任务占 | 夜跑 exit 1 等 25 分钟重试一次 | — 不重读列表 | 「现在修」= 重新同步（距上次读 ≥ 30 分钟，否则写明等到几点） |
| `TRANSIENT.RATE_LIMITED` | 刚刚同步过 | 读取服务 10 分钟限频 | — | — | 等 10 分钟（写明几点） |
| `TRANSIENT.DISCONNECTED` / `TIMEOUT` / `BUSY`（ingest 步骤级） | 读取服务没在运行 / 超时 / 正忙 | 读取服务没起来 | — | ✔ 检查读取服务、没在跑就拉起 | 同左 |
| `TRANSIENT.WEB_PROBE_BLOCKED`（ingest / attachments.recheck 游客段）/ `PROBE_FAILED`（attachments.recheck 收尾段） | 网页那侧被拦 / 附件没查清 | 游客网页被登录墙 / 验证挡住；登录号也没看清 | 游客段无条件保险丝；收尾段服务失败第一次就收工 | — | 面板写真实队列位置（排第几、预计哪天、碰号补查为什么没跑、几晚没进展），不再天天「等到明早」；见第 13 条 |
| `TRANSIENT.HIDDEN_WIDGET` / `FAV_TAB_STUCK`（sync.favorites） | 收藏这次先停了 / 收藏页签点不动 | 页面里有验证组件但没显示滑块 / 收藏接口疑似限流 | 读取组件当场停、不熔断；退出 3 | — 今晚不再重读 | 下次同步照常读；见第 14 条 |
| （1009 撤掉）`TRANSIENT.AI_PENDING` | 卡片上不再标「待补识图 / 概要」：轻量版本来不做；开了 AI 后台静默补，状态栏一行进度 | — | — | ✔ enrich --pending 补 | 不用处理；回归 `tests/test_card_problems_1008.py::test_item_problems_drops_stale_api_codes_when_ai_health_clear`、`tests/test_card_problems_1008.py::test_light_mode_shows_no_ai_badges` |
| `TRANSIENT.DOWNLOAD_FAILED` | 附件没下好 | 504 / 超时 / 网页占位页 / 文件头不对 | 带退避重下，最多 3 次 | ✔（号没出事、离上次开这一篇 ≥ 20 分钟） | 「现在修」= 重下这篇附件；不行就手动下载后「挂附件」 |
| `TRANSIENT.SERVICE_BUSY` / `STEP_TIMEOUT`（attachments.convert） | 服务正忙 / 步骤超时 | 本地 OCR 没起来、超时 | 歇几秒当场再转一次 | ✔ 强制重转 | 同左 |
| `PERMANENT.PDF_ENCRYPTED` / `PDF_DAMAGED` / `DOC_UNSUPPORTED` / `CONVERSION_FAILED` | 全文没转出来 | 有密码、文件坏、格式不支持 | 字节照存，不删不重下 | — | 「现在修」= 再强制转一次；原件已保存 |
| `TRANSIENT.HTTP_5XX` / `HTTP_429` / `NETWORK` / `SERVICE_BUSY`（vision.layer1 / enrich.summary） | 接口暂时出错 / 限流 / 网络不通 / 服务正忙 | 模型接口抖动、限额 | 识图请求网络抖动重试 1 次；概要：重试 1 次 → 换文本 AI 模型 | ✔ 重跑这篇识图和概要 | 同左；不行到设置里点「测试」 |
| `TRANSIENT.RETRY_EXHAUSTED` | 连着几次没补成 | 识图 / 概要连着 3 次没补成 | — | ✔ 重跑这篇（不等退避） | 同左 |
| `TRANSIENT.STEP_CRASHED`（vision.layer1 / enrich.summary） | 步骤中途出错退出 | 识图 / 概要代码意外异常（正文已入档） | 不阻断入档，照样渲染笔记 | ✔ 重跑这篇 | 同左 |
| `PERMANENT.MODEL_OUTPUT_INVALID`（enrich.summary） | AI 结果不可用 | 概要两次都不是合法 JSON | 第二次把「只回 JSON」说死 → 换文本 AI 模型 | — | 「现在修」= 重跑这篇 |
| `PERMANENT.MODEL_OUTPUT_INVALID`（vision.refine） | AI 结果不可用 | 精细识别真复读 / 截断 / 流程图格式坏（1008 起长段落不再误判，见第 11 条） | 原样 → 换参数 → 换模型 → 退回第一层结果 | — | 「再试一次」= 放弃了的图重新精细识别；修过没好的不进「全部修一遍」；可「隐藏」 |
| `TRANSIENT.SERVICE_BUSY` / `HTTP_*` / `NETWORK`（vision.refine 步骤级） | 接口连着不通 | 免费 key 限额、兜底模型也不通 | 429 换 key、503 歇一会儿同 key 再试、全不行退回设置里的模型 | ✔ 补跑 10 张 | 同左 |
| `TRANSIENT.*`（videos.transcribe） | 服务正忙 / 步骤超时 | 转写服务没起、抽音轨超时 | 转写服务没起：当场拉起（CapsWriter）再转 | ✔ 拉起后重转这条 | 同左；不行到设置里测试语音识别 |
| `PERMANENT.NO_SPEECH` / `NO_AUDIO` | 视频里没人说话 / 没有音轨（画面上也没认出字幕） | 纯音乐 / 没音轨，且没有画面字幕 | 没人声也抽画面字幕；读出字幕就不登记 | — | 不用处理；「现在修」= 重读一次画面字幕 |
| `TRANSIENT.*`（embed） | 网络不通 / 接口暂时出错 / 限流 | 向量接口抖动 | 每批退避重试最多 3 次 | ✔ 重建语义索引 | 同左；不行确认千问兼容接口的 key |
| `TRANSIENT.STEP_TIMEOUT` / `STEP_CRASHED`（nightly.<步骤>） | 步骤超时 / 中途出错退出 | 那一步超时被停、崩溃 | — | ✔ 补跑那一步的一小段（目录 / 识图 / 概要 / 转写 / 索引 / 补附件） | 同左；碰号的那几步号出事时不跑 |
| `TRANSIENT.INTERRUPTED`（nightly.run） | 被打断 | 上一晚夜跑被系统强停 / 断电 | — | — | 等下一晚夜跑走完自动消（写明几点） |
| `TRANSIENT.SECRET_TIMEOUT` | 取 AI key 超时 | 密码库卡住 | 没 key 照跑，退回设置里的模型 | — | 人看一眼密码库 |
| `PERMANENT.STEP_ARGS` | 程序和夜跑脚本版本对不上 | 夜跑脚本给的参数程序不认 | — | — | 更新程序或夜跑脚本 |
| `PERMANENT.NOTE_GONE`（只上卡片） | 原帖打不开 | 删了 / 仅作者可见 / 审核中（分不清，所以不说「已删除」） | — | — | 不用处理，本地存档还在；30 天游客复查一次 |
| `PERMANENT.REMOTE_TASK_FAILED` | 远程阅读的计划任务没弄好 | 计划任务注册失败 | — | — | 设置 → 远程阅读 关掉再打开 |
| `PERMANENT.CHECKSUM_MISMATCH` / `BAD_PACKAGE` / `DISK_FULL` | 组件校验不过 / 包不对 / 磁盘不够 | 只在安装命令结果里出现 | — | — | 设置 →「开始」重装；先腾空间 |
| `SKIPPED.*` | 未配置 / 已关闭 / 额度到了 / 已退回普通方式 / 旧设置已换算 | 没开、没配 | — | — | 不是问题，不计数 |
| `PERMANENT.COMMENTS_INCOMPLETE`（step `comments.fill`） | 评论没补全：设置楼数内的楼中楼还缺 N 条、原因、连着几次没多拿到 | 展开按钮点不动 / 被限频 / 评论区滚不动，连着 3 次续读都没多拿到 | 同一篇隔 45 分钟再续；没进展计数 | — 不自动（同一篇反复开页伤号） | 「再试一次」= 续读这篇一次（`comments <id> --fill`）；补齐了自动消；不想看可隐藏；见第 15 条 |
| `PERMANENT.NOTE_RESTRICTED`（step `note.restricted`） | 网页版要验证（卡片角标 + 问题面板一条 + 笔记页一行，都带「打开验证」） | 小红书网页版限制了这一篇（她的浏览器里打开要验证），读取服务打开时页面上没有它；不是号的问题 | 今天没搜过就用标题搜一次新口令、歇一会儿再开一次 | — 不自动（要她亲手过验证） | 「打开验证」= 开验证窗口到这篇（`note-verify <id> --wait`），过了自动补抓评论 / 附件；可隐藏；见第 16 条 |
| `PERMANENT.NOTE_DAMAGED`（step `render.check`） | 笔记页被改坏（两栏散了 / 正文没了），打开时就地提示一次 | 手改 md 删了受管标记 / 属性 / 批注块，或把两栏块换行拆开 | 打开时提示「恢复」，不弹窗不阻断 | 默认关（`LINK_BRAIN_AUTO_RESTORE=1` 才自动；24 小时没动才跑，失败不再自动） | ⋯ 菜单「恢复这篇」/「从快照找回…」；回归 `tests/test_note_damage_1009.py`、`tests/test_restore_1009.py`、`tests/test_note_tools_1009.cjs` |

入档不被阻断（B2.4）：同步 / 导入时识图、概要、附件、转写都在入档之后单独做；渲染时识图或概要出意外只登记一条（`TRANSIENT.STEP_CRASHED`，正文已入档），笔记照写——`tests/test_self_heal_1004.py::test_render_survives_vision_crash`。
