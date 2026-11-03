# 安装与首次启动：改动计划 v2（1103，吸收 Codex 审查，未写代码）

依据：作者 1103 的决定 + `docs/ARCH-REVIEW-INSTALL-1103.md` + Codex 只读审查（14 条必须改、4 条建议改）。
原则不变：懒人安装为主、局部修正；`setup run` 执行常规组件和首次流程；不加状态中心 / 事件总线 / 状态机。

## 作者已定
- 全自动，没有「开始」按钮。首次启用：自动打开「懒人安装」卡片 → 装后端 → `setup run` 一路跑；边跑边选，没跑到的步骤按到它时最新的设置。
- 收藏位置一开始就定好（不填 = 默认位置），本轮钉死；改了**下一轮生效**，卡片显示本轮实际位置。
- 认字默认装；2 GB 视频说话转文字不进自动安装，勾上才在后台单独下载，取消勾选不删模型。
- 小红书、B 站同步可以同时跑；目录先有。

> Codex 必须改第 1 条（首次配置要有明确完成时点）：按作者决定**不加确认点**，用「默认值 + 每步现读」代替。唯一在开头钉死的是收藏位置（作者定：不填就默认），其余选项在用到它的那一步才读。

## 0. 设置读取时机（按 Codex 第 3 条重写）
| 类别 | 内容 | 依据 | 处理 |
|---|---|---|---|
| **run 快照（继承环境）** | 收藏位置 `LINK_BRAIN_VAULT`、Obsidian 配置目录、环境变量里的 API key、key pool、CapsWriter 路径、运行节奏等 | `main.src.js:1269` 起进程时整份环境；`pipeline.py:103` 子进程继承；`load()` 不刷新进程环境 | 收藏位置：本轮钉死，卡片显示本轮位置（写进 `setup-run.json`）；其余：本轮内不变，文档里写明，不改 |
| **run 快照（代码）** | `setup.selected` | `pipeline.py:161` | **改**：每步开始重读（B1） |
| 步骤快照 | 每天上限、每轮上限 | `favorites.py:850`、`:609` | 不改（同步步骤开始时读） |
| 每篇读取 | 评论楼数；主识图配置（一篇的图片循环前读一次） | `adapter.py:1109`；`vision.py:309` | 不改 |
| 每次调用 | 认字档位 / 模型目录 | `vision.py:132` | 不改 |

## 1. 后端（Python）
| # | 改什么 | 位置 |
|---|---|---|
| B1 | 每步开始重读 `selected()` | `pipeline.py:161,196,272,278` |
| B2 | install 步排除 `asr` / `capslock`（语音组件独立安装，文档改称「常规组件由 run 装，语音组件单独装」） | `pipeline.py:196` |
| B3 | 每装完一项发结果事件 `{type:'progress', stage:'install', component, state, status}`；整个 install 步结束时也发一条，插件据此清掉「正在装 X」 | `pipeline.py:205` 后、`:219` |
| B4 | **目录先有**：新阶段 `catalog_first`，放在 install **之前**（不依赖登录、不等组件），空库也出空目录页 | `pipeline.py` STAGES 与 `run()` 开头 |
| B4b | **边同步边填**：同步期间定时消费 dirty（每存 N 篇或每隔几分钟调一次 `ensure_fresh`），不只在收尾刷新 | `favorites.py:1051` 附近的循环；`catalog.py ensure_fresh` |
| B4c | 修 dirty 标记无锁读改写：`mark_dirty` 与 `:841` 的「按序号判断后删除」放进同一把小文件锁 | `catalog.py:798,841` |
| B5 | check 只答「装没装」：去掉「设置关着 = partial」 | `components.py:173`（OCR）、`:232`（CapsLock） |
| B6 | **登录不算整轮失败**：没登录 → login 记 `waiting`（「扫码后自动同步」），sync / comments 记 skipped；最终结果区分「组件已装好」和「小红书待登录」，不报失败 | `pipeline.py:224-234`、result 汇总 |
| B7 | 语音安装结束**不覆盖用户选择**：装完只在用户当时仍勾着 ASR 时才写 `asrAI.mode`；`apply_settings_patch` 写盘前现读、只合并补丁里的键（已是如此，核实后补测试） | `capswriter.py:419`、`common.py:127` |
| B8 | 并发前核实：index.db 连接的 `busy_timeout`；`catalog.py:669` 迁移笔记块与 `render.py:1712` 写笔记的冲突窗口。核实有问题再加最小的锁，没问题就写进文档 | `index.py:86`、`catalog.py:669`、`render.py:1712` |
| B9 | （保留 PR 91）VC++ 运行库补装、lock 带 extras | 已在分支 |

## 2. 插件
| # | 改什么 | 位置 |
|---|---|---|
| U1 | **撤回安装弹窗**：删 `installer-ui.js`、`main.src.js` 的 `installerUI` 注册、`onboarding startup` 的 `openAndRun`、`renderSetupHints` 开弹窗分支、`renderRun` 开弹窗按钮、`home.installBackend` 的 `onProgress` 转发、`styles.css` 弹窗样式。`test_installer_1103.cjs` **拆开**：后端进度 / 日志翻译部分留下（移到 backend-install 的测试），弹窗部分删；batch5 / home-ui 测试退回 | `backend-install.js` 自己的 `onProgress` 保留 |
| U2 | 首次启用：**先等 `resumeRun()` 判定完**，没有在跑的 run 才启动；自动打开设置页定位「懒人安装」卡片 + 通知「点这里看进度」；后端 → run 一路自动 | `onboarding-ui.js startup()`、`home-ui.js firstRun():362-364`、`openSetupPage` |
| U3 | 卡片上方**固定配置区**（不放进每次重画都 `empty()` 的进度区）。选项：收藏位置（本轮显示实际位置，改了下一轮生效）、认图片里的字、视频说话转文字、评论读几楼、B 站画质、B 站超过多长先不下（`settings-v6.js:587`）、「选同步哪些收藏夹」（B 站登录后才出现）。**没后端 / 没 plan 时也能保存**：直接写 `setup.selected` / 对应设置，不走依赖 plan 的 `featureToggle` | `home-ui.js renderRun:507` 上方；`featureToggle:605` 加无 plan 分支或另写一个只存设置的小函数 |
| U4 | 刷新及时：收到 B3 结果 → 清 `run.install` → `loadPlan(true)`（强制刷新不复用进行中的旧查询）→ **完成后**广播重画；设置④「现在」几行、页顶提示挂进 `painters`；usage 60 秒缓存在组件 / AI 变化时失效 | `home-ui.js:137,194,562`；`settings-v6.js:127,921-1000`；`onboarding-ui.js renderSetupHints` |
| U5 | 视频说话转文字：开关**保存成功后**（不是 `finally` 里）触发后台 `setup install --component asr`，不占小红书锁；进度在卡片上 | `home-ui.js:623` 附近 |
| U6 | **锁收窄 = 最小拆两个任务句柄**：小红书一个（`running/runningChild`，现有）、B 站一个（新增 `biliRunning/biliChild`）；B 站按钮、进度监听、停止按钮改看自己的句柄；目录刷新（`refreshCatalog():2904` 和其他重建入口、缺页提示的按钮）不占插件锁，靠 Python `catalog-build` 锁 | `settings-v6.js:381,645,666`；`main.src.js:2281,2528,2894,2904` |
| U7 | 状态栏默认显示：读 `plugin.running`、`homeState.backendRun`、恢复中的 run、B 站句柄；去掉 `devSyncLog` 门槛（只对这些任务） | `main.src.js:2848-2867`、默认 :300 |
| U8 | 同步进度统一说法：卡片 sync 行读 `sync-status.json` 篇数（复用 `syncProgressView`），并让该文件变化触发卡片重画 | `home-ui.js:553-558`、文件监听 |
| U9 | 登录契约：成功 = `state === 'ready'`（`busy` 不算）；登录后更新 / 失效 `accountCache`；**登录只在小红书账号真正被占用时受限**，不再问「停止装好并跑完？」；登录成功且 run 跳过了同步 → 走现有 `sync.autoAfterLogin` 自动同步 | `main.src.js:1975-1982,1732,1954`；`accounts.py:1219` |
| U10 | 重启后：恢复中的 run 进入状态栏；其他小红书同步入口也先看恢复中的 run | `home-ui.js:227,284`；`main.src.js` 同步入口 |
| U11 | 收藏位置下一轮生效：`setup-run.json` 记本轮 vault；恢复读取按本轮 vault，不按插件当前根 | `onboarding-ui.js:45`、`home-ui.js:280`、`pipeline.py` state |
| U12 | 后端安装进度**不再算假百分比**：保留日志翻译（「正在下载 onnxruntime（12 MB）」）；有字节总量（下载 uv / wheel）才显示百分比，其余显示不确定进度条 | `backend-install.js uvInstallMeter:213` |

## 3. 不做的 / 剩余项（不宣称已解决）
不加状态中心；不改夜跑；不动目录页内容。以下矛盾本轮**不覆盖**，留作下一批：账号「刚刚确认」按绘制时点、AI 能不能用的四套判断、问题数四处口径。

## 4. 验收
- 测试：每步重读选择；install 结果事件 → 清进度 + 刷新 + 重画；登录未完成不算失败；语音装完不覆盖关闭；B 站与 run 并行时进度 / 停止对象正确；目录先出、同步中填充；重启恢复不起第二个 run；状态栏有后端安装进度。
- 并发：在虚拟机里同时跑小红书同步 + B 站同步 + 刷新目录，看 index.db 锁等待和目录 dirty 是否丢。
- 虚拟机从「干净系统」快照走一遍，截图：卡片、设置④、目录页、B 站页、状态栏；核对同一件事各处一致、无关功能不被挡。截图和清单交作者。
