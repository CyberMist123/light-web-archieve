# 1023 ARCH-AUDIT 第 0、1 批验收记录（2026-10-23）

云端会话，Linux + Python 3.13 venv，不是 Obsidian 实测。Obsidian 里只能她验的列在文末「待她：一步」。

## 一、第 0 批：唯一来源守卫

| 项 | 入口 | 预期 | 实测 |
|---|---|---|---|
| 守卫 | `tests/test_single_source.py` | 11 类数据：现存重复全在 known 白名单里 → 过；新加一处重复 → 红 | 11 过；临时加一个 `PRICES = {}` 文件 → 「价格表」红，删掉后恢复 |
| 对照表 | `docs/TEST-MAP.md` | 模块 → 测试、行为缺口按批次列出 | 已写 |

## 二、第 1 批：目录跟上库、不刷屏、篇数一个口径

| 项 | 入口 | 预期 | 实测 |
|---|---|---|---|
| 同步中断 | `favorites.run` 中途抛错（pytest） | 已入库的帖进目录、待重建记号清掉 | `test_sync_run_refreshes_catalog_even_when_it_fails` 过 |
| 单篇导入 | `catch.run`（pytest） | 直接跟上；插件批量导入（`LINK_BRAIN_DEFER_CATALOG`）等最后统一建 | `test_catch_refreshes_unless_deferred` 过 |
| 重建途中又有改动 | pytest | 记号留着，下次再建 | 过 |
| 不刷屏 | 同样的输入连着建两次（pytest） | 页面 md / 脚本 / catalog-data / 检索索引 / 回收站页一个都不改 mtime | `test_rebuild_without_changes_touches_no_file` 过（`index-data.json` 另有短路逻辑，未纳入，见 ARCH-AUDIT 第 10 节） |
| 篇数 | pytest | `counts.all = mine + 其它来源`；目录页「N 篇 · 全部 M」、问收藏页「全部 M 篇」 | `test_counts_single_source` 过 |
| `catalog --if-dirty` | pytest | 没有记号时秒回、不写任何文件 | 过 |

## 三、测试汇总（和 main 8d3a1a8 同一环境对比）

- `python -m pytest -q`：main 上已有 40 条失败 / 报错（`test_remote_mcp` 等，依赖版本问题，和本改动无关）；本分支同样这 40 条，**没有新增**。
- `node tests/run-node.cjs`：逐个文件的过 / 挂 / 跳过和 main **完全一致**（挂的是缺 msedge 等本机环境问题）。

体验预算：重建时内容没变不再写文件，目录页不重画；有改动时和以前一样。

## 待她：一步

1. 更新插件后打开 Obsidian，等评论补齐在后台跑：目录页还闪不闪。
2. 目录页表头是不是「1403 篇 · 全部 1437」这样，问收藏页是不是「全部 1437 篇」。
3. 点一次「立即同步收藏」（或从 TG 发一条链接）：完了不用手动刷新，「今日新增」能筛到新帖。
