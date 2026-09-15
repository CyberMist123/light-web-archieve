# Current State

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
- 源文件 `C:\Users\18717\Downloads\_.md`，31 条去重后 31 篇。第一轮 17 篇成功落盘，
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
  MCP 无法读私密收藏。解法不是 MCP：外部读取器 `favdump.exe`（在 `C:\Users\18717\.xiaohongshu-mcp`，
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
- **每晚调度已挂**（仓库外）：Windows 计划任务 `XhsFavSync` 每天 04:00 跑 `xhs-fav-sync.ps1`（清 slate → sync-favorites → 掉登录才 Bark/TG 报警），脚本在 `C:\Users\18717\.xiaohongshu-mcp\xhs-fav-sync.ps1`，日志 `~\.xiaohongshu-mcp\fav-sync.log`。

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
