# Current State

current_lot: 0
last_verified_commit: (本次 commit)

## 已真实通过

- `python -m link_brain --help` 跑通，列出 7 个子命令：`ingest / read / search / sync-favorites / inbox / resolve / comment`
- `docs/FORMAT.md` 首版：目录布局、RAW 版本规则、`meta.json` / `source.json` / `manifest.json` / `comments.jsonl` 完整示例、可见 md 模板与分层标记、留言行格式、SQLite 三张表建表语句、退出码表
- `python -m pytest -q` 全绿（8 项）：CLI 子命令齐全、`--help` 退出 0、未实现子命令返回 3、FORMAT.md 里每个 json 代码块都能被 `json.loads` 解析
- `.gitignore` 含 `vault/`、`.env`、`*.local.*`；`git ls-files` 无数据/密钥文件

## 已知缺口

- 任务书 Lot 0 验收写"列出 6 个子命令"，但同 Lot"做"那一节列了 7 个（`ingest / read / search / sync-favorites / inbox / resolve / comment`）。按 7 个实现，验收那句按笔误处理。
- `ingest` 之外的子命令全是占位，调用返回退出码 3。
- `index.py` / `render.py` / `vision.py` / `llm.py` / `comments.py` 只有模块文档和未实现异常。

## 下一步

Lot 1：`adapters/xiaohongshu.py` 接 18060 MCP，5 条样本各落一份不可变 RAW，调研结论写进 `docs/POC-xiaohongshu.md`。
