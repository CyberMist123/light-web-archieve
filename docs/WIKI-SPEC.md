# 个人 Wiki 规格（10-29 起）

改个人 Wiki 之前先读这页。数据格式和 `pwiki` 命令的逐字段说明在 `docs/FORMAT.md`「个人 Wiki」一节；以后要和别的页面一起统一的样子在 `docs/WIKI-UNIFY-LATER.md`。设计稿和原型不在仓库里（作者本机 `design-1028-wiki/`，含 `prototype.html` 结构原型、`from-design/prototype.design.html` 设计版原型和 `design.md` 视觉规则）。

## 1. 是什么、为什么

她自己写的知识页：和「浏览收藏 / 问收藏」平级的第三页「Wiki」。两个用处（她 10-28）：① 以后找收藏有入口；② 慢慢长成自己的知识库，不用每次从 0 重新搜。

**她定下的原则**（改的时候别违背，要改先问她）：

| 原则 | 出处 |
|---|---|
| 数据库（收藏）提供材料，Wiki 的结构由她的思考决定；只有她主动引用的内容才进正文，不自动堆资料 | 10-28 |
| 尽量和问收藏的风格对齐；平时只看到正文；控件少（参照目录页筛选设计稿那种简洁） | 10-28 |
| 随时能改：点哪段改哪段，不用先点「编辑」；标题层级随时能调 | 10-28 |
| 目录照问收藏的浮动目录；Ctrl+F 才出搜索 | 10-28 |
| 不用双链（不提示、不补全 `[[ ]]`），目录 + 拖动排序就是组织方式 | 10-28 |
| 文件夹（大类）页是自由文档；「OPEN / 当前理解」这类分组只是建议，不写死 | 10-28 |
| 关系图挂在目录顶上，能展开、能固定；要像 Quartz（quartz.jzhao.xyz）那样会动 | 10-28 / 10-29 |
| 视觉照 Collection+ 纸墨风格（设计稿「非常好看，就这个风格」）；数字用 Cormorant 斜体；不要柱图 | 10-28 |
| 页头切换先沿用胶囊，以后三页一起统一 | 10-29（见 WIKI-UNIFY-LATER） |
| 历史要能比较、恢复；不需要用户装 Git（RELEASE-BAR P8） | 10-29 |

## 2. 文件地图

| 文件 | 管什么 |
|---|---|
| `link_brain/personal_wiki.py` | **唯一写手**：页面读写、快照历史、冲突检测、外部编辑记录、改名、删除进 `.trash`、索引 `_archive/wiki-index.json`、导入、`pwiki` CLI |
| `link_brain/assets/wiki-view.js` | Wiki 页面脚本（Dataview 块里跑；前面内联 `lb-page-lib.js` + `catalog-search.js`）。直接读 `PersonalWiki/*.md`，写一律经插件 |
| `obsidian-plugins/link-brain-actions/main.js` | `wikiCall(op, {args, input})`：所有写操作 → `python -m link_brain pwiki …`，插件级排队；命令「打开个人 Wiki」 |
| `link_brain/catalog.py` | 刷新目录时生成 `_archive/wiki-page.js` 和库根 `Wiki.md`（`lb-page: wiki`）；`library_pages` 认 `wiki` |
| `link_brain/assets/chat-view.js`、`trash-view.js` | 页头三页切换里的「Wiki」按钮 |
| `link_brain/assets/lb-page-lib.js` | `LB_PAGE_STYLE_IDS` 含 `lb-wiki-style`（共用样式排在页面样式前面） |
| `tests/test_personal_wiki_1029.py` | 后端 |
| `tests/test_wiki_view_1029.cjs` | 页面（假 DOM + 逼真的假 `wikiCall`：共用假磁盘、按磁盘核 `base_hash`、可延迟、可失败一次） |
| `link_brain/wiki_page.py` | 10-31 从 personal_wiki 拆出的纯函数（解析 / hash / 派生 / 扫目录），不碰 storage——问收藏 / MCP 的检索只用它，免得把写手卷进大 import 环 |
| `link_brain/wiki_plan.py` | 10-31「按我的思路搭框架」：出计划 / 按节检索（问收藏同一套）/ 只引编号 / 原话核对 / 只往节下补 |
| `link_brain/wiki_ai.py` | 10-31「让 AI 改」：一段 / 整页，只回建议不写盘；提示词（RULES + PRESETS）在这里；`pwiki ai` 由 `__main__` 直接转给它 |
| `link_brain/personal_wiki_search.py` | 10-31 问收藏 / MCP（`pwiki` 工具）读 Wiki：搜标题 / 标签 / 正文；问收藏把命中页作为「她的判断」放进提示词（不进来源编号） |
| `tests/test_wiki_view_1031.cjs`、`tests/test_personal_wiki_1031.py`、`tests/test_personal_wiki_search_1031.py` | 10-31 整理：原地编辑、AI 改、目录、搜索、删除找回；后端轻入口 / 找回 / AI 提示词；检索 |

## 3. 数据（摘要，细节见 FORMAT.md）

- 一页 = `vault/PersonalWiki/<标题>.md`，文件头 `id · title · role(page|topic) · index_tag · order · tags · created · updated`，正文是唯一主副本。Obsidian 里直接改也行（会记成「外部编辑」）。
- 文件夹 = `role: topic` 的页 + 它的 `index_tag`；页面带哪个文件夹的标签就在哪个文件夹里（可多个）。文件夹里的顺序 = 文件夹页的 `order`（目录里拖出来的）。编号按建立先后。
- 收藏引用 `[标题](lwa:<item_id>)`，`item_id` 是目录数据里的完整 id（带来源前缀，如 `xhs-…`）；页面也认不带前缀的短 id（唯一匹配时）。
- 历史 `.history/<id>/`（整页快照 + `log.json`），删除 `.trash/`，都不进索引。
- `hash` = 文件全文（CRLF→LF）SHA-1 前 16 位；页面和后端同一算法，保存时带 `base_hash` 防覆盖。

## 4. 页面

- **页头**：刻线大标题 · 「…」 · 历史钮；三页切换胶囊 + 篇数行。
- **浮动目录**（左）：工具行（回首页 · 搜 · 全部收起 / 展开 · 新页面 · 收起目录）；MAP 关系图（展开 / 固定，有「全局图」）；编号文件夹 → 页面 → 当前页 H1–H4 小标题；底部标签。
  10-31：默认只展开当前页所在的文件夹（她手动开关过的照她的，记在 `lb-wiki-prefs.open`）；当前页那行自动滚进目录视野；滚正文时目录里当前小节加粗 + 左线；「收起目录」= 整栏收起、正文居中，左下角「目录」再打开（记住）；拖页：同文件夹内排顺序，拖到别的文件夹的页 / 文件夹名 = 换文件夹（改标签 + 排进那边的 order），拖到「未归类」= 拿出文件夹；文件夹里没排过的页按建立先后（以前按修改时间，改一下就跳位置）；新页建在文件夹里自动排到末尾。Ctrl+F 搜标题和正文（正文命中带那一句），回车开第一「页」。
- **首页**：OVERVIEW 四个数字（全部页面 · 近 7 天改过 · 引用的收藏 · 文件夹）· INDEX 文件夹物件（未归类 · 新文件夹）· MAP 全局关系图。
- **文件夹页**：大编号 + 名字 + 自由文档（可放 ` ```pages ` 自动列表）+ 没写进正文的页列在 MORE。
- **普通页**：标题即输入框 · 元信息（日期 · 字数 · 引用数 · 标签）· 正文。
- **标签页**：同标签的页 + 收藏里带这个标签的（只当材料，不自动进正文）。
- **历史**：页内右侧栏：版本列表、和现在的逐行差异、恢复、保存版本。
- **编辑（10-31 重做，她：「不要跳出来一个巨大的黑框，就正常改」）**：原地改——编辑框套在和阅读时同一个元素里（p / h2 / li / blockquote），字号缩进全继承，点开不跳；列表按条开、标题按行开，行首记号不显示，引用的长 id 显示成 `@1`（存时换回）；浅色小工具条（正文 / H1–H3 / 列表 / 待办 / AI 改）宽屏放在正文右边空白里。Enter = 下一条 / 下一段（光标后的字带过去），空的一条再 Enter = 结束列表，段落开头打 `#` `-` `1.` `[]` `>` 换样子，开头 Backspace 去记号，Tab 缩进，↑↓ 走到上 / 下一块，Ctrl+Enter 在后面开新段落，段左边悬停 ＋ 在中间插一段，Esc 收起；Ctrl+Z（不在输入框里时）撤销上一步（也存盘）。`@` 搜收藏插入引用。「…」里有整页 Markdown、新页面、新文件夹、让 AI 改整页、最近删除、重新读入、删除这一页。
- **让 AI 改（10-31 晚重做，她：「ai 是对 wiki 整体改，不是单行。还有选中段落不方便」）**：范围不用拖选——编辑时点工具条「AI 改」= 光标所在那一节（上一个小标题到下一个同级小标题）；页面上拖选了字 = 浮出「AI 改选中的 N 段」；「…→让 AI 改整页」= 整页（右侧栏）；空页「让 AI 先搭个框架」。范围里的段在等 / 看的时候虚线框锁住、点了不开编辑。现成说法（润色 / 精简 / 说清楚一点 / 改成列表 / 只改错字；整页：理顺结构 / 精简 / 从引用补要点 / 搭个框架 / 润色）+ 自己说（记住最近 6 条）。模型输出走 `<replacement>…</replacement>` 外框（只认最外一层；没外框时剥代码块和中文开场白 / 收尾兜底，`wiki_ai._clean`）。结果先按行对齐、改过的行再按字（中文）/ 词（英文）比，每一处可单独点掉，「用选中的 N 处」一次拼好经 `pwiki save`（kind=ai，note 记用了几处）存——Ctrl+Z 一步撤；等的时候别处加删了行会跟着挪（按原文重新定位），那一截原文本身被改了就作废不套用；AI 丢了引用会提示。模型 = 插件设置里的文本 AI；提示词在 `wiki_ai.py`。
- **按我的思路搭框架（10-31 第二块，她：「我给一段文字，但我有我的思路，ai 根据我的思路，把资料、wiki 框架配齐」）**：「…→按我的思路搭框架」或空页的按钮，右侧栏：写思路 → AI 出计划（每节小标题 + 去收藏里搜什么 + 这一节回答什么）→ 她改 / 删 / 加节 → 「按这个去收藏里找」：每节用问收藏同一套检索（`retrieval.retrieve_payload`，不现调扩词模型），候选收藏全页一套编号 S1…；模型只许引编号、每条带一句原帖原话；程序换成 `[标题](lwa:id)`、删掉不存在编号的整条、核对原话是原帖逐字子串（去空白比，对不上的在正文标「⚠」、面板里红框列出）；她写的字一行不动——已有同名小标题的补在那一节末尾，没有的在页尾新开；和她相反的说法放「### 相反的说法」。结果照上面逐处勾选再存（kind=ai）。后端 `link_brain/wiki_plan.py`（`pwiki plan` / `pwiki fill`，`__main__` 直接转过去）。真库实测一次 3 节：出计划约 18 秒，补材料约 2.5 分钟，用了 10 篇收藏、原话全对上。
- **删除**：先确认；提示里带「撤销」；「…→最近删除」列出 `.trash` 里的页一键找回（Obsidian 不显示点开头的文件夹）。首页 / 标签页不显示历史钮。
- **右侧原文**：点收藏引用 = 插件 `openArchiveSource(item.note, 页面容器)`，和问收藏同一个原文窗格。
- **只读**：没插件 / 手机 → 能看、能跳、能开原文，不能改。

## 5. 写盘模型（改这里要特别小心）

GPT（Codex）前后审了 6 轮，几轮都在这一层找到「丢字 / 旧内容盖新内容」的竞态，最后改成下面的结构（`wiki-view.js` 写盘一节开头有 ①–⑥ 注释）。**新加任何会改页面的功能，都必须走这套，不许开旁路**：

1. 每页一条串行队列：保存、恢复、覆盖、记版本、删除都排进去。
2. （10-31 改）只有「整页换掉」的操作——恢复、删除、冲突后重读磁盘——进行时这一页只读（`_hard`：标题框、待办、整页 Markdown 框、拖动、标签都不收；点某段等它做完再开，期间正文被换过就不开）。普通保存不锁页：在后台排队，还没轮到的那次合成一次、轮到时存那一刻的最新内容；以前每存一次锁 1.5 秒，Enter 下一段要干等。保存失败时草稿里放的是她手上的全部（这次要存的 + 之后又改的 + 编辑框 / 整页 Markdown 框里还没收的字），编辑框收起、Markdown 框作废，正文按 ⑤ 换掉；普通保存成功不重画（她可能正在标题 / 标签框里打字），正文被换过（`_repaint`）才重画。
3. 要写的内容在**进队那一刻**定下（含编辑框里已经打的字），之后不再从界面补收；唯一入口 `mutate` / `change`。
4. **重画只画，不存**；只有 Esc / 失焦 / 换页 / 整页 Markdown 自动保存（框没冻住）这几个提交点会存。
5. 失败：这次的内容进页顶「没保存上的改动」草稿（新的顶掉旧的，存在本库 localStorage `lb-wiki-drafts`）；CONFLICT 换成磁盘版本，其它错误回到上次存上的样子。提示用固定句式「没保存上，内容还在，可重试：<原因>」。
6. 「用我这份覆盖」= 一份正文、一次保存；只有这次存上才删草稿。

后端那一侧：写前再读一次磁盘（`_ensure_fresh`），扫描之后 Obsidian 又改过就记「外部编辑」并拒绝覆盖；改名是先整个挪到新名字再写内容（不会出现两份同 id）。

## 6. 样式规矩

- 颜色只用 Obsidian 变量 / `--lb-*` 令牌（纸和墨，橙红只给状态）；字体只用 `var(--lb-font-*)`（`tests/test_guards.py`「写死的字体栈」会拦）。
- 没有 `title=` / `aria-label=`（Obsidian 会画成浮框，她不要）；图标钮用视觉隐藏文字。
- 不用 `window.alert / confirm / prompt`；提示 `LB.say`，确认 `LB.confirm` 或页内弹层。
- 数字斜体 `LB Digits Inline` 只挂在 Wiki 根元素上（没进共用字体）。
- 宽度三档（宽 ≥1040 / 开着原文格 680–1040 / 手机 <680）用 ResizeObserver 给根加 `is-mid` / `is-narrow`（不用容器查询：会让浮层定位错）。

## 7. 改完怎么验

- **只跑相关测试**（她 10-29 定的，不跑全量）：`node tests/test_wiki_view_1029.cjs`、`node tests/test_wiki_view_1031.cjs`、`node tests/test_assets_syntax.cjs`、`node tests/test_trash_view_c16.cjs`、`node tests/test_l4_contracts.cjs`、`python -m pytest -q -p no:cacheprovider tests/test_guards.py tests/test_personal_wiki_1029.py tests/test_personal_wiki_1031.py tests/test_personal_wiki_search_1031.py`；动了别的共用文件再加对应测试。
- **交 GPT 审**（她 10-29 定的）：Codex 插件，审完逐条核实再修；涉及写盘的改动要求测试「修前红、修后绿」。
- **预览**：在 worktree 里建 `vault\`，`LINK_BRAIN_VAULT=<worktree>/vault python -m link_brain pwiki import …` 导内容；拷 Dataview（要开 DataviewJS）和插件进 `vault/.obsidian/plugins/`，再拷一份真库 `_archive/catalog-data.json`（有它首次启动不会自动同步）；用 `catalog._WIKI_SCRIPT` 写 `_archive/wiki-page.js` 和 `Wiki.md`。Obsidian「打开其他库」开它。原帖不在预览库，点引用开原文要到真库验。
- **部署**（AGENTS.local）：避开 03:30–07:00、确认 XhsFavSync 不在跑 → 变基到最新 main、跑相关测试 → `git merge --ff-only` 进主工作树 main → 先核对真库插件 == 合并前 main 的插件（去掉换行符比），再拷 `obsidian-plugins/link-brain-actions/*` 进 `vault/.obsidian/plugins/link-brain-actions/`（不碰 `data.json`）→ 主工作树 `python -m link_brain catalog` → 她在 Obsidian 里「重新加载应用（不保存）」。

## 8. 还没做 / 以后

- **保存提速**：10-31 `pwiki` 走轻入口（`__main__` 直接调 `personal_wiki.main_fast`，不载整套 cli），一次约 0.25 秒（以前 1.5 秒），而且普通保存不再锁页。还嫌慢再接常驻 worker。
- **AI 一起改**：10-31 已接上「改这一段 / 改整页 / 搭框架」。还没做：从问收藏「加入 Wiki」；AI 改时流式显示。
- **Wiki 进检索**：10-31 问收藏把命中的 Wiki 页（最多 3 页、过门槛）作为「她自己的判断」放进提示词、结果带 `wiki`（问收藏页还没显示它：chat-view.js 另有会话在改）；MCP 有 `pwiki` 工具。没做：收藏一篇都没命中时也用 Wiki；追问（mode=chat）用 Wiki。
- **页头三页统一**、收藏引用编号圈和问收藏来源角标统一、正文数字斜体进共用字体、全站去掉悬浮提示：见 WIKI-UNIFY-LATER.md。
- 目录页（浏览收藏）还没有 Wiki 入口（等页头统一时一起加）。
- 原文格里的「插到当前页」没做（右栏是插件的阅读格，页面插不进按钮）。
