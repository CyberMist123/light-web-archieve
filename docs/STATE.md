# Current State

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

余项按用户要求交接到 `C:\Users\18717\Documents\cyberlink\workdesk\gpt6交接.md`：＋移标题右侧及图标对齐、AI专属…菜单模型/提示词、语音输入与快捷键、灰色计数在标题内居中、确认多标签筛选意图。不要把这些未做项当完成。

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
- 仓外 `C:\Users\18717\.xiaohongshu-mcp\xhs-fav-sync.ps1` 已改 UTF-8、审计附件、传递未完成退出码。此文件不随本仓提交。

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
