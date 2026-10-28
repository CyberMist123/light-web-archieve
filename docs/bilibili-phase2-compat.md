# Bilibili 第二阶段：兼容性表（草稿）

2026-10-29，批次 A（收藏夹只读发现 + 快照）。任务书 §1 要求的那张表：每一行是哪个现成程序 / 接口提供、实际验证的版本、验收结果、缺口。
「实测」都是本机匿名（没登录）只读请求，没下载任何视频；下载相关几行引用阶段一（`feat/bilibili-phase1`）的结论，本批没重新验。

| 能力 | 谁提供 | 实际验证版本 / 接口 | 验收结果 | 缺口 |
|---|---|---|---|---|
| 来源发现（列收藏夹） | B 站只读接口 `x/v3/fav/folder/created/list-all?up_mid=`；封装在 `link_brain/sources/bilibili/favorites.py` 的 `list_folders` | 2026-10-29 实测 | ✅ 匿名能列出某人的**公开**收藏夹（`id` = 完整 media_id，`attr` 位 0 = 私密、位 1 = 非默认）；整个列表不公开时 `data=null` → `hidden`；0 个 → `empty` | 没登录时私密收藏夹直接不在列表里；Bili23 `parse --json` 不能替代（阶段一：bili23-downloader 3.0.0 的 parse 是占位实现）；稍后再看、收藏的合集（`ftype=collect`）没做 |
| 私密收藏夹 | 同上 + 阶段一登录态（`login.http_client()`） | 匿名实测 | 🟡 匿名读私密 / 已删收藏夹：`code=0`、`data.info=null` → 记 `forbidden`（「无权限或已删」），不当空收藏夹；接口文档写的 `-403` 也照认 | **待验**：阶段一登录接通后，用自己的号读自己的私密收藏夹；匿名分不清「私密」和「已删」 |
| 全量分页 | `x/v3/fav/resource/list`（`ps` ≤ 20，按 `has_more` 翻）+ `x/v3/fav/resource/ids`（一次给全部 id，用来核对成员） | 实测：公开收藏夹 204 条，11 页 | ✅ 见下「真实验收」。**实测发现**：没登录时分页列表会悄悄少条（3 页各 19 条、`has_more` 仍为 true），翻完 201 / 204；全部 id 接口给全 204 个。现在翻完条数不对就用全部 id 核对：对得上 → 补成 `listed=false` 的占位、`complete=true`；对不上 → `partial`。断页（412 / 429 / -412 / 超时两次 / 空页却说还有）→ `partial` + 缺页，上次完整快照不动；每页原子写检查点，续读只补缺页 | 少的那 3 条为什么不给游客看没查清（视频详情接口匿名请求回非 JSON，没继续试，免得撞风控）；登录后是否还少待验。千条以上的大收藏夹只在单测里翻过（45 条 / 3 页）、真号上没跑 |
| 多 P 枚举 | 收藏列表的 `page`（分 P 数）+ `ugc.first_cid`；逐 P 的 `pages[]/cid` 要视频详情接口或下载器 | 收藏列表实测 | 🟡 收藏列表只给分 P **数**（实测 204 条里 2P×7、3P×2、4P×1、6P×1）和第一 P 的 cid，快照里记 `page_count / first_cid`，预览按它估 P 数 | 逐 P 的 cid / 标题 / 时长：批次 B 用阶段一的元数据路径取（`pages[]`），收藏列表的数只作预估 |
| 单 P 定向下载 | yt-dlp（阶段一选型） | yt-dlp 2026.10.26（阶段一） | 本批没测 | 批次 B |
| 不同语言字幕 | yt-dlp | 同上 | 本批没测 | 批次 B；字幕要登录态（阶段一 cookie 文件） |
| XML 弹幕 | yt-dlp | 同上 | 本批没测 | 批次 B |
| 失败断点续传 | 收藏扫描：本模块的逐页检查点；下载：yt-dlp `--continue` / `.part` | 扫描实测；下载没测 | ✅（扫描）真号上 `--max-pages 4` 读到第 4 页停 → 再跑从第 5 页接着读，最后完整 204 条；总数变了就从第 1 页重来（页码会错位） | 下载续传批次 B 验 |
| 登录态复用 | 阶段一 `login.py`：Netscape cookie 文件 + 扫码 | 阶段一 | 本模块按契约函数内 import `login.status()` / `login.http_client()`；模块不在（阶段一没合）→ `unavailable`，退回匿名只读，私密收藏夹如实 `forbidden` | 接通后待验；`bili23-downloader` 3.0.0 不可用（占位实现、非官方发布），浏览器 Cookie 提取本机全部失败（阶段一） |
| 进度 / 输出机器可读性 | 本模块：`python -m link_brain.sources.bilibili.favorites list <mid>` / `scan <链接>`，stdout 只有最后一行 JSON（`read.outcome` 外形），逐页进度走 stderr；快照 JSON 有 `pages_read / missing_pages / error.reason` | 实测 | ✅ 退出码 0 完整 · 3 没读全（原因在 JSON）· 2 认不出链接 · 1 列表出错 | 还没挂到 `python -m link_brain` 子命令和插件（`cli.py` 归阶段一）；没进同步记录 / 问题记录（批次 C） |

## 真实验收（只读、没登录）

- 收藏夹 A（公开，默认收藏夹，`media_id 44***21`，owner `77***21`）：`media_count=204`，读 11 页（第 3 / 4 / 6 页各 19 条），分页去重前 201 / 去重后 201（没有跨页重复），全部 id 接口 204 个，补 3 条占位后 `complete=true`；失效 2 条（`attr=1`，标题「已失效视频」）；预计分 P 221。第二次跑：`new 0 / same 202 / unavailable 2 / unfavorited 0`，关系表 `seen 204`。分轮读：`--max-pages 4` → `partial`、`missing_pages=[5]`、退出 3；再跑从第 5 页续上，完整。快照和关系表里搜 `SESSDATA / bili_jct / cookie / upos / deadline=` 均为 0。
- 收藏夹 B（公开、合法空，`media_id 1**`）：`info.media_count=0`、`medias=null`、`has_more=false` → `status=empty, complete=true`。
- 收藏夹 C（文档示例里的旧收藏夹，现在匿名看 `info=null`，`folder/info` 回 11010）→ `forbidden`，没写「上次完整快照」。
- **没做**：两个含同一 BV 的真实收藏夹（匿名找不到同一个人的两个公开收藏夹共有 BV；单测覆盖了，真号待登录后用自己的收藏夹验）；私密收藏夹；千条以上。

## 接口字段（以实测为准，文档出处：bilibili-API-collect 的 fav/info.md、fav/list.md；原 SocialSisterYi 仓库已 404，用的是任务书给的 pskdje 镜像）

- 收藏夹 `id`（mlid，完整 id）= `fid` 后面接 owner mid 的末两位（实测 `fid=1` + mid 尾 `01` → `101`）。链接里的 `favlist?fid=` 给的是完整 id。
- 收藏项 `type`：2 视频、12 音频、21 视频合集（只有视频有 bvid，其余按 `<kind>:<id>` 记，不丢）；`attr`：0 正常、9 UP 主删了、1 其他原因删了。
- 翻过最后一页：`medias=null, has_more=false`；不是数字的 id：`-400`；不存在：`code=0, data=null`。
