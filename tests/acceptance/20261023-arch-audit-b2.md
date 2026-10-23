# 1023 ARCH-AUDIT 第 2 批验收记录（2026-10-23）

云端会话，Linux + Python 3.13 venv，不是 Obsidian 实测。Obsidian 里只能她验的列在文末「待她：一步」。

范围（ARCH-AUDIT §10 第 2 批）：价格统一到 `link_brain/pricing.py`；「免费」只认显式标记；预算默认值只留后端；密钥只经 providers（夜跑并进去）；接口和本机命令行平级（概要能选 OpenCode）。

## 一、改了什么（她能感觉到的）

| 项 | 以前 | 现在 |
|---|---|---|
| 价格 | 五处：pricing.json、用户覆盖、`visual.PRICES`（夜跑「花费」用它）、`llm-config.yaml` 的 `pricing`（概要估价用它，美元）、`keyprobe` 直读包内文件 | 只有 pricing.json + 用户覆盖，读法只在 `pricing.py`；夜跑花费、概要估价、账本、预算、设置页同一套算法。`qwen3-vl-plus`、`qwen3.7-plus` 的价从 `visual.PRICES` 挪进 pricing.json |
| 查不到价 | 四种说法：未计价 / 「免费」/ 预算不拦 / 0 元 | 只有一种：未计价（设置页写「—，未计价」，夜跑写「另 N 次未计价」），**预算按要钱的拦** |
| 免费 | 价格表里没有 = 免费（Gemini 因此绕过每天上限） | 只认：本机命令行；Gemini 免费 key 池（`keyPool: gemini`，以及识图 / 精细识图里轮的免费 key）；价格表里写了 `"free": true` 的 |
| Gemini 价 | 表里没有 `gemini-3.5-flash` / `gemini-embedding-2` | 两行都加了；付费档单价官方页没核到（打不开），按表的规矩写 `null` = 未计价；走免费 key 池的调用记 `free: true`、0 元 |
| 每天上限默认 3 元 | 后端一份、设置页两处各写一份 | 只在 `budget.DEFAULT_YUAN`；设置页显示后端给的 `daily_yuan` |
| 供应商 | JS `providerOf` 自己按接口地址猜 | 删了；读后端每一格给的 `provider` |
| Gemini 免费 key 从哪来 | providers 一套（环境变量 → key 文件），夜跑另一套（再加命令、注释、路径里的环境变量） | 只在 `providers.pool_load`：环境变量 → 取 key 的命令（同一进程只跑一次）→ key 文件，支持 `#` 注释和路径展开；夜跑调它 |
| 本机命令行 | 命令写在插件默认值和 Python 默认值两处（插件那份少了加固参数）；概要只能「和问收藏一样 / 接口 / 不写」 | 命令只在 `ai_config.CLI_PRESETS`（Codex / Claude Code / OpenCode）；插件只存 `preset`。概要多一个「本机命令行」，下拉列后端表里的命令行（含她问收藏下拉里自己加的「OpenCode DS4.1」那种），也能自己写命令 |
| 账本里的命令行 | `m` 常是空的（BUGS #9：321 次空模型名） | 记程序名 + 模型（如「claude sonnet」「opencode」），0 元 |
| 概要 extracted.json | `cost_usd_est`（美元，查不到记 0） | `cost_yuan_est`（元，查不到 `null`）；FORMAT.md 已改，旧文件两种都可能遇到 |

## 二、入口 · 步骤 · 预期 · 实测

| 项 | 入口 | 预期 | 实测 |
|---|---|---|---|
| 四处钱数相等 | pytest：一次 qwen3.8-max 识图（假接口回 10 万 / 2 万 token） | 执行器 cost_yuan（夜跑花费）= `usage.cost_of` = `budget.spent_today` = 设置页 `ai_routes` 的钱 | `test_same_call_same_money_everywhere` 过（都是 ¥1.92） |
| 未知模型 | pytest | 执行器 None + unpriced、账本 None、边栏 unpriced=1、设置页「—，未计价」、`is_paid` True、到上限照样拦 | `test_unknown_model_is_unpriced_everywhere_and_budget_blocks` 过 |
| 免费只认标记 | pytest | 同一个 gemini-3.5-flash：付费 key 要钱，keyPool/free/cli/价格表 free 才免费 | `test_free_only_from_explicit_marks`、`test_gemini_pool_call_is_logged_free`（账本 `m` 只写原始名） |
| 夜跑「花费」 | pytest | 有未计价时写「另 N 次的模型不在价格表里，未计价」 | `test_refine_tally_reports_unpriced_not_zero` 过 |
| 用户覆盖价 | pytest：写 `~/.link-brain/pricing.json` | `keys detect` 给的模型跟着覆盖走；账本按覆盖价算 | `test_user_price_override_reaches_keyprobe_and_ledger` 过 |
| 价格表 | pytest | recommended / alternatives 每个模型都查得到；STATE.md 列的运行时模型都在表里，Gemini 两个走免费池 = 免费 | `test_pricing_table_resolves_recommended_and_runtime_models` 过；`test_pricing_table_sane` 改成允许 `null`（note 里必须写「未计价」） |
| CLI 平级 | pytest | 概要选 `preset: opencode` → 解析出命令；账本 `p=cli m=opencode` 0 元；设置页「免费（本机）」、标签「本机 opencode」 | `test_cli_row_records_model_name_and_shows_free`、`test_summary_can_pick_opencode_preset`、`test_default_cli_models_only_carry_presets` 过 |
| 概要下拉 | node `test_ai_settings_ui.cjs` | 方式多「本机命令行」；选了出「用哪个命令行」，选项来自 `usage --table`；选 OpenCode 只存 preset | 过 |
| 预算默认 | pytest | `budget.status({})` = DEFAULT_YUAN；两个设置页源码里没有 3 的兜底 | `test_budget_default_only_in_backend` 过 |
| 同一组 key | pytest，四种来源（环境变量 / 命令 / key 文件 / 路径带 `$VAR` 的 key 文件）+ 设置里改了变量名 | `providers.pool_keys("gemini")` 和夜跑 `refine_keys()` 一模一样；命令一个进程只跑一次 | `test_nightly_and_providers_get_same_gemini_keys`×4、`test_renamed_env_from_settings_is_used_by_both`、`test_key_cmd_runs_once_per_process` 过；原 `test_batch5_delivery` 两条（命令只注入那一步、命令超时登记 SECRET_TIMEOUT 照跑）照过 |
| 真实入口 | `python -m link_brain usage`（临时收藏库：她那种配置——问收藏 DeepSeek、概要 OpenCode、识图 Gemini 免费池；账本 4 行） | 今天 ¥1.56（只有 qwen3.8-max 那行花钱）、未计价 1（没标免费的 Gemini 行）；上限 3.0 来自后端；概要「本机 opencode · 免费（本机）」；识图「免费 · 2 把轮流用」 | 照预期 |
| 真实入口 | `python -m link_brain usage --table` | 秒回，不读账本；概要 modes = inherit/http/cli；命令行 Codex / Claude Code（Sonnet）/ OpenCode | 照预期 |
| 真实入口 | 临时 `~/.link-brain/config.json` 指 key 文件（带注释行） | 夜跑 `refine_keys()` 和 `providers.pool_keys` 都是 `['g1', 'g2']` | 照预期 |
| 守卫 | `tests/test_single_source.py` | 本批白名单清空：价格表、Gemini 密钥来源、供应商猜测、前端预算默认值、CLI 命令抄本；写死的模型名去掉 visual.py；新增「价格读法」（不许再 `estimate._price` / `load_pricing` 直读、`refineKeysEnv` 只在 providers 读） | 12 条过 |

## 三、测试汇总（和 main 8d3a1a8 同一环境对比）

- `python -m pytest -q`：main 上 40 条失败 / 报错（`test_remote_mcp` 等依赖版本问题，和本改动无关）；本分支同样这 40 条，**没有新增**。新增 `tests/test_pricing_1023.py` 17 条全过。
- `node tests/run-node.cjs`：逐个文件的过 / 挂 / 跳过和 main **完全一致**（12 个挂的是缺 msedge 等本机环境问题，UI 层 19 过 / 7 挂 / 3 跳过，同 main）。
- 改了旧测试的地方（都是本批有意改的行为）：`test_console_1018` 的「免费」样例加 `keyPool: gemini`、多两句断言（没标免费的 Gemini 要钱、查不到价要钱）；`test_setup.test_pricing_table_sane` 允许 null；`test_llm` 改认 `cost_yuan_est`；`test_batch5_delivery` 去掉对已删的 `_keys_env_name` 的替身；`test_settings_pages_1016.cjs` 删 JS `providerOf` / `providerRows` 的用例、改成断言它们不在了；`test_ai_settings_ui.cjs` 概要方式多一项 + 命令行下拉用例。

体验预算：设置页 AI 页仍一次 `usage`（多带一张小表）；概要选了命令行时多一次 `usage --table`（不读账本，本机实测秒回），一个窗口只读一次。没有新增页面重绘。

## 四、没做 / 要知道

- **旧账本不回补**：10-23 以前的 Gemini 免费池调用没有 `free` 标记，仍算「未计价」（和以前一样不计钱），从这版起的新调用记 0 元。
- **到了每天上限，没标免费、又查不到价的模型会被拦**（以前当免费照跑）。她的配置里 Gemini 走 `keyPool: gemini`，不受影响；如果哪一项是直接填的 Gemini key（不是池），到上限后会停，要么改成 keyPool，要么在 `~/.link-brain/pricing.json` 给它写价或 `"free": true`。
- 取 key 的命令（`gemini_keys_cmd`）以前只有夜跑会跑；现在插件里点「测试识图」等、后端要用免费 key 时也会跑一次（同一进程只一次）。
- 没做：用量按模型分组（BUGS #9 第一条）、`GEMINI_MODEL` 进 data.json（第 3 批）、`ai_health.provider_name` / `keyprobe.PROVIDERS` 的显示名表（第 3 批跟模型名一起）、「关掉视频下载」用例（TEST-MAP 里列在第 2 批，本次范围外）。

## 待她：一步

更新插件和后端后，在 Obsidian 里：

1. **设置 → AI（或「更多 → 每项功能用哪个模型」）**：顶上「每天上限」显示的是你原来存的数（没存过显示 ¥3），改成别的数回车，提示「每天上限改成 ¥N」；关掉设置再打开，数还在。
2. 同一页「每个功能用谁」：识图 / 精细识图里 Gemini 那格写「免费」，鼠标停上去看到「key：N 把轮流用」；百炼 / DeepSeek 那格写「约 ¥…」。如果有哪格写「—，未计价」，截图给我（那个模型价格表里没有，到上限会被拦）。
3. 展开「概要 · 打标签」→「写概要用的模型」下拉：多了「本机命令行（不要 key、不花钱）」。选它 → 下面出「用哪个命令行」，里面有 Codex / Claude Code（Sonnet）/ OpenCode，以及你问收藏下拉里的「OpenCode DS4.1」。选「OpenCode DS4.1」，点「测试概要模型」，应能出一段概要。
4. 测完想换回来：同一个下拉选回「和问收藏一样」。
5. 「花了多少：各功能明细」折叠：跑过一次命令行概要后，「概要」一行调用数 +1、金额不变。
6. 问收藏页右下的模型下拉：Codex、Sonnet 还在、能用（插件新装时它们现在只存 preset，命令由后端补）。
7. 等一晚夜跑后看 `~/.link-brain/nightly.log` 的「[识图补跑]」那行：「免费 key 可用 N 个」和以前一样；如果有「另 N 次…未计价」，把那行发我。
