# 验收：第二波 PR④ RAW 暂存发布（1025）

入口：无新入口、无新故障码。用户可见的变化只有「检查环境」里多一行「RAW 版本」（可选项）。

## 步骤 / 预期 / 实测

| 步骤 | 预期 | 实测 |
|---|---|---|
| `pytest tests/test_raw_staging.py` | 全绿；`test_backfill_crash_mid_download_leaves_no_version`、`test_half_version_is_not_counted_but_its_number_is_never_reused` 在修前（旧 `existing_versions` / 旧 backfill）是红的 | 修前红 → 修后绿 |
| `pytest tests/test_xiaohongshu.py::test_raw_version_is_immutable tests/test_videos.py tests/test_remove.py tests/test_tomb_p0_1024.py tests/test_tomb_p0fix.py tests/test_doctor_dataview.py` | 全绿（`ensure_raw_dir` 老路径不变） | 绿 |
| 全量 pytest（TZ=Australia/Sydney）+ node 与 main 对比 | 无新增失败 | 见 PR 描述 |
| 真库 `python -m link_brain doctor`（或插件「检查环境」） | 多一行「RAW 版本」：✓ 版本目录完整；或 ⚠ 「N 篇有写一半的旧版本目录，M 个过期暂存目录」+ 一句不影响使用 | **待她：一步** |

## 不在本 PR 里
- `ingest` 的两处「先占号再往里写」→ PR⑤ 真入口换成 stage_version。
- 收编孤儿版本（有完整 vNNNN 没 meta）→ PR⑤。
- 老半截版本：只报数不删（主审定）。

## 待她：一步
部署后点一次「检查环境」，看「RAW 版本」那行是 ✓ 还是 ⚠（⚠ 也正常，说明以前某次下载中崩过，重抓一次那篇就有完整版本）。
