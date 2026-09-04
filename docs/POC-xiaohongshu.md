# POC — 小红书通过 xiaohongshu-mcp 到底能拿到什么

实测于 2026-09-04，端点 `http://127.0.0.1:18060/mcp`，样本是任务书文末 5 条（A–E）。
下面每条都是**跑出来的**结论，不是推测。

## 结论速查（issue 第 14 节要的 5 条）

| # | 问题 | 结论 |
|---|---|---|
| 1 | 楼中楼能不能拿到、拿到几层 | **能，且能拿全。小红书本身只有 2 层**（一级评论 + 回复），MCP 也只返回 2 层 |
| 2 | 评论图有没有 | **没有。** MCP 的评论对象结构里根本不存在图片字段，拿不到 |
| 3 | 高清档位 | **`urlDefault` 就是能拿到的最高档**，改/去后缀一律 403（URL 带签名）；实拿 1080×1440，页面声明 1200×1600 |
| 4 | 附件 | **MCP 拿不到**（响应里没有附件字段）；**网页版游客能拿到元数据**（`relatedFile`），字节要登录。见第 4 节 |
| 5 | MCP 返回的完整键列表 | 见下面第 5 节 |

---

## 1. 楼中楼：能拿全，只有两层

`get_feed_detail` 传 `load_all_comments=true` + `click_more_replies=true` + `reply_limit=100` 时：

- 每条一级评论有 `subCommentCount`（字符串）和 `subComments`（数组）。
- **5 条样本里 `len(subComments) == int(subCommentCount)` 无一例外**，包括 D 那条 17 条回复的楼。
- `subComments[i]` 自己也有 `subCommentCount` / `subComments`，但实测**恒为 `""` / `null`** —— 小红书楼中楼就是两层，不存在第三层。
- 因此 `source.json` 用 `comments[].sub_comments[]` 两层就够，`floor` 只有 1 和 2。
- `sub_comments_complete` 由 `len(subComments) >= subCommentCount` 判定，**5 条样本全部为 `true`**。

**一级评论的完整性有明确信号**：`data.comments.hasMore`。
用 `limit=50` 抓 D 时 `hasMore=true`（只拿到 50 条）；改成 `limit=200` 后 `hasMore=false`、拿到 64 条一级评论 + 95 条楼中楼。
所以 `comments_complete` 不必永远写 `"unknown"`——`hasMore=false` 时可以判定为 `true`。
adapter 默认 `limit=200`、`reply_limit=100`；**5 条样本全部 `comments_complete=true`**。
（代价：D 那条抓了约 3 分钟，MCP 是真的在无头浏览器里滚页面。）

## 2. 评论图：拿不到

MCP 评论对象的键是固定的 11 个：
`id / noteId / content / likeCount / createTime / ipLocation / liked / userInfo / subCommentCount / subComments / showTags`。
**没有任何图片/媒体字段**，一级评论和楼中楼都一样。样本 D（任务书标注"有评论图"）的 64 条一级评论里也搜不到任何图片 URL。

结论：这是 MCP 的结构性缺口，不是参数没开对。`source.json` 的 `comments[].images[]` 恒为 `[]`，
`manifest.json` 里也就不会出现 `role: comment_image`。

想要评论图，只能走硬约束 10 的 `agent-browser` 复用登录态补抓。
**Lot 1 没有开浏览器**（MCP 能给的都拿全了、样本验收不缺它），留给 Lot 3 视觉验收时再决定。

## 3. 图片高清档位：`urlDefault` 封顶，后缀不可改

`imageList[i]` 只有 4 个键：`width` / `height` / `urlDefault` / `urlPre`。

实测同一张图（样本 A 第 1 张，声明 1200×1600）：

| URL | HTTP | Content-Type | 字节 | 实际尺寸 |
|---|---|---|---|---|
| `urlDefault`（`!nd_dft_wlteh_webp_3`） | 200 | image/webp | 41190 | 1080×1440 |
| `urlPre`（`!nd_prv_wlteh_webp_3`） | 200 | image/webp | 12686 | 1080×1440 |
| 去掉 `!...` 后缀 | **403** | text/html | 238 | — |
| 换 `!nd_whgt_webp_3` | **403** | — | — | — |
| 换 `!nd_dft_wgth_webp_3` | **403** | — | — | — |
| 换 `!nd_dft_wlteh_jpg_3` | **403** | — | — | — |
| 拿 `urlPre` 的路径拼 `!nd_dft_...` | **403** | — | — | — |

关键发现：**URL 路径里那段 32 位 hex 是签名**，和后缀绑定。任何改动（去后缀、换档位、换格式、跨 URL 拼）都 403。
所以"去掉 `!nd_dft_wlteh_webp_3` 得原图"这个常见说法在当前 CDN（`rednotecdn.com`）上**不成立**。

- `urlDefault` 与 `urlPre` 尺寸相同（1080×1440），差别在压缩率（41KB vs 12KB）→ **取 `urlDefault`**。
- 拿到的比页面声明的小一档（1080 vs 1200），这是 CDN 侧的降采样，客户端无解。
- 格式恒为 `webp`，**原 bytes 原样落盘不转码**，扩展名按响应 `Content-Type` 定。
- 下载要带 `Referer: https://www.xiaohongshu.com/` 和移动端 UA（不带也能过，但保险）。

## 4. 附件：MCP 拿不到，但**网页版游客就能看到元数据**（2026-09-04 更新）

`get_feed_detail` 的 `data.note` 只有 10~11 个键（见下），**没有附件/文件相关字段**——这条结论不变。

但笔记**网页版**的 SSR 状态里有：

```
window.__INITIAL_STATE__
  .note.noteDetailMap["<note_id>"].note.relatedFile
    = {docId, name, icon, bizExtra:"{download_num,page_num,view_num}"}
```

**不需要登录**，一个普通 `httpx.get(笔记URL?xsec_token=..&xsec_source=pc_feed)` 就能拿到。
样本 A 实测：`name="p模式教程-机教版.pdf"`、`docId=7658854832003020032`、19 页、644 次下载。

前端路由（从 `index.*.js` 里读出来的）：`FilePreviewPath = "/file/:docId"`，
点附件卡片就是 `window.open("/file/<docId>?noteId=..&fileName=..&xsec_token=..&xsec_source=note_detail_file")`。

**字节要登录。** 游客打开那个预览页，页面写死一句「登录即可下载该文件 / 登录后可下载 / 无法查看，原文件不可见」
（in-app 浏览器实测，2026-09-04）。所以：

| | 游客 | 登录后 |
|---|---|---|
| 附件元数据（名字/页数/docId） | ✅ | ✅ |
| 附件字节 | ❌ | 待验（需要一个登录态） |

adapter 现在的处理（`fetch_related_file` + `_attachments`）：

- ingest 时顺手 GET 一次笔记页，`relatedFile` 有就写成一条带真名字/`doc_id`/页数/预览 URL 的
  `attachments[]`，`status="metadata_only"`，`meta.attachments_status="metadata_only"`；
- `relatedFile` 是 `None` 且页面确实解析到了这条笔记 → **这篇就是没挂文件**，正文里提到"文件"也不再误报；
- 页面 200 但状态里没有这条笔记（登录墙 / 已删 / 反爬占位页）→ 当**探测失败**处理，退回正文
  `ATTACHMENT_HINT_RE` 线索、`status="unavailable"`。这一步很重要，否则会把线索一起吞掉；
- 探测原始结果落 `raw/vNNNN/web_raw.json`，方便以后回溯"当时页面上到底有没有附件"。

**元数据这条路整条是游客可达的**，不用登录、不用开浏览器。

### 4b. 附件字节：要登录 + 必须开浏览器（2026-09-04 打通）

下载走：

```
POST https://webapi.rednote.com/web_api/sns/v1/file/download
body: {"document_id": "<docId>", "note_id": "<noteId>"}
```

**直接回文件字节**（不是回一个 URL）。但它要 `X-s` / `X-t` / `X-S-Common` 三个签名头，
签名逻辑在小红书自己的前端 bundle 里且会变——**本仓不复刻签名**，让浏览器自己去发这个请求。

实测出来的硬约束（`link_brain/attachments.py` 就是按这几条写的）：

| 坑 | 现象 | 对策 |
|---|---|---|
| headless | 那个 POST 一直挂着不返回，页面不报错 | **必须 `--headed`** |
| Chrome 问保存位置 | 自动点击被当成"下载已取消" | 先改 profile 的 `Preferences`：`download.prompt_for_download=false` + `default_directory` |
| `agent-browser open <url>` | 登录态的小红书页面不进 idle，命令永不返回 | `open` 空白页，再 `eval` 改 `location.href` |
| `subprocess.run(capture_output, timeout)` | Windows 上超时只杀 `cmd.exe`，node 攥着管道，`run()` 永远挂住 | Popen + 输出重定向到文件 + 超时 `taskkill /T /F` |
| 账号 | 主号在 18060 MCP 那侧，两边不能同时在线 | agent-browser profile 用**另一个小号**登录 |
| 权限 | 游客调 `file/preview` 回 `{"code":-104,"msg":"您当前登录的账号没有权限访问"}`，`user/me` 回 `guest:true` | 登录后即可 |

样本 A 实测：`p模式教程-机教版.pdf`，1,436,001 字节，
sha256 `13543169d7010630c0b74670d1000c9e79a5de88074bbe22cacbc0e84a965f23`
（手工点击下载和 `python -m link_brain attachments` 自动下的字节完全一致）。

顺带发现：评论走 `GET /api/sns/web/v2/comment/page?note_id=..&image_formats=jpg,webp,avif&xsec_token=..`，
**参数里明写了 image_formats**——以后要补评论图，这条是入口（V1 不做）。

## 5. MCP 返回的完整键列表

顶层：`{feed_id, data}`；`data` = `{note, comments}`。响应是**一段 JSON 文本**塞在 `content[0].text` 里，
`structuredContent` 为 `None`——所以客户端要自己 `json.loads`。

### `data.note`

```
noteId, xsecToken, title, desc, type, time, ipLocation, user, interactInfo, imageList
                                                                          [, video]   ← 仅 type=="video"
```

- `type`：`"normal"` / `"video"`
- `time`：毫秒时间戳
- `desc`：正文全文，话题以 `#词[话题]#` 内联在末尾（adapter 用 `HASHTAG_RE` 抠成 `hashtags[]`）
- `user`：`{userId, nickname, nickName(常为空), avatar}`
- `interactInfo`：`{liked, likedCount, sharedCount, commentCount, collectedCount, collected}`，**计数全是字符串**，`sharedCount` 常为 `""`
- `imageList[i]`：`{width, height, urlDefault, urlPre}`
- `video`：`{image:{firstFrameFileid, thumbnailFileid}, capa:{duration}, media:{videoId, video:{duration,md5,...}, stream:{av1[], h264[], h265[]...}}}`
  - 取 `media.stream.h264[0].masterUrl` 当 `video_url`，`capa.duration` 当秒数
  - 视频型笔记的 `imageList` 就是**封面**（样本 B：1 张），role 记 `video_cover`
  - **视频本体按设计不下载**，manifest 里一条 `role:"video", download_status:"skipped"`

### `data.comments`

```
{list: [...], cursor: "<最后一条评论 id>", hasMore: bool}
```

`list[i]` 与 `list[i].subComments[j]` 同构，11 个键：

```
id, noteId, content, likeCount, createTime, ipLocation, liked,
userInfo{userId,nickname,nickName,avatar}, subCommentCount, subComments, showTags
```

- `showTags`：如 `["is_author", "user_top"]`
- 楼中楼**没有** `target_nickname` 之类的"回复谁"字段；被回复者只能从正文/上下文推
- `ipLocation` 常为 `""`

### 明确**不存在**的东西

评论图、笔记附件、正文富文本结构（超链接是纯文本）、@用户结构化列表、收藏夹归属。

---

## 6. 短链解析

`https://xhslink.cn/o/<code>` 用 httpx **不跟随重定向** GET，读 `Location`：

```
302 → https://www.xiaohongshu.com/discovery/item/<note_id>?...&xsec_token=<token>&...
```

- 一跳到位，`xsec_token` 就在 query 里（**必须有它，`get_feed_detail` 缺 token 抓不到**）
- 要带**移动端 UA**
- canonical URL 统一成 `https://www.xiaohongshu.com/explore/<note_id>`
- 三种输入（短链 / 正常 URL / 分享文本）实测解出同一个 `note_id` ✅

## 7. 其它顺手记的

- 工具清单里有 `get_my_profile(tab=note|fav|liked)` 和 `user_profile(..., tab=fav)`——
  **Lot 6「没有收藏列表工具」这个前提可能不成立**，开 Lot 6 前先花 10 分钟试 `get_my_profile(tab="fav")`。
- `check_login_status` 返回的是**人话文本不是 JSON**，客户端要容忍。
- Lot 1 全程**没有开 agent-browser**，收尾复查 `check_login_status` 仍是「已登录」，MCP 没被顶下线。
- 控制台是 GBK，跑脚本要 `PYTHONIOENCODING=utf-8`，否则 emoji 会 `UnicodeEncodeError`。

## 8. 5 条样本实拿数据（2026-09-04）

| # | note_id | kind | 图片 | 一级评论 | 楼中楼 | comments_complete | 附件 |
|---|---|---|---|---|---|---|---|
| A | 6a49b7ff…522c | image | 12/12 | 32 | 22 | true | unavailable（线索："给小机看的版本在文件～"） |
| B | 6a8be1e1…a211 | video | 1/1（封面） | 17 | 11 | true | none |
| C | 6a994947…082f | image | 8/8 | 17 | 2 | true | none |
| D | 6a2758e0…1731 | image | 13/13 | 64 | 95 | true | none |
| E | 6a6b59e4…19fe | image | 7/7 | 28 | 71 | true | none |

D 的 GitHub 外链：**正文和评论里都没有裸 URL**，只有文字提及（"GitHub 里面搜不到"、"github 仓库喔"、影子仓库名 `Haven-Ombre`）。
评论正文原样进 `source.json`，所以信息保留了，但 `note.links[]` 是空的——Lot 4 让小模型点它时要从正文/评论文本里认，不能指望 `links[]`。

---

## 9. 18060 那个服务为什么会"挂"（2026-09-05 查清，批量必读）

批量跑 31 条收藏时，跑到第 19 条开始每条都秒失败：

```
MCP get_feed_detail 报错: 工具 get_feed_detail 执行时发生内部错误: [launcher] Failed to get the debug url
```

**不是掉登录、不是风控、服务进程也活得好好的。** 机制是这样：

1. `xiaohongshu-mcp` **每次工具调用都新开一个自带的 Chrome**（`newBrowser()` 在每个 handler 里，
   二进制在 `%LOCALAPPDATA%\xiaohongshu-mcp\browser\<版本>\browser\chrome.exe`）。
2. 调用超时/客户端断开时，**那个 Chrome 不回收**，变成孤儿进程常驻。
3. 孤儿越堆越多 → 可用物理内存被吃干 → 下一次 `MustLaunch` 拿不到 DevTools 的 debug url → panic。
4. 于是后面每一条都在 3 秒内失败，看起来像"服务挂了"。

实测数据：可用内存 0.5–0.9 GB 时连挂 14 条；杀掉 7 个孤儿 Chrome + 重启服务后回到 2.77 GB，恢复正常。
`xhs-ensure.log` 里那串「登录态查询失败：(500) 内部服务器错误」也是同一个根因，不是登录问题。

**批量脚本要做的三件事**（本仓的 CLI 只负责报警和退避重试，杀进程属于机器维护，不写进仓库）：

- 每条之前回收孤儿：`Get-Process chrome | Where-Object { $_.Path -like '*xiaohongshu-mcp*' } | Stop-Process -Force`
  ——**按二进制路径认**，Owner 自己的 Chrome 一根汗毛都不碰。
- 可用内存低于 ~1.4 GB 就等着，别硬跑。
- 撞退出码 5 先自愈一次（回收 + `Start-ScheduledTask XiaohongshuMCP`），第二次才停车报警。

CLI 这侧对应的行为：`ServiceDownError` + 退避重试 3 次（20s/60s），见 `link_brain/ingest.py`。
