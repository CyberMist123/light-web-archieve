# 验收：第二波 PR③ 小红书整文件搬进 sources/xiaohongshu（1025）

入口：所有入口不变（插件、命令行、TG、夜跑、MCP 照旧 `python -m link_brain …`）。只搬文件、改相对 import，无新故障码、无界面变化、数据格式不变。

## 步骤 / 预期 / 实测

| 步骤 | 预期 | 实测 |
|---|---|---|
| `pytest tests/test_xhs_package_move.py` | 9 个旧路径和新路径是同一个模块对象，monkeypatch 旧路径新路径看得到；`comment_fill_worker_cwd_is_repo_root`、`account_guard_checks_program_root` 在「只搬家、不改 `__file__` 推目录」时红 | 修前 2 红 → 修后绿 |
| `pytest tests/test_guards.py` | import 契约 4 条按 `.importlinter` 基线（共享 → 小红书 24 条、小红书 → AI / 目录 6 条）无新增、无多余；最大环 78 | 绿 |
| `pytest tests/test_account_guard_1008.py` | 碰号闸认仓库根 | 绿 |
| 全量 pytest + node 与 main 对比 | 无新增失败 | 见 PR 描述 |
| 部署后：插件设置页「检查账号」（只看 `login --status`，不开页） | 还是绿的（碰号闸认程序目录没搬坏） | **待她：部署后看一眼** |

## 不在本 PR 里
共享层改走 `sources` 接口、收掉 `ignore_imports`（⑤b / ⑥）；`attachments` / `render` 拆分（⑥）；`pyproject` 加 import-linter 依赖（守卫用 AST 扫描，不需要）。
