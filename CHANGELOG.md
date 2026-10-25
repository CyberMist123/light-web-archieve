# 变更记录

版本号只有一个：`pyproject.toml` / `link_brain.__version__` 与插件 `obsidian-plugins/link-brain-actions/manifest.json` 一致（`link-brain-native-media-nav` 是独立小插件，单独计）。
每次合进 main 的改动在「未发布」下记一行人话；打版本时把「未发布」改成版本号和日期。更细的施工过程在 `docs/STATE.md`（给 AI 看的日志）。

## 未发布

- 开源前 P1：一页 `docs/ARCHITECTURE.md`；读取组件预编译发布工作流（`reader-v*` 标签 → GitHub Release，Windows x64 zip + sha256，上游基线钉在 `reader/UPSTREAM`）；
  问题记录旁路并回后删不掉时放 `.merged` 标记，不再卡住压实；`docs/FORMAT.md` 补 `tombstones.jsonl` / `problems.pending/` / `eid`；版本号统一为 0.2.0 并新增本文件。

## 0.2.0 — 2026-10-25

第一波「止血」+ 开源前 P0。此前 Python 包一直标 0.1.0、插件标 0.2.0，这里对齐到 0.2.0。

- 删除屏蔽以 `vault/_archive/tombstones.jsonl` 为准（只追加），`index.db` 只是缓存；删除半路崩了能接着做完（#8）。
- 问题记录：等不到锁写旁路再并回、每行带事件 id 去重；同一秒内先后按事件 id 排（#8）。
- 目录页构建离线、不花钱；夜跑收尾前 `index catch-up` 补向量 / 草稿 / 归类（#8）。
- Python 解释器路径成为插件唯一配置；缺依赖明确报错，不悄悄退化（#8）。
- 价格只在 `pricing.py`、免费只认显式标记、密钥只经 `providers`、命令行模型与 API 平级（ARCH-AUDIT 第 2 批，#6）。
- 插件 ↔ 后端 `catalog-data.schema` 握手，格式对不上提示「刷新目录 / 更新插件」而不是崩（#9）。
- `mcp` 依赖封顶 `<2`；GitHub Actions：pytest（ubuntu + windows）、node 单测、PR 隐私闸（#9）。
- 目录 `mark_dirty` / `ensure_fresh`、构建幂等、篇数一个口径；唯一数据来源守卫（ARCH-AUDIT 第 0/1 批，#5）。

## 0.1.0 及更早

2026-09 起的归档基座、目录页、问收藏、识图 / 转写、回收站、远程 MCP 等，见 `docs/STATE.md` 和 git 历史。
