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

## 3. 数据（摘要，细节见 FORMAT.md）

- 一页 = `vault/PersonalWiki/<标题>.md`，文件头 `id · title · role(page|topic) · index_tag · order · tags · created · updated`，正文是唯一主副本。Obsidian 里直接改也行（会记成「外部编辑」）。
- 文件夹 = `role: topic` 的页 + 它的 `index_tag`；页面带哪个文件夹的标签就在哪个文件夹里（可多个）。文件夹里的顺序 = 文件夹页的 `order`（目录里拖出来的）。编号按建立先后。
- 收藏引用 `[标题](lwa:<item_id>)`，`item_id` 是目录数据里的完整 id（带来源前缀，如 `xhs-…`）；页面也认不带前缀的短 id（唯一匹配时）。
- 历史 `.history/<id>/`（整页快照 + `log.json`），删除 `.trash/`，都不进索引。
- `hash` = 文件全文（CRLF→LF）SHA-1 前 16 位；页面和后端同一算法，保存时带 `base_hash` 防覆盖。

## 4. 页面

- **页头**：刻线大标题 · 「…」 · 历史钮；三页切换胶囊 + 篇数行。
- **浮动目录**（左）：工具行（回首页 · 搜标题 · 全部收起 / 展开 · 新页面 · 收起目录）；MAP 关系图（展开 / 固定，有「全局图」）；编号文件夹 → 页面（可拖动排序）→ 当前页 H1–H4 小标题；底部标签。
- **首页**：OVERVIEW 四个数字（全部页面 · 近 7 天改过 · 引用的收藏 · 文件夹）· INDEX 文件夹物件（未归类 · 新文件夹）· MAP 全局关系图。
- **文件夹页**：大编号 + 名字 + 自由文档（可放 ` ```pages ` 自动列表）+ 没写进正文的页列在 MORE。
- **普通页**：标题即输入框 · 元信息（日期 · 字数 · 引用数 · 标签）· 正文。
- **标签页**：同标签的页 + 收藏里带这个标签的（只当材料，不自动进正文）。
- **历史**：页内右侧栏：版本列表、和现在的逐行差异、恢复、保存版本。
- **编辑**：点一段 → 编辑框 + 层级工具条（正文 / H1–H4 / 列表 / 待办 / AI 改写〔灰〕），Ctrl+Alt+0–4，Esc 收起即保存，Ctrl+Enter 下一段；`@` 搜收藏插入 `[标题](lwa:id) — `；「…」里有整页 Markdown、重新读入、删除这一页、新页面、新文件夹。
- **右侧原文**：点收藏引用 = 插件 `openArchiveSource(item.note, 页面容器)`，和问收藏同一个原文窗格。
- **只读**：没插件 / 手机 → 能看、能跳、能开原文，不能改。

## 5. 写盘模型（改这里要特别小心）

GPT（Codex）前后审了 6 轮，几轮都在这一层找到「丢字 / 旧内容盖新内容」的竞态，最后改成下面的结构（`wiki-view.js` 写盘一节开头有 ①–⑥ 注释）。**新加任何会改页面的功能，都必须走这套，不许开旁路**：

1. 每页一条串行队列：保存、恢复、覆盖、记版本、删除都排进去。
2. 队列里有东西时这一页只读（标题框、待办、整页 Markdown 框、拖动、标签都不收）；点某段会等队列空了再开，期间正文被换过（冲突、恢复）就不开。
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

- **只跑相关测试**（她 10-29 定的，不跑全量）：`node tests/test_wiki_view_1029.cjs`、`node tests/test_assets_syntax.cjs`、`node tests/test_trash_view_c16.cjs`、`node tests/test_l4_contracts.cjs`、`python -m pytest -q -p no:cacheprovider tests/test_guards.py tests/test_personal_wiki_1029.py`；动了别的共用文件再加对应测试。
- **交 GPT 审**（她 10-29 定的）：Codex 插件，审完逐条核实再修；涉及写盘的改动要求测试「修前红、修后绿」。
- **预览**：在 worktree 里建 `vault\`，`LINK_BRAIN_VAULT=<worktree>/vault python -m link_brain pwiki import …` 导内容；拷 Dataview（要开 DataviewJS）和插件进 `vault/.obsidian/plugins/`，再拷一份真库 `_archive/catalog-data.json`（有它首次启动不会自动同步）；用 `catalog._WIKI_SCRIPT` 写 `_archive/wiki-page.js` 和 `Wiki.md`。Obsidian「打开其他库」开它。原帖不在预览库，点引用开原文要到真库验。
- **部署**（AGENTS.local）：避开 03:30–07:00、确认 XhsFavSync 不在跑 → 变基到最新 main、跑相关测试 → `git merge --ff-only` 进主工作树 main → 先核对真库插件 == 合并前 main 的插件（去掉换行符比），再拷 `obsidian-plugins/link-brain-actions/*` 进 `vault/.obsidian/plugins/link-brain-actions/`（不碰 `data.json`）→ 主工作树 `python -m link_brain catalog` → 她在 Obsidian 里「重新加载应用（不保存）」。

## 8. 还没做 / 以后

- **保存提速**：现在每次保存起一次 Python（约 0.3–1 秒，这期间这一页只读）。卡的话把 `pwiki` 操作接进常驻 worker（`serve.py`）。
- **AI 一起改**：搭框架、修订这一节（带生成时的正文 hash，期间手改过就先重新比较）、从问收藏「加入 Wiki」。界面上已有灰着的入口。
- **Wiki 进检索**：问收藏 / MCP 先读到她的判断和偏好（`wiki:` 来源，读 `_archive/wiki-index.json`）。
- **页头三页统一**、收藏引用编号圈和问收藏来源角标统一、正文数字斜体进共用字体、全站去掉悬浮提示：见 WIKI-UNIFY-LATER.md。
- 目录页（浏览收藏）还没有 Wiki 入口（等页头统一时一起加）。
- 原文格里的「插到当前页」没做（右栏是插件的阅读格，页面插不进按钮）。
