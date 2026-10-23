# 唯一数据来源排查（1023，只读，未改代码）

范围：仓库代码和文档（看不到本机 `~/.link-brain/` 和 vault，涉及实际数字的地方引用 `BUGS-1023.md` / `STATE.md`）。行号以 `8d3a1a8` 为准。
每类数据分四段：**现状**（在哪、谁写、谁读）· **重复 / 矛盾** · **建议唯一来源** · **派生何时重建**。最后是迁移计划。

---

## 0. 结论先说

| 数据 | 现在几处 | 建议唯一来源 |
|---|---|---|
| 账号 | accounts.json 三个字段 + 各模块各取各的 + 插件 `settings.nickname`（同名不同义） | 新 `accounts.current()` / `accounts.pinned()`，按 **user_id** 认号 |
| 是不是收藏 | `ingest_kind` / `favorited_by` / `relations.ingest_kind` / `provenance.collected_by` 并集 | `favorited_by`（带账号），读一律走 `provenance.is_favorite(meta)` |
| 专辑 | 只有 `albums.json`，无账号键、文件不存在 | `albums.json` schema 2，按 user_id 分区 |
| 模型名 | data.json + ai_config 迁移常量 + `vision.GEMINI_MODEL`(env) + keyprobe + llm-config.yaml + pricing.json recommended | data.json（经 `ai_config.load()`）；推荐列表只用于「填空」 |
| 价格 | pricing.json + 用户覆盖 + `visual.PRICES` + llm-config.yaml `pricing` + keyprobe 直读 | `estimate.load_pricing()`（包内 + 用户覆盖），外加一个 `pricing.cost_of()` |
| 预算 | budget.py 默认 3 + settings-pages.js / settings-v6.js 各写一份 3 | `budget.DEFAULT_YUAN`，经状态接口给前端 |
| 密钥 | data.json + keyFile CSV + 多个 env + config.json `gemini_keys_file/_cmd`；providers 和 nightly 两套顺序 | `providers.resolve_key()` / `providers.pool_keys()` 一处 |
| 篇数 | 目录页（按来源过滤）/ 问收藏页（全部）/ fav_counts（磁盘）/ index.db | catalog-data 里写好的 `counts`，页面只读 |
| 派生缓存 | catalog-data 只在部分路径重建 | 一个 `catalog.mark_dirty()` + 统一重建入口 |
| 页面标题 / 文案 | `'Collections'` 三处、错误文案 Python/JS 两份、problems 分组两份、回答提示词两份、sync 默认两份 | `lb-page-lib.js` 常量 + Python 导出的 registry |

---

## 1. 账号（accounts）

**现状**
- `~/.link-brain/accounts.json`：读 `accounts.py:114 config()`，写 `:124 save()`。
  - `nickname` / `user_id`：登录、切换时写（`accounts.py:736`、`:779`），换号 / 退出清空（`:833`）。
  - `sync_account`（钉住的同步号）：只有 `favorites.py:654` 写，且只在为空时写，值是**昵称**。
  - `endpoint`：`accounts.py:131 endpoint()`，env `LINK_BRAIN_XHS_ENDPOINT` > 配置 > `DEFAULT_ENDPOINT`（`:39`）；`:309` 又单写了一份端口 18061。
- 「当前账号」各取各的：
  - 普通同步 `favorites.py:275-276`：nickname = 读取服务返回的实际登录号 > 配置；user_id 却取**配置**。
  - 快照模式 `favorites.py:594-595`：nickname = `sync_account` > 配置，不看实际登录 → `:651-655` 的认号检查永远通过。
  - 认号 `favorites.py:651-655`：只比**昵称**（改昵称误报 WRONG_ACCOUNT，同名放过）。
  - 打标去重 `favorites.py:807/814`：`user_id or nickname`；调用门槛 `:399`：昵称空就整段跳过。
  - 显示 `catalog.py:513`：`nickname or user_id`；本人判断 `ask.py:1547-1552`：user_id 或 nickname。
- 插件 `main.js:194 settings.nickname`：只是批注署名（`annotate-view.js:20/393/463`），和 accounts.json 无关，**同名不同义**。
- meta.json 的 `mcp_endpoint`：`ingest.py:273` / `adapters/xiaohongshu.py:1060` 写的是导入时算好的 `xhs.MCP_ENDPOINT`（`adapters/xiaohongshu.py:34`），不是调用时的 `accounts.endpoint()`。

**重复 / 矛盾**
- 一次同步里 `favorited_by` 可能写成「新号昵称 + 旧号 user_id」（昵称来自实际登录，id 来自配置）。
- 三套「是谁」的键：昵称（认号）、`user_id or nickname`（打标）、`user_id 或 nickname`（问答）。
- 只能钉一个同步号 → 第二个号同步必报 WRONG_ACCOUNT（BUGS #8）。

**建议唯一来源**
- `accounts.py` 出两个函数：`current()`（读取服务实际登录号的 `{user_id, nickname}`，拿不到就返回 None，**不拿配置顶替**）和 `known()`（accounts.json 里登记过的号列表，按 user_id 为键）。
- `sync_account` 改成存 user_id；认号、打标、问答、目录筛选全部按 user_id 比，昵称只作显示。快照模式也调 `current()`。
- 插件 `settings.nickname` 改名 `annotatorName`（迁移时读旧键），避免误认。
- meta.json 的 `mcp_endpoint` 删掉或明确标成「导入时记录」，代码里不得读它当地址。

**派生**：无派生文件；`favorited_by` 的正确性依赖这里。

---

## 2. 收藏关系（ingest_kind / favorited_by / fav-list）

**现状**
- `meta.ingest_kind`：只在 `ingest.py:268 _build_meta` 写。来源：`catch.py:128` 固定 `shared`、CLI `--ingest-kind`（`ingest.py:807`、`cli.py:21`）、收藏同步 `favorites.py:378` = `favorite`。
  - 续读 / 复用媒体路径 `ingest.py:782` 保留旧值；完整重抓 `ingest.py:686/715` 用**本次**传入值；命中（hit）不重写 meta。
  - 副本：SQLite `relations.ingest_kind`（`index.py:65/219/308`），读者 `synclog.py:479`。
- `meta.favorited_by`（`[{nickname,user_id,first_seen}]`）：唯一写入 `favorites.py:804-822 tag_account`，唯一调用 `:400`；重建 meta 时保留（`ingest.py:693/786`）。catch、CLI 单篇（即使 `--ingest-kind favorite`）、restore 都不写。
- `_archive/fav-list.json`（`favorites.py:88`）：全量替换 / 增量并到前面；读者 `fav_counts.py:5/85`、快照模式 `favorites.py:585+`、`setup/backfill.py:4`。**无账号键**。
- `_archive/fav-tokens.json`（`attachments.py:1335`，写入 `favorites.py:283`）：读者附件补抓、`restricted.py`。**无账号键**。

**读的口径各不同**
| 读者 | 口径 |
|---|---|
| `provenance.py:17 collected_by`、`fav_counts.py:69` | `favorited_by or ingest_kind=="favorite"` |
| `synclog.py:479` | 只看 `relations.ingest_kind='favorite'` |
| `catalog.py:513`（按账号筛） | 只看 `favorited_by` |
| `STATE.md:178` backfill 口径 | 只看 `favorited_by` |

**1400 vs 1425 怎么来的**
- `favorited_by` 多出的 25 篇：先被 catch / CLI 以 `shared` 入库，后来出现在收藏列表；同步命中只调 `tag_account` 加上 `favorited_by`，`ingest_kind` 不改。另一条：收藏过的帖被 catch 完整重抓，`ingest_kind` 被覆盖成 `shared`（`ingest.py:686`），`favorited_by` 被 `:693` 保留。
- 反方向（`favorite` 但没有 `favorited_by`）也存在可能：0926 之前的收藏没打标、同步时昵称空（`:399`）、`tag_account` 写失败被吞（`:820`）、CLI `--ingest-kind favorite`。

**建议唯一来源**
- 「是不是收藏」= `favorited_by` 非空，读一律走新的 `provenance.is_favorite(meta)`；`ingest_kind` 降级为「第一次怎么进来的」历史字段，**永远不覆盖**（`ingest.py:686/715` 改成保留旧值）。
- `relations.ingest_kind` 不再用于判断收藏；`synclog.py:479` 改读 `is_favorite`（或 relations 加 `is_favorite` 列，由 upsert 时从 meta 算）。
- 一次性迁移：`ingest_kind=="favorite"` 且无 `favorited_by` 的，按 fav-list 里能对上的账号补标；对不上的记 `favorited_by:[{user_id:null, nickname:null, first_seen:<入库时间>, legacy:true}]`。
- `fav-list.json` / `fav-tokens.json` 改成 `{schema:2, accounts:{<user_id>:{...}}}`。
- FORMAT.md 补 `favorited_by`、`fav-list` schema 2、两字段的主次关系。

**派生**：`src`（catalog-data 每条）由 `collected_by` 算 → 会随口径变，见 §7 篇数。

---

## 3. 专辑（albums）

**现状**
- `_archive/albums.json`（`albums.py:32-33`），`{schema:1, boards:{id:{name, notes:[note_id]}}}`，读写 `:36-48`，合并 `merge_list` `:72+`。
- 目录合并 `catalog.py:408-412 note_albums()`，异常吞掉返回空；写进每条 `albums`（`catalog.py:495`）。
- meta / frontmatter 都没有专辑。文件不存在 → 全部为空且不报错（BUGS #8）。

**矛盾**
- 无账号键；列表读全后 `merge_list` 删掉不在列表里的专辑 → 第二个号同步会清掉第一个号的专辑。`favorited_by` 带账号，两边对不上。
- 专辑同步不触发 catalog 重建（`albums.py` 无 build 调用）。

**建议**：`albums.json` schema 2：`{accounts:{<user_id>:{boards:{...}, synced_at}}}`，`merge_list` 只动当前号那一块；`note_albums(account=None)` 返回并集，目录按账号筛时传 user_id。albums.json 不存在时在问题面板挂一个「专辑没同步」，不静默。同步完调 `catalog.mark_dirty()`。FORMAT.md 补规格。

---

## 4. 模型名 / 价格 / 预算 / 用量

### 4a 模型名
**现状**
- data.json（经 `ai_config.py:247 data_json_path()` + `:365` 叠默认）是声称的唯一来源；`DEFAULTS` `:79-128` 模型多为空。
- 设置之外写死的模型：
  - `ai_config.py:277-280` 迁移常量 `qwen3.7-flash / qwen3.8-flash / qwen3.8-max / deepseek-v4-flash`（迁移时只在内存补）。
  - `vision.py:391-392 GEMINI_MODEL = env LWA_GEMINI_MODEL or "gemini-3.5-flash"`（隐藏 env），被 `vision.py:125-127/406/420/428` 和 `ai_routes.py:111-112` 直接用；`:428` 还把模型名改成「gemini-3.5-flash（免费 key N）」——若进账本 `m` 字段，价格永远查不到（待核）。
  - `semantic.py:45-50` 兜底 `text-embedding-v4`；`keyprobe.py:32 EMBED` 写死 `qwen3.7-text-embedding-flash`；`llm-config.yaml:25` 也写了 embedding 模型（文件头 `:2-3` 自称不放模型名）。
  - `ai_config.py:105-112` 的 CLI 命令和 `main.js:175` 不一致（后者少加固参数，靠 `text_stream.harden_command` 运行时补）。
  - `pricing.json:133-146 recommended/alternatives`：经 `usage-ui.js:102` 写进 data.json；`setup/estimate.py:11/207` 也用。
- 运行时实际模型（STATE.md:29）`gemini-3.5-flash`、`gemini-embedding-2` 在 pricing.json 里没有。

**建议**：模型只在 data.json；`GEMINI_MODEL` 改成读 `visionAI.refineModel`（迁移时把 env 值写进去一次），`ai_routes` 读同一个函数。`llm-config.yaml` 的 `embedding.model` 和 `pricing` 删掉。迁移常量只留在 `_migrate_legacy` 内部，不得被别处 import。账本 `m` 字段只写原始模型名，「免费 key N」放单独字段。

### 4b 价格
**现状：五处**
1. `link_brain/pricing.json:29-131`（规范表，`usd_cny` `:4-9`）。
2. 用户覆盖 `~/.link-brain/pricing.json`，只由 `setup/estimate.py:30-42 load_pricing()` 合并。
3. `visual.py:71-81 PRICES`（6 个千问，元）→ `visual.py:558` 填 `cost_yuan` → `vision.py:475-549` 求和 → `nightly.py:592-596` 夜跑「花费」。Gemini / DeepSeek 记 0，覆盖文件不读；`qwen3-vl-plus`、`qwen3.7-plus` 只在这里有价。
4. `assets/llm-config.yaml:7-10`（`qwen3.7-flash` USD）→ `llm.py:76-80 price_of` → `llm.py:459/476 cost_usd_est`。和 pricing.json 的元价换算后不一致。
5. `keyprobe.py:35-36 _pricing()` 直读包内文件，不看用户覆盖。

走 `load_pricing()` 的（覆盖生效）：`usage.py:143-158 cost_of`、`budget.py:47-75`、`ai_routes.py:45-69/141`、`ai_health.py:88/110-135`。

**「查不到价」各说各话**：`usage.cost_of` → None（未计价）；`ai_routes.py:58-61` → 「免费」；`budget.is_paid` → 免费、不限额；`visual.cost_yuan` / `llm.price_of` → 0。→ Gemini 绕过每日预算。

**供应商猜测三份**：`usage.py:50-64 provider_of`、JS 抄本 `settings-pages.js:41-47 providerOf`、`ai_health.py:82-100 provider_name`（多了 moonshot 等，千问叫法不同）、`keyprobe.py:22-29 PROVIDERS/LABEL`。

**建议**
- 新 `link_brain/pricing.py`：`table()`（= 现 `estimate.load_pricing()` 挪过来）、`price_of(model)`（名字 + aliases）、`cost_of(row)`、`is_free(cfg)`、`provider_of(endpoint, model)`。所有算钱 / 判费 / 猜供应商只调它。
- 删 `visual.PRICES`、`llm-config.yaml` 的 `pricing`；`keyprobe._pricing` 改调 `pricing.table()`。
- 「查不到价」只有一种结果：`unpriced`（显示「—，未计价」，预算按**付费**处理，宁可多拦）；「免费」只来自显式标记：pricing.json 里 `free: true`，或 CLI、或 Gemini 免费 key 池（对齐 1023 拍板「免费的 CLI 和 Gemini 免费 key 不计费」）。
- 补价：`gemini-3.5-flash`、`gemini-embedding-2`（免费池调用标 free）。
- JS 侧 `providerOf` 删掉，改读后端在用量接口里给的 `provider` 字段。
- 用量按模型 / 供应商分组（`usage.month_summary` 加维度，BUGS #9）。

### 4c 预算
- `budget.py:20 DEFAULT_YUAN = 3.0`，`:25-39` 读 `budget.dailyYuan`；前端 `settings-pages.js:213-228`、`settings-v6.js:191-192/323-333` 各写一份 3。
- 建议：前端只显示 `budget.status()` 返回的 `daily_yuan`（已有，`ai_routes.py:128-144`），删前端常量。

---

## 5. 密钥

**现状**
- `providers.py:222-243 resolve_key`：`apiKey` → `keyPool` → `keyFile/keyField`（外部 CSV，`:93-108`）→ `apiKeyEnv`（如 `DASHSCOPE_API_KEY`）。空池直接报错，不往下落（`:225-229`）。
- Gemini 池 `providers.py:112-117/131-145`：env `LWA_GEMINI_KEYS` → `~/.link-brain/config.json` 的 `gemini_keys_file`（`storage.py:33-44`）。`gemini-keys.txt` 代码里不出现，应是该配置指向的文件。
- **第二套 Gemini 读法** `nightly.py:503-541 refine_keys`：`visionAI.refineKeysEnv` 指的 env → `LWA_GEMINI_KEYS_CMD`/`gemini_keys_cmd`（跑 shell）→ `LWA_GEMINI_KEYS_FILE`/`gemini_keys_file`；支持 `#` 注释和 env 展开（providers 不支持），再注入子进程 env。
- `vision.py:125/406`：先 `pool_alive("gemini")`，否则 `refineKeysEnv`。
- `rerank.py:76` 兜底 `DASHSCOPE_API_KEY`；`ai_config.py:283-296` 迁移时复用 textAI 的 keyFile。
- 插件：`main.js:2661/3275` 写 `apiKey`；「配好了没」判断 `main.js:36-49/897/3249` 不认 `keyPool`。
- 远程口令 `remote/secret_box.py`、`remote/store.py:138-146/313-315`：独立体系，不在本次范围。

**建议**
- data.json 存「去哪拿」（`apiKey` 明文 / `keyPool` / `keyFile` / `apiKeyEnv`），**取值只在 `providers.resolve_key()` 和 `providers.pool_keys(name)`**。`nightly.refine_keys` 删掉，改调 `pool_keys("gemini")`；`_CMD` / 注释 / env 展开并进 providers 一处。
- 插件「配好了没」改读后端 `ai_routes` 给的 `key_state`（已有池计数 `ai_routes.py:56`），不再自己判断。
- `ai_config.py:1-4` 的「唯一数据源」措辞改成「唯一**配置**来源；密钥值可以在外部文件/env，由 providers 解析」。

---

## 6. 派生缓存与重建

### 6a 清单
| 文件 | 构建 | 输入 | 备注 |
|---|---|---|---|
| `_archive/catalog-data.json` | `catalog.build` `catalog.py:651`；局部 `patch_items` `:788`（星标）、`drop_items` `:821`（删除） | meta.json、可见 md frontmatter、notes.json、albums、topics、问题上下文（`collect` `:402`） | 同时重写页面和 index-data（`:669`） |
| `_archive/index-data.json` | `indextree.build` `indextree.py:1138` | 索引.md + catalog-data items + 词表 | 无变化跳过（`:1000`）；随 catalog 一起漏 |
| `problems-summary.json` | `problems.write_summary` `problems.py:554/564` | problems.jsonl + `sync_state.page_state` | 每次问题写入和 sync-status 写入都刷，覆盖好 |
| `sync-status.json` | `sync_state.record/progress` `sync_state.py:10/134` | — | 中断只在 `load_fixing` `:63` 时才落盘成 INTERRUPTED |
| `index.db` | `index.upsert_object` `index.py:112`，全量 `:256-280` | meta.json | 每次 ingest 实时更新，**最新**；但没有页面读它的篇数 |
| `semantic.db` | `semantic.py:284` | catalog-data items | 随 catalog-data 一起旧 |
| fav_counts | 每次现算 `fav_counts.py:27/81` | 磁盘对象目录 + 墓碑 + fav-list | 第三套篇数口径 |

依赖 catalog-data 新鲜的读者：`export_bundle.py:14`、`playlist.py:44`、`topics.py:282`、`problems.py:937`、`restore.py:255`、`semantic.py`。

### 6b catalog-data 什么时候重建 / 漏在哪
| 事件 | 重建？ | 位置 |
|---|---|---|
| 夜跑 | ✅ | `nightly.py:105,130` |
| 插件手动刷新 / 插件导入网址循环结束 | ✅ | `main.js:788…3211`、`:2357`；`library-ui.js:143` |
| 评论补齐 / 附件 / 视频 / pdf / 分类编辑 | ✅ | `comment_fill.py:1098…`、`attachments.py:1088`、`videos.py:287`、`pdftext.py:225`、`topics.py:296` |
| 删除 | 局部 `drop_items`，失败才全量 | `remove.py:214-224` |
| 星标 | 局部 `patch_items` | `note.py:148,220` |
| **同步完成** | ❌ | `favorites.py:1009-1023`、`favorites.run :1026`、插件 `syncNow main.js:946-953`（只有顺带补评论才碰巧重建） |
| **同步中断 / 失败** | ❌ | `favorites.py:999-1001`；`sync_state.load_fixing` 只刷 problems-summary |
| **单篇导入（catch / MCP / TG / CLI）** | ❌ | `catch.py:283`、`ingest.py:633,698,792` 只 upsert index.db |
| **从快照恢复** | ❌ | `restore.py:289,333` |
| **专辑同步** | ❌ | `albums.py` |
| **改来源 relabel** | ❌（注释叫人手动跑） | `provenance.py:34-37` |
| 改标题（笔记）/ 改标签 | ❌（标签页面读 Obsidian 缓存，标题等下次 build） | `catalog-view.js:562` |

→ BUGS #3「今日新增筛不到」就是前两行 + 单篇导入。目录页只会**提示**过期（`catalog-view.js:2448-2452` 比 sync-status 时间和 `built_at`），不会自愈。

### 6c 建议
- 新 `catalog.mark_dirty(reason)`：写 `_archive/catalog-dirty.json`（`{since, reasons[]}`，原子写）。所有改动 catalog 输入的写入方（ingest 末尾、`tag_account`、`albums.merge_list`、`remove`、`restore`、`relabel`、同步 `finally` 段——**包括中断**）只调它，不自己 build。
- 一个重建入口 `catalog.ensure_fresh(max_wait)`：dirty 存在且没有别的 build 在跑就重建（复用 CONVENTIONS §6 的锁）；调用点：同步 `finally`、catch 结束、插件打开目录页 / 问收藏页时、夜跑。`patch_items`/`drop_items` 保留为快路径，但同样清 dirty。
- index-data / semantic.db 继续跟着 catalog.build，不另设触发。
- catalog-data 里加 `source_fingerprint`（对象目录数 + 最新 meta mtime），页面发现和 `fav_counts.library_total` 对不上时显示「数据在更新」而不是旧数。

---

## 7. 篇数（1403 vs 1437 vs 1460）

两页读的是**同一份** `catalog-data.json`，差在过滤：
- 目录页 `catalog-view.js:556-560`：`activeSrc=''`（默认「我的收藏」），`items = allItems.filter(src==='')`；表头 `:2434-2441`、概览「全部收藏」`:3277-3283`、分类栏「全部」`:1030` 都用过滤后的 `items.length`。只有来源下拉显示 `全部（allItems.length）` `:1058`。
- 问收藏页 `chat-view.js:43` `items = data.items`，`paintSub` `:762-768` 显示 `items.length`，**不过滤来源**。
- `src` 由 `provenance.collected_by`（`provenance.py:16-25`，写在 `catalog.py:511`）算：收藏 / 本人手动 = `''`，否则是「聊天分享」、项目名、agent 名。
- ⇒ **1437 = 全部，1403 = 我的收藏，差的 34 篇是聊天分享 / agent 收的。**（在目录页「来源 ▾」里可验证：应显示 `全部（1437）`、`我的收藏（1403）`。）
- 两个都比磁盘上的 1460（BUGS #6）少 23 = 10/22 中断同步的 22 篇 + 10/23 单篇导入 1 篇，即 §6b 漏的重建。
- 另外还有第三、四个口径：`fav_counts.counts().library_total`（磁盘目录 + 墓碑，`fav_counts.py:27-38/81`，同步进度条 `favorites.py:493-496`、同步记录首行 `synclog.py:613`、backfill）；索引面板 `idx.total`（`catalog-view.js:1602`，来自 index-data）。

**建议**：`catalog.build` 在 catalog-data 顶层写 `counts: {all, mine, by_src:{...}, by_account:{user_id: n}, trash}`，所有页面显示篇数只读它，并且**标签写明口径**（「我的收藏 1403 · 全部 1437」）；问收藏页默认显示 `all` 但文案写「全部 1437 篇」，或与目录页共用 `LB.countLabel(data, src)`。`fav_counts.library_total` 只给同步进度用，并在不等于 `counts.all + 待重建` 时触发 `mark_dirty`。

---

## 8. 页面标题与文案

**现状**
- `catalogTitle`：插件设置 `main.js:190`，改标题 `:663-665`，保存并广播 `link-brain:catalog-prefs` `:1335-1338`。**BUGS #4 已在 `e7d0907` 修**：`chat-view.js:754-755` 也读它。剩下的重复：兜底 `'Collections'` 写了三处（`catalog-view.js:719`、`chat-view.js:755`、`main.js:664-665` 占位）。
- 页面通道：设置只经 `LB.provider()`（`lb-page-lib.js:110`）实时读 + workspace 事件；Python 生成的数据经 `_archive/*.json`。这个双通道本身是对的。
- 页面文件名 `catalog.py:35/584`（`小红书收藏目录.md`、`收藏搜索.md`、`星标收藏.md`）：CONVENTIONS §8 明确保留，靠 `lb-page` 找页，不算重复。
- 重复的文案 / 表：
  - problems 分组：`problems.py:222 GROUP_OF_CLASS` 被 `problems-ui.js:31` 手抄；`ACTION_TEXT` 只在 JS（`problems-ui.js:34`），键和 `problems.py:52 DEFAULT_ACTION` 相同。码表本身已经走 `registry_for_js()`（`catalog.py:647`），是好例子。
  - 步骤名：`problems.py:80 STEP_LABELS` 和 `ai_health.py:30 STEP_LABELS` 两份。
  - 报错转人话：`errtext.py:10` 和 `home-ui.js:149 errText` 两份。
  - 回答提示词：`main.js:156 DEFAULT_ANSWER_PROMPT` 和 `ai_config.py:55`（及 `:60` 旧版）两份。
  - 同步默认值：`main.js:198` 和 `ai_config.py:128 DEFAULTS["sync"]`（注释写「手工对齐」）；`commentFloors` 归一化规则不同（Python `:237-244` 夹到 10–50/"all"，JS `main.js:3175-3178` "all"→2000）。
- 与 CONVENTIONS §8 冲突：失败回滚文案 `home-ui.js:530`「原来的设置没动」、`:566`「原来的选择没动」、`main.js:3177`「已改回原来的楼数」（应为「没保存上，开关已拨回原来的位置：…」）；`catalog-view.js:1638` 用户可见「N 个大类」（应为「分类」）。问收藏页内「目录」既当页面名又当回答内目录（`chat-view.js:899/2089/2094/2109`），易混。

**建议**
- `lb-page-lib.js` 出 `LB.pageTitle()`（含 `'Collections'` 兜底），三处改调它；`main.js` 占位也 import 同一常量（插件可 require 资产或在插件里定义后挂到 provider 上，页面读 `provider().DEFAULTS`）。
- Python 侧导出一个 `ui_registry.json`（随 catalog.build 写，和 problems registry 同路）：problems 分组 / 动作文案、步骤名、sync 默认值、默认回答提示词；JS 只读它。`errtext` 同理：后端返回结果时已带人话（CONVENTIONS §1），JS 的 `errText` 只做「没有人话时」的兜底且不得复制规则。
- §8 文案违规按表改；`test_terms_x5.cjs` 设为必过。

---

## 9. 迁移计划

原则：每批只动一类来源；先加「守卫测试」（列出现存重复，标为已知例外，**新增**重复即红），再迁移，迁完把例外清空。守卫统一放 `tests/test_single_source.py` 和 `tests/test_single_source.cjs`，靠 grep/AST 扫源码。

### 第 0 批：守卫 + 文档（不改行为）
- 加 `tests/test_single_source.py`：
  - 价格：除 `pricing.json` / `pricing.py`（第 2 批后）外，源码里出现 `PRICES =`、`"pricing":`（yaml）、直接 `open(...pricing.json)` 即红。白名单暂含 `visual.py`、`llm-config.yaml`、`keyprobe.py`。
  - 模型名：`link_brain/**/*.py` 里出现形如 `qwen\d|gemini-\d|deepseek-|gpt-4o` 的字符串字面量，只允许在 `ai_config._migrate_legacy`、`pricing.json`、测试里。
  - 收藏判断：`ingest_kind\s*==\s*["']favorite` 和 `favorited_by` 的读取只允许在 `provenance.py`。
  - 账号：`.get("nickname")` / `.get("sync_account")` / `.get("user_id")` 作用在 accounts 配置上的只允许在 `accounts.py`。
  - 密钥：`LWA_GEMINI_KEYS`、`gemini_keys_file`、`apiKeyEnv` 只允许在 `providers.py` / `storage.py`。
- 加 `tests/test_single_source.cjs`：`'Collections'` 字面量只允许 1 处；`providerOf` / `errText` 规则表不得出现在 JS；`problems-ui.js` 不得定义 `GROUP_OF_CLASS`。
- FORMAT.md 补 `favorited_by`、`albums.json`、`catalog-data.counts`（规格先行）。

### 第 1 批：派生重建 + 篇数（用户可见问题最大：BUGS #3、篇数不一致）
- `catalog.mark_dirty` / `ensure_fresh`；同步 `finally`（含中断）、catch、restore、relabel、albums 调 `mark_dirty`。
- catalog-data 加 `counts`；两页篇数都读它并写明口径。
- 测试：
  - pytest：模拟同步中途抛异常 → `catalog-dirty.json` 存在 → `ensure_fresh` 后新帖在 items 里、`built_at` 更新。
  - pytest：`catch.run` 一篇后 dirty；`restore` 后 dirty。
  - pytest 守卫：所有调用 `index.upsert_object` 的模块必须同一函数里调 `mark_dirty`（AST 扫）。
  - node：同一份 sample catalog-data 喂目录页和问收藏页，两页显示的「全部」数字相等，且等于 `counts.all`。

### 第 2 批：价格 / 预算 / 用量（BUGS #9）
- 新 `pricing.py`，删 `visual.PRICES`、yaml `pricing`、`keyprobe._pricing`、JS `providerOf`、前端预算默认 3；补 Gemini 价与 `free` 标记；「查不到价」统一 `unpriced` 且预算按付费拦；用量按模型 / 供应商分组。
- 测试：
  - 守卫转严格（白名单清空）。
  - pytest：同一条账本行，`usage.cost_of`、`budget.spent_today`、夜跑「花费」、`ai_routes` 显示的钱数相等。
  - pytest：未知模型 → 四处都显示未计价，`budget.is_paid` 为 True。
  - pytest：用户覆盖价格对 `keyprobe` 生效。
  - pytest：pricing.json 每个模型名在 `recommended`/`alternatives` 中都可解析；`STATE.md` 列的运行时模型都有价（或 `free`）。

### 第 3 批：模型名与密钥
- `GEMINI_MODEL` 进 data.json（迁移写一次）；`nightly.refine_keys` 并入 `providers.pool_keys`；插件「配好了没」读后端 `key_state`。
- 测试：pytest 同一组 env/config，`providers.pool_keys("gemini")` 与夜跑子进程拿到的 key 列表相同；守卫：`os.environ.get("LWA_GEMINI` 只在 providers；模型名字面量守卫转严格。

### 第 4 批：账号 + 收藏关系 + 专辑（BUGS #8，动数据格式，需要她拍板）
- `accounts.current()/known()`，按 user_id 认号，快照模式也看实际登录；`sync_account` 存 user_id；插件 `nickname`→`annotatorName`。
- `provenance.is_favorite`；`ingest_kind` 不再覆盖；`fav-list` / `fav-tokens` / `albums.json` schema 2 带账号键；一次性迁移脚本（`--dry-run` 先出报告：多少篇补标、多少篇 legacy）。
- 测试：
  - pytest：A 号同步后 B 号同步，A 的专辑仍在；`favorited_by` 两号都有；不报 WRONG_ACCOUNT（多号登记过时）。
  - pytest：改昵称后同一 user_id 同步不报错；同昵称不同 user_id 报错。
  - pytest：catch 重抓一篇已收藏帖后 `is_favorite` 仍为 True。
  - pytest：迁移脚本跑两遍结果相同（幂等），`count(is_favorite)` 在迁移前后 = 并集口径的数。
  - 守卫转严格。
- ❓待她拍板：多号是否都算「我的收藏」；legacy 收藏归哪个号。

### 第 5 批：文案与 UI 共享表
- `LB.pageTitle()`；`ui_registry.json`（problems 分组 / 动作、步骤名、sync 默认、默认回答提示词）；`errText` 规则只在 Python；§8 违规文案改正；`test_terms_x5.cjs` 设必过。
- 测试：node 守卫（`'Collections'` 1 处、`GROUP_OF_CLASS` 不在 JS、`DEFAULT_ANSWER_PROMPT` 只在 Python）；pytest：`ui_registry.json` 的 sync 默认 == `ai_config.DEFAULTS["sync"]`；node：`commentFloors` 归一化对同一组输入与 Python 结果一致（共用 fixture）。

顺序理由：第 1 批修的是她每天看到的错数；第 2 批纯后端、风险低、修钱数；第 3 批依赖第 2 批的 `pricing.py`/`provider_of`；第 4 批改数据格式、要迁移和拍板，放后；第 5 批只动 UI，可和 2/3 并行。

## 10. 1023 她拍板后的执行表（取代 §9 的批次顺序）

规则：多个号的收藏、网页导入 = 我的收藏；TG 发来的网址 = Fable。不做「按单篇选择存不存视频」。按 GPT 架构图的分层立约定，不一次大搬家；每批一个 PR、她审过再合。

| 批 | 层 | 内容 | 必加测试 | 状态 |
|---|---|---|---|---|
| 0 | 全部 | 守卫测试 `test_single_source.py/.cjs`（现存重复列白名单，新增即红）；`docs/TEST-MAP.md` 功能→测试对照、标出缺口；FORMAT.md 补 favorited_by / albums / counts | 守卫本身；白名单数 = 本文档列出的重复数 | 待做 |
| 1 | ⑤ 派生 | `mark_dirty` + `ensure_fresh`（同步含中断、catch、restore、relabel、albums）；build 幂等（内容没变不写页面 md / 脚本，版本不含 built_at）；重建合并；catalog-data `counts`，两页篇数读它 | 中断同步后新帖进目录；catch 后 dirty；同输入连跑两次 build 不改任何文件 mtime；两页「全部」数相等 | 待做 |
| 2 | 横切配置 | AI 配置表（API / CLI 平级，功能声明可用类型；概要可选 OpenCode）；`pricing.py` 统一价格、免费只认显式标记（CLI / Gemini 免费池）；预算默认只在后端；密钥只经 providers；后端把表给设置页 | 四处钱数相等；未知模型 = 未计价且预算拦；CLI 行记模型名且显示免费；夜跑与 providers 拿到同一组 key | 待做 |
| 3 | ③ 规则 | `is_favorite` / `collected_by`：TG → Fable；ingest_kind 不再覆盖；accounts 按 user_id；fav-list / fav-tokens / albums 带账号键；迁移脚本先 dry-run | 换号同步不清别的号的专辑；重抓不丢收藏；迁移幂等；TG 帖来源 = Fable | 待做 |
| 4 | ① 界面 | 标题 / 文案 / 问题分组 / 默认值从后端表读；§8 违规文案改正；`test_terms_x5.cjs` 必过 | `'Collections'` 只 1 处；JS 不含规则表 | 待做 |

可并行、不等上表：GitHub 找 skill（尤其旅行，注意许可证、内容当不可信）；纯样式待办。要等：B 站 / 网页入口等第 1、3 批；手机 / 网页 PWA 等第 2 批。

## 附：本次没核实 / 待确认
- `vision.py:428` 的「（免费 key N）」标签是否进了账本 `m` 字段（会让 Gemini 永远查不到价）。
- BUGS #9 里「cli 空模型名 321 次未计价」：`usage.cost_of` 对 `p="cli"` 返回 0，未计价的那 321 条可能是没标 `p=cli` 的行，需看真账本。
- `chat-view.js` 是否真的监听 `link-brain:catalog-prefs` 就地换标题（注释说会，未逐行核）。
