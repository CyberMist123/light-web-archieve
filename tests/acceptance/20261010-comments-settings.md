# 10-09 晚反馈批次验收记录（2026-10-10）：评论补齐 · 设置一页 · 连接 AI · 选本机文件夹

截图在 `LWA_QA_DIR`（本次 = worktree 下 `qa/`，不进仓）。「外壳」= `tests/_obsidian_shell.cjs` 的 settings-modal 宿主里的 Chromium（playwright），不是 Obsidian 实测；
Obsidian 里只能她验的列在文末「待她：一步」。

## 一、评论补齐（入口：后台补跑 `comments --fill-pending --until-done` / 夜跑一步 / 插件「现在补」）

| 项 | 步骤 | 预期 | 实测 |
|---|---|---|---|
| 根因 | 真库只读扫一遍（不碰号） | 说清漏在哪 | 601 篇里 521 篇没有 comment_load（10-08 以前入库），其中 195 篇前 10 楼缺回复、共 5863 条；旧排程只认 comment_load 里的缺口 → 一篇都排不上；新组件入库的 80 篇前 10 楼 0 缺口 |
| 补跑起得来 | 计划任务（按需）拉起后台补跑 | 单实例、篇间 60–180 秒、状态文件每分钟刷新 | 00:05 起跑，候选 197 篇 / 5863 条；前几篇逐篇补齐（缺 1→0 等），状态文件 `running · 已补齐 n/197` |
| 碰号规矩 | 读源码 + 单测 | 开页前只看内存状态；熔断 / 掉登录不开页、等她处理后自动接着；夜跑在跑 / 20 分钟内开始就让路；别的任务在等号先让 | `tests/test_comments_fill_1009.py` 的 worker 三条 + polite 锁两条 |
| 不重下 / 不重识图 | 单测 | 续读写新版本时正文图引用旧文件 | `test_fill_reuses_downloaded_media_and_does_not_redownload` |
| 连着补不上 | 单测 | 3 次没进展才进问题面板，原因照实；补上自动消 | `test_no_progress_three_times_goes_to_problem_panel_then_resolves` |

体验预算：同一篇两次开页 ≥ 45 分钟；篇间歇 60–180 秒（和同步收藏同一个变量 LWA_FETCH_REST）；一篇一次续读读取组件预算 480 秒（插件「立即同步」等号 10 分钟内一定轮得到）。

## 二、设置一页（她 10-09 的裁决，见 docs/SETUP-CONTRACT.md 顶部）

| 项 | 入口 | 预期 | 实测 |
|---|---|---|---|
| 一页四块 | 外壳 settings-modal，亮 / 暗 / 第三方主题 | 状态 · 功能 · 连接 AI · 高级（默认收起），没有分页条和分步向导 | `tests/ui/l4_settings_ui.cjs` 过；截图 `S1009-settings-{light,dark,orange}.png`、`S1009-settings-adv-*.png` |
| 一项不少、不重复 | 假 DOM 全展开 | 第 7 批五个分页的设置项都在（挪地方 / 合并重复按表对上），列出的单例只出现一次 | `tests/test_settings_layout.cjs` 过 |
| 开关即唯一入口 | 假 DOM | 改 setup.selected（依赖联动）并对上 OCR / 语音 / CapsLock / AI 方式 | 同上第 2 节 |
| 一键装好 / 跑完 | 单测 + 假 DOM | `setup run` 事件画成 ✓ / ⟳ / ✗；掉登录给「去扫码 / 验证」 | `tests/test_setup_run_1009.py`、`tests/test_home_ui.cjs` |
| 零配置首次 | 假 DOM | 新库按轻量版自动跑一次；老库不动 | `tests/test_home_ui.cjs` 第 3 节、`tests/test_batch5_delivery_ui.cjs` |
| 轻量版不标 AI | pytest | 卡片不出待补识图 / 概要；开了 AI 待补也不上卡片 | `tests/test_card_problems_1008.py` 两条 |

## 三、连接 AI

| 项 | 入口 | 预期 | 实测 |
|---|---|---|---|
| Claude Code 一键接上 | `connect add claude-code`，**临时 CLAUDE_CONFIG_DIR** 真跑 claude 命令 | 写进用户级 mcpServers.lwa；她真实的 ~/.claude.json 不动 | `LWA_TEST_REAL_CLAUDE=1` 跑 `test_real_claude_cli_writes_only_temp_config` 过；夹具核对真配置 mtime 没变 |
| Claude Desktop | 临时配置文件 | 备份、只动 lwa、可撤销、坏 JSON 不敢改 | `tests/test_connect_1009.py` |
| 网页端一屏 | 假 DOM | 远程服务开关 / 域名 / 连接地址 / 口令 / 几步 / 已连接 | `tests/test_remote_ui.cjs` |

## 四、选本机文件夹

| 项 | 入口 | 预期 | 实测 |
|---|---|---|---|
| 系统对话框弹得出来 | 真机跑 `python -m link_brain pick-folder`，截屏 | 置顶的系统选文件夹对话框 | tkinter 弹出 Windows 新式「选择文件夹」对话框（标题「LWA 测试：选本机文件夹（会自动关掉）」），在最前面；选完回 `{"ok":true,"path":…,"via":"tk"}`（截图在作者本机工作区） |
| 从库内选 | 假 DOM | FuzzySuggestModal 只列收藏库里的文件夹（不列隐藏 / _archive） | `tests/test_remote_ui.cjs` |

## 待她：一步

1. 重载 Obsidian（或在第三方插件里关掉再打开 Link Brain）——设置页变成一页；底部状态栏能看到「⟳ 补评论 · n/197 篇」。
2. 设置页「连接 AI」里勾要连的客户端：claude.ai / ChatGPT 照那几步连一次；Claude Code / Desktop 要不要接由你决定（点「一键接上」随时可「撤销」）。
3. 「再开放一个文件夹 → 选本机文件夹…」点一次，看系统对话框是不是在最前面弹出来。
