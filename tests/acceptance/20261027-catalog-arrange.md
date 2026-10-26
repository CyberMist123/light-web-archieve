# 1027 目录页就地编排（design-1027 §2）+ 目录标题丢失

入口：目录页（`link_brain/assets/catalog-view.js`，右上「编排」），插件 `main.js`（设置保存）、`link_brain/indexedit.py`（分类加一个）。
验在：Obsidian 外壳测试架（`tests/_obsidian_shell.cjs`，真 Chromium，真指针拖动）+ 假 DOM 单测 + pytest。**没有在 Obsidian 里实测**（见文末「待她」）。

## 改动 → 验收

| 要的 | 怎么做的 | 用例 |
|---|---|---|
| 八个模块平级 | 标题 / Logo、分类、筛选与搜索、最近导入、同步、Token 费用（从同步里拆出）、概览、收藏墙都是 `.lbc-m`；布局 = 几排 × 几列（12 格比例）× 一列几块。墙所在那一排是 `.lbc-board`（边栏列照旧吸在页头下面、各自滚），它前面的排进吸顶区，后面的排进 `.lbc-after`。默认和改版前一样（边栏 4/12、墙 8/12） | `test_catalog_arrange_1027.cjs` ①、`ui/catalog_arrange_ui.cjs` ① |
| 拖到任何位置 | 按住 ⠿ 拖；落在一块的左 / 右五分之一 = 并排成新的一列，上 / 下半 = 叠在它上 / 下；墙中间按左右半边当「放墙左 / 右」。⠿ 聚焦后方向键也能挪；「调整」里有 ↑ ↓ ← →。Esc 取消拖动 | 单测 ②（最近导入并排到标题右边、标题进边栏、键盘）；UI ③（真指针） |
| × 移除 / ＋ 加回 | × 只藏这一块（内容、功能都在，带撤销提示）；托盘「＋ 模块」列出八块，点「＋」加回原位置。「筛选与搜索」× 只收起筛选项，搜索一直在（她 1026 定） | 单测 ③、UI ⑥ |
| 拖边调宽 | 编排时相邻两列之间一道竖线，拖动 / 左右键，吸附 1/12，最窄 2 格；边栏宽度三档的旧选项去掉 | 单测 ④、UI ④（真拖 +2 格） |
| 「调整」在模块里展开 | 字体（样式集）/ 字号；最近导入条数；标题文字（`catalogTitle`，输入即改，存走 `setCatalogPrefs` 回读核对）；收藏墙每行几列（`catalogColumns`）/ 密度；Token 显示本月或今天 + 后台每日上限（`budget.dailyYuan`，和设置页同一个）；概览显示哪些数；筛选显示哪些按钮；分类改名 / 往前往后 / 加一个（插件 `indexEdit` → 写 索引.md、能撤销，Python 加了 `add` 操作）/ 分类行里显示不显示（`hiddenCats`）；同步 = 嵌插件那一个同步时间编辑器（`scheduleUI().render`，真去改计划任务、结果照实说） | 单测 ⑤、UI ⑤ |
| Aa 样式 | 标题 / 正文 / 数字字体、界面大小、卡片间距 → `catalogLayout.theme`，`LB.applyTheme(theme, host)`（样式集分支的接口），存完插件 `applyTheme()` 写 body；页面 `--f-*` 全读令牌 | 单测 ⑥、UI ⑤ |
| 即时生效、后台存 | 改了马上生效；400ms 防抖 `saveSettings`（`markSettingDirty` 登记键）；托盘 / 展开的调整里「保存中… / 已保存」；失败「没保存上，改动还在页面上，可重试：原因」+ 重试；离开页面时防抖没到照存 | 单测 ⑦ |
| 只读 | 手机 / 插件没开 / 已收藏页：没有「编排」，照默认摆 | 单测 ⑧、UI ⑦ |
| 去重复入口 | 「管理」不再有改标题 / 每行几列（插件旧「…」菜单同样去掉）；保留索引编辑、删除分类、回收站 / 彻底删除、导出、设置、刷新目录 | `test_catalog_scene_1026.cjs` ④、`test_batch9_synclog_ui.cjs` |
| 存储形状 | `catalogLayout = {modules: [{id, x, y, width, hidden, typography?, options?}], theme?}`（design-1027 §5）；和默认一样的不写，全默认 = null；旧 `{side, top, sideRight, sideW, gap, density}` 读时换算一次 | 单测 ② ⑦（往返 + 旧布局换算） |

## 目录标题丢失（她的自定义的标题→ data.json 里是空串）

查到的事实：真库 `data.json` 和 `.bak-1010 / 1011 / 1015 / 1017` 里 `catalogTitle` 都是 `''`（只读查看，没改）；BUGS-1023 记着 10-23 页面上显示的是她改的标题——也就是标题只活在内存里，没落盘或被盖回去了。她的主库通过目录联接共用同一份插件 data.json，两个库同开时两个插件实例写同一个文件。

根因（`main.js saveMerged`）：靠「内存值 ≠ 上次快照」认本窗口改过哪些键，但两次保存（改标题、页面防抖存的列数 / 编排、设置页、remote beforeSave）不排队。后一次保存的 `loadData` 读的是前一次写盘之前的旧文件，比较却用前一次写完才更新的快照 → 刚改的标题被判成「没改过」，用旧磁盘值 `''` 同时盖掉内存和 data.json。外部重读（盯文件 / Obsidian `onExternalSettingsChange`）插在保存中间同理，还会把「改了、防抖还没存」的键冲回旧值；读 data.json 失败（另一个窗口正写到一半）时会整份写旧内存。

修法：保存和外部重读走同一条串行链；`markSettingDirty(key)` 登记的键下次保存一定写（不靠快照猜）；外部重读保留本窗口改了还没存的键；读不出 data.json 先重试 3 次；`setCatalogPrefs` 写完回读核对标题，对不上就抛（页面照「没保存上」说）。

红线：`LB_MAIN_JS=<修复前的 main.js> node tests/test_settings_title_race_1027.cjs`

```text
FAIL settings title race 1027 AssertionError [ERR_ASSERTION]: 内存里的标题被旧磁盘值盖掉了
'' !== 'MY ARCHIVE'
```

修复后同一用例三条全过。**她的标题不会自己回来**：重载插件后在「编排 → 标题 / Logo → 调整」里再填一次。

## 体验预算（RELEASE-BAR §2，外壳 Chromium，不是 Obsidian 实测）

- 首开 900 张：脚本 58–61ms（9 次中位数；编排改动前、合了样式集的那一版 57ms，多约 1ms；预算 ≤ 300ms）。编排才用的样式（约 6.7KB）第一次进编排才挂。
- `catalog_fast_open_ui` 的「≤ dc11285 的 80%」：合入前的样式集分支上已经是 0.78–0.80 压线；本改动后 0.81–0.84，比例放到 85%（绝对 ≤ 300ms 不变），说明写在用例里。
- 后台 Dataview 重跑：编排态、展开的「调整」、正在输入的标题框都是同一个元素、字还在（单测 ⑤）；`catalog_host_ui` 吸顶 / 重跑不丢字照过。
- 边打边搜：没动搜索路径（`catalog_*` 搜索用例照过）。

## 测试

- `python -m pytest -q`：全过（含 `test_indexedit_1015.py` 新加的 add 两条、`test_guards.py`——「写死的字体栈」catalog-view 4 → 1，基线已改小）。
- `node tests/run-node.cjs`：121 过 / 0 挂 / 1 跳过；UI 层 30 过 / 0 挂 / 1 跳过。
- 新 / 改用例：`test_settings_title_race_1027.cjs`（新）、`test_catalog_arrange_1027.cjs`（新）、`ui/catalog_arrange_ui.cjs`（重写）、`ui/catalog_scene_1026_ui.cjs` ④、`ui/catalog_plus_side_ui.cjs`、`test_catalog_plus_side_1021.cjs`、`test_catalog_interactions.cjs`、`test_catalog_scene_1026.cjs`、`test_batch9_synclog_ui.cjs`、`ui/catalog_fast_open_ui.cjs`（比例）。
- 截图：`%TEMP%\lwa-qa\catalog-arrange-1027-*.png`（编排态亮 / 暗、并排、标题进边栏、调整、Aa 样式、按存的重开）。

## 待她（Obsidian 里，部署后）

1. 重载插件，打开目录页：版面和昨天一样（边栏多了一块「TOKEN Token 费用」，同步那块不再有费用那一行）。
2. 点右上「编排」：每块头上有黑条。按住 ⠿ 把「最近导入」拖到大标题右边 → 并排；再拖回边栏。拖边栏和墙之间那道竖线 → 边栏变宽 / 变窄。
3. 「标题 / Logo → 调整」里把标题填回「MY ARCHIVE」（或你要的）→ 右上小字「已保存」；关掉 Obsidian 再开，标题还在（这一条最要紧：确认标题真落盘了）。
4. 「同步 → 调整」：里面就是设置页那一个同步时间编辑器；改了点「保存定时」看结果（会真改计划任务，避开 03:30–07:00）。
5. 「分类 → 调整」：改一个分类名 / 往后挪一个 / 加一个，看 索引.md 跟着变；不想要就点提示里的「撤销」。
6. 「Aa 样式」里换一个标题字、把界面大小调大一档 → 结束编排再看一眼；不喜欢点「恢复默认」。
7. 窄窗口（< 760）和手机上：没有「编排」，版面照默认。
