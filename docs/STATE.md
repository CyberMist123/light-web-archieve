# Current State

current_lot: 1
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

## 已知缺口

- **评论图 MCP 结构上就没有**（评论对象 11 个键里没有任何媒体字段）。Lot 1 没有开 agent-browser 补抓；收尾复查 `check_login_status` 仍在线。要评论图得走硬约束 10 的浏览器路，留到 Lot 3 视觉验收时决定。
- **附件靠正文关键词启发式**（「附件 / 在文件 / 文件里 / 笔记文件」）识别线索，会漏也会误报；MCP 完全不返回附件对象。
- **图片拿到的是 1080 宽的 CDN 降采样档**（页面声明 1200）。URL 带签名，去后缀/换档位一律 403，客户端无解。
- 样本 D 的 GitHub 外链在原帖里就**没有裸 URL**，只有文字提及；`note.links[]` 为空，文字本身在 `source.json` 里原样保留。
- 任务书 Lot 0 验收写"列出 6 个子命令"，同 Lot"做"那节列了 7 个；按 7 个实现。
- `read / search / inbox / resolve / comment / sync-favorites` 仍是占位（退出码 3）；`ingest --refresh` 属 Lot 2，当前直接报错退 1。
- 没有索引、没有去重：同一链接再 ingest 一次会因 `raw/v0001` 已存在而报错退 1（Lot 2 接 `HIT` 逻辑）。
- D 那条抓满评论约 3 分钟（MCP 在无头浏览器里真滚页面），批量抓要留够超时。

## 下一步

Lot 2：`index.py` 建 SQLite 三表、`ingest` 接去重（命中打 `HIT` 不联网）、`--refresh` 做规范化比对决定是否写 `v0002`、`read` / `search` 落地。
