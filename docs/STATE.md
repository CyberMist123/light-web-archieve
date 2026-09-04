# Current State

current_lot: 3
last_verified_commit: (本次 commit)

## 已真实通过

### Lot 0
- `python -m link_brain --help` 列出 7 个子命令：`ingest / read / search / sync-favorites / inbox / resolve / comment`
- `docs/FORMAT.md`：目录布局、RAW 版本规则、`meta.json` / `source.json` / `manifest.json` / `comments.jsonl` 完整示例、可见 md 模板与分层标记、留言行格式、SQLite 三表、退出码表
- `.gitignore` 含 `vault/`、`.env`、`*.local.*`；`git ls-files` 无数据/密钥文件

### Lot 1
- `adapters/xiaohongshu.py`：三种输入（短链 / 正常 URL / 分享文本）实测解出同一个 `note_id`；短链走不跟随重定向的 `Location`
- 连 18060 MCP `get_feed_detail`（`load_all_comments` + `click_more_replies`，`limit=200` / `reply_limit=100`），原始响应原样落 `mcp_raw.json`，归一化落 `source.json`
- 图片下载三检（HTTP 2xx / Content-Type 是图片 / Pillow 读出宽高），原 bytes 原样落盘、按 Content-Type 定扩展名、算 sha256、写 `manifest.json`
- **5 条样本各落一份 `raw/v0001/{mcp_raw.json,source.json,manifest.json,assets/}`**：
  A 12 图 / 32 一级 / 22 楼中楼 / 附件 unavailable；B kind=video、assets 只有封面、视频只记 URL；
  C 8 图；D 13 图 / 64 一级 / 95 楼中楼；E 7 图 / 28 一级 / 71 楼中楼。五条 `images_complete=true`、`comments_complete=true`
- 缺内容 gate 用脱敏 fixture + 坏 URL 触发：`images_complete:false`、每张失败有 `error`、退出码 2、主体仍照常归档（不碰任何已写好的 `raw/v0001`）
- `docs/POC-xiaohongshu.md`：楼中楼 / 评论图 / CDN 档位 / 附件 / MCP 完整键列表 5 条结论全部有"能 / 不能 / 只能到 X"
- `python -m pytest -q` 16 项全绿

### Lot 2
- `index.py`：SQLite `vault/_archive/index.db`，`objects/sources/relations` 三表按 `docs/FORMAT.md §8` 建，`(source, source_id)` 唯一约束
- `ingest`：canonicalize → 查索引 → 命中打 `HIT`（`--verbose` 可见"不调用 MCP"、raw 下仍只有已有版本，不联网不下载）→ 未命中才走 Lot 1 adapter
- `ingest --refresh`：规范化比对（忽略 `engagement` 与 `captured_at`）；无变化只更新 `last_checked_at`、不产生新版本；有变化写 `raw/v0002`，`v0001` 字节不变（sha256 验证过）
- `read <item_id|url>` 打印 `meta.json`；`search <词>` LIKE 查标题/正文，输出 `item_id | 标题 | 首次归档日期`
- 每次 ingest 把 `origin/actor/ingest_kind/note` 写进 `relations` 表；同一对象多次进入只加 relation 不重抓
- 新增 `reindex` 子命令：从已有 `raw/vNNNN/source.json` + `meta.json` 回填索引，不重抓不联网（用于 5 条 Lot 1 样本首次建库）
- 真机验证：5 条样本 `reindex` 回填成功；`ingest`（真链接）第二次打 `HIT`、`--verbose` 确认无 MCP 调用、`raw/` 仍只有 `v0001`；`search "P模式"` 命中样本 A
- `tests/test_index.py` 5 个用例（唯一约束、HIT 无网络、refresh 无变化不产生 v0002、refresh 有变化产生 v0002 且 v0001 sha256 不变、search 命中）；`python -m pytest -q` 21 项全绿

### Lot 3
- `vision.py`：对每个对象 `raw/v0001/assets/` 每张图 subprocess 调 `media.py image --ocr`，结果落 `derived/vision.json`（`asset` 回指 `raw/v0001/assets/`，按 sha256 跳过已识别）；单张失败记 `status:failed` 不阻断。5 条样本共 41 张图，实测**全部 OCR 成功（41 ok / 0 failed）**
- `render.py`：纯程序拼模板；人看版 `vault\Web\Xiaohongshu\<标题清洗后>__<id8>.md` 严格按 `docs/FORMAT.md §6` 顺序（标题→留言层→图片→正文→评论→归档信息），frontmatter 走 `link_brain:` 键；图片 `![[_archive/xiaohongshu/<id>/raw/v0001/assets/xxx.webp]]`；评论没有图（MCP 结构上拿不到）就不输出图片段，不留占位；楼中楼缩进两格
- `derived/agent.md`：按 `docs/FORMAT.md §7` 八个固定小节；"概要/重要细节"两节 Lot 3 阶段留空占位，其余（数据点/外链/原文/图片 OCR/评论/元信息）程序填
- rerender 只重写 content 层，comments 层原样保留：`tests/test_render.py::test_rerender_preserves_hand_written_comments_layer` 覆盖；另外拿真实样本手写一行再 `render` 实测确认保留（验完已清理，不留测试痕迹在 vault）
- `read --brief`（标题+正文前120字，≤5行）、`read --full`（打印整个 `agent.md`）、`search` 每条一行 `item_id | title | 1行概要 | tags | 日期`
- 新增 `render <item_id|--all>` 子命令；`ingest` 归档成功后自动跑 vision+render（失败只打印 warning，不影响 ingest 退出码）
- 修了一个 Windows 控制台编码坑：`__main__.py` 里把 stdout/stderr 强制 `reconfigure(encoding="utf-8", errors="replace")`，否则打印含 emoji/生僻字的文件名（如样本"‼️"）在 gbk 控制台直接 `UnicodeEncodeError` 崩溃
- 5 条样本 `render --all` 实测：`vault/Web/Xiaohongshu/` 下恰好 5 个 md，无重复文件；两次 `render --all` 输出 md5 完全一致（幂等）
- `python -m pytest -q` 28 项全绿（Lot 3 新增 `tests/test_render.py`）

## 已知缺口

- **评论图 MCP 结构上就没有**（评论对象 11 个键里没有任何媒体字段）。渲染层已按此定案：评论没有图就不输出图片段，不留占位；要评论图得走硬约束 10 的浏览器路，V1 未开。
- **附件靠正文关键词启发式**（「附件 / 在文件 / 文件里 / 笔记文件」）识别线索，会漏也会误报；MCP 完全不返回附件对象。
- **图片拿到的是 1080 宽的 CDN 降采样档**（页面声明 1200）。URL 带签名，去后缀/换档位一律 403，客户端无解。
- 样本 D 的 GitHub 外链在原帖里就**没有裸 URL**，只有文字提及；`note.links[]` 为空，文字本身在 `source.json` 里原样保留。
- 任务书 Lot 0 验收写"列出 6 个子命令"，同 Lot"做"那节列了 7 个；按 7 个实现。
- `inbox / resolve / comment / sync-favorites` 仍是占位（退出码 3）——Lot 5/6 才做。
- `derived/agent.md` 的"概要/重要细节"两节 Lot 3 阶段留空占位，等 Lot 4 小模型派生填。
- D 那条抓满评论约 3 分钟（MCP 在无头浏览器里真滚页面），批量抓要留够超时。
- `index.db` 不入版本控制（在 `vault/` 下），新克隆仓库/换机器要先跑一次 `python -m link_brain reindex` 把 5 条样本的 raw 回填进索引。

## 下一步

Lot 4：小模型派生（`llm.py` 调 `media.py text` 生成 summary/key_points/tags/links_worth_opening/valuable_comments，补 `derived/agent.md` 的概要/重要细节两节 + `docs/BENCH.md`）。
