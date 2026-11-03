# 安装与首次启动流程：架构审查（1103，只分析，未改代码）

## 先回答那一句

**如果已经有 `setup run`，为什么还要 `installer-ui.run()` 自己再装一遍组件？——没有站得住的理由。**
`setup run` 的第一步（`pipeline.py:194-219`）本来就按 `data.json` 的 `setup.selected` 逐项 `components.check` → `components.install`，
每项的下载进度都以 `{type:'progress', stage:'install', component, phase, done, total}` 发给插件（`home-ui.js applyRunEvent` → 懒人安装卡片的进度条）。
PR 91 另写一遍，是我想让弹窗自己画组件进度、并在同步开始前让扫码按钮亮起来——这两件用现有 run 的事件就能做到。
结果是：同一批组件两套安装路径、两套选择规则（弹窗写死 `reader`/`ocr`，run 读 `setup.selected`）、两套状态，装完再进 run 又检查一遍。

## 一、当前真实架构

### 原来的懒人安装（PR 91 之前，main）
| 环节 | 在哪 | 怎么做 |
|---|---|---|
| 入口 | `onboarding-ui.js startup()`（窗口就绪 1.5 s 后） | 没后端 → `homeUI.installBackend`（静默）；新库 → `homeUI.firstRun()` → `runAll()` |
| 装后端（Python 还不存在） | `backend-install.js ensureBackend` | 纯 JS：uv → Python 3.12 → venv → wheel + 带哈希 lock → 自检。**这是唯一必须在 JS 里做的部分** |
| 组件选择 | `data.json setup.selected`（没选过 = 轻量版 core/reader/ocr） | 设置④的开关 `featureToggle`/`setFeature` 写它；后端 `pipeline.selected()` 读同一个 |
| 装组件 / 登录 / 同步 / 补 AI / 目录 / 索引 / 评论 | `link_brain/setup/pipeline.py run()` | 一个后台进程依次跑 7 步，每步发进度，落盘 `_archive/setup-run.json` |
| 进度显示 | `home-ui.js renderRun`（设置页「懒人安装」卡片） | 后端安装 5 步 + run 7 步 + 组件下载进度条，都画在这一张卡片 |
| 断点恢复 | `home-ui.js resumeRun/watchResumed` | 读 `setup-run.json` + pid 存活 → 续画或「上次没跑完，停在 X」 |
| 互斥 | `main.src.js spawnPy({exclusive})` → `plugin.running` | run 期间占用整把锁（最长 6 小时） |

结论：**原来的流程已经完整**，从后端到首次同步一条链。缺的是：首次没把用户带到这张卡片、选项不在这张卡片上、几处显示过时 / 被锁挡住（见第三节）。

### PR 91 新增了什么
| 新增 | 判断 |
|---|---|
| `components.py _ensure_vc_runtime` + `link_brain/__init__.py` 加 DLL 目录 + check 里报缺运行库 | **必要**。干净 Win11 实测 OCR 导入失败的真因，虚拟机验证过修好 |
| Release lock 带 `ocr/bilibili/docs`，插件装 `link-brain[ocr,bilibili,docs]` | **必要**（作者定的默认装全）。v0.2.1 已发、本机 `--require-hashes` 装过 |
| `uvInstallMeter` / `pythonLineText`：uv 输出 → 真实进度和人话 | **有用**，属于 `ensureBackend` 自己的进度，不重复 |
| `backendMissingText()` 装后端期间改说「正在安装」 | **小而有用**，只读已有的 `homeState.backendRun` |
| `installer-ui.js`：弹窗 + 自己的安装控制（调 installBackend 后再自己跑 `setup install reader/ocr`）+ 自己的进度模型（含按时间模拟）+ 自己的 OCR 开关 + 自己的扫码（成功判断写错）| **重复**原有能力，且引入新的不一致。应撤回 |
| `onboarding startup` 改成 `openAndRun()` 等用户点「开始同步」；`renderRun` / `renderSetupHints` 的按钮改为开弹窗 | 随弹窗一起撤回 |

## 二、后端 plan / install / run 的职责

- `setup plan`：功能清单 + 状态 + 预设（给界面）。`setup check`：逐项只读检查。`setup install --component`：装一项。`setup run`：整条流程。**分工本身是清楚的。**
- 三处不清的地方：
  1. **check 把「开没开」算进「装没装」**：OCR 设置关着 → `partial`「OCR 在设置里关着」（`components.py:173`）；CapsLock 关着同理。前端再把 partial 说成「没装好」。
  2. **run 不发每个组件的结果**：只在整步结束时发一句 `全部就绪`，插件拿不到「OCR 现在就绪了」，只能等整轮跑完才重读 plan（`home-ui.js:273`）。
  3. **run 的步骤顺序**：目录在同步之后；同步按防风控节奏可达 170 分钟，期间没有目录页。

## 三、目录页、B 站页为什么被挡（代码核对）

| 现象 | 原因 |
|---|---|
| 识图「认字的本机组件还没装好」 | `settings-v6.js:924` 读缓存的 `homeState.plan`；plan 只在 run 整轮结束 / 装完后端时重读，而且这几行的 repaint 不在 home 的 `painters` 里，plan 刷新了也不重画 |
| 「还没有这个页面：点…刷新目录」 | 目录在 sync 结束时才生成（`favorites.py` finally 里 `ensure_fresh`，或 run 的 catalog 步）；「刷新目录」走 `run()` 的互斥锁（`main.src.js:2528`），run 占着就拒绝 |
| B 站「预估 / 立即同步」灰掉、不说原因 | `settings-v6.js:641` `disabled = !!plugin.running`。B 站和小红书无关，Python 侧也没有共用的账号锁，这把锁不需要 |
| 「在底部状态栏停止 / 看进度」 | 状态栏进度默认隐藏（`devSyncLog:false`，`main.src.js:300/2856`） |
| 重启后按钮全亮、能起第二个 run | `plugin.running` 只在内存；`runAll` 不看已恢复的 `homeState.run` |

## 四、架构裁决

**结论：撤回 PR 91 的安装流程设计（弹窗及其控制流），保留它的后端能力。不重构整个 LWA，不引入新的状态中心 / 事件总线 / 状态机。**

### A. 保留（原有）
- 设置页「懒人安装」卡片（`home-ui.js renderRun`）作为**唯一的**安装与首次运行界面。
- `runAll` = `installBackend`（仅后端缺失时）→ `setup run`：唯一执行者。
- `setup.selected` 作为唯一的组件选择；设置④的 `featureToggle` / `setFeature` 作为唯一写入口。
- `setup-run.json` 断点恢复；`backend-install.js ensureBackend`。

### B. 删除 / 撤回（PR 91）
- `installer-ui.js` 整个文件，`main.src.js` 里的 `installerUI` 注册，`onboarding-ui.js` 的 `openAndRun` 分支和「打开安装窗口」提示，`home-ui.js renderRun` 里开弹窗的按钮，`installBackend` 的 `onProgress` 参数（只给弹窗用）。
- `tests/test_installer_1103.cjs`；`test_batch5_delivery_ui.cjs` / `test_home_ui.cjs` 里为弹窗改的部分退回原样。
- 保留：VC++ 修复与其测试、lock extras、`uvInstallMeter` / `pythonLineText`、`BACKEND_INSTALLING_TEXT`、v0.2.1 发布与校验值、`test_page_host` 的换行修正。

### C. 需要重新划分的职责（都是小改，在原模块里）
1. **check 只答「装没装」**：去掉 OCR / CapsLock 里「设置关着 = partial」，开没开由设置决定、界面自己判断显示不显示。
2. **run 每装完一项发一条结果**（在 `pipeline.py:205` 那一行之后加一个事件）；插件收到就 `loadPlan(true)`。
3. **设置④那几行「现在」挂进 home 的 `painters`**（plan 一变就重画）；页顶提示也走 painters，不再画一次就不动。
4. **锁收窄**：run 只挡小红书那几样（同步 / 补评论 / 登录，Python 已有 `account_session`）；B 站、刷新目录不再看 `plugin.running`。
5. **目录先有**：run 在 login 之后、sync 之前先跑一次 `catalog`（空库 = 空目录页，显示「正在同步」）；同步过程中的刷新复用 `ensure_fresh`。
6. **状态栏默认显示一行进度**（关掉 `devSyncLog` 这个门槛，只对 run / 同步）。
7. 扫码成功判断统一用账号行的 `status`（不用 `ok`），登录后清 `accountCache`。

### D. 用户可见的流程
- **一条安装流程**：首次启用 → 自动打开设置页并定位「懒人安装」卡片 + 一条通知「点这里看进度」。卡片上面是选项（复用现有行：收藏位置 `renderFolder`、认图片里的字 / 视频说话转文字（约 2 GB）`featureToggle`、B 站收藏夹「选同步哪些收藏夹…」），下面是现有进度。
  执行者：`ensureBackend`（后端缺失时，自动开始）→ `setup run`。
- **各平台各自的动作**（任何时候、互不阻断）：小红书扫码、B 站扫码、B 站同步、刷新目录、填 AI key。
- 待作者定：后端下载（几分钟、几百 MB）自动开始；`setup run` 是装完后端立刻自动跑，还是等用户在卡片上点一次「开始」（这样选项一定先于装组件生效，比如 2 GB 语音模型）。

### E. 如何避免重复
- 重复安装：组件只由 `setup run` 的 install 步装；没有第二条路径。
- 重复选择：只有 `setup.selected`。
- 重复状态：运行状态只有 `homeState.run`（+ 文件恢复）和 `homeState.backendRun`（run 的前置一步，画在同一张卡片）；组件状态只有 plan，由 run 的逐项结果触发刷新。
- 重复前置检查：run 的 install 步已经 check 过，插件端不再另查。

## 五、改动规模估计
撤回弹窗约 -400 行；C 里 7 项各是几行到几十行的局部改动，集中在 `pipeline.py`、`components.py`、`home-ui.js`、`settings-v6.js`、`main.src.js`。
验收：在虚拟机从干净快照走一遍，逐项截图核对「同一件事各处说法一致、无关功能不被挡」，再交作者。
