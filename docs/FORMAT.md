# FORMAT — light-web-archieve 数据格式规范（V1）

本文件是**格式的唯一真相**。代码只认这里定义的结构；`docs/TASKBOOK.md` 定"做什么"，本文件定"长什么样"。
改格式 = 改本文件 + 改代码 + 在 `docs/STATE.md` 记一笔。

约定：
- 所有 JSON 文件 UTF-8、缩进 2、`ensure_ascii=false`、末尾一个换行。
- 所有时间戳是 ISO-8601 本地时区带偏移，例如 `2026-09-04T14:30:00+10:00`。
- 所有路径字段是**相对该对象目录**的 POSIX 风格相对路径（`raw/v0001/assets/image-001.webp`），不写绝对路径、不写反斜杠。
- `null` 表示"确实没有"；缺字段表示"这版格式还没有这个字段"。二者不等价。

---

## 1. 目录布局

```
D:\LIGHT WEB ARCHIEVE\vault\
├─ Web\Xiaohongshu\<标题清洗后>__<note_id 后8位>.md   ← 人唯一看到的文件
└─ _archive\
   ├─ index.db                                       ← SQLite 索引
   └─ xiaohongshu\<note_id>\                         ← 一个"对象"
      ├─ meta.json                                   ← 可变：指向当前版本、记录归档状态
      ├─ comments.jsonl                              ← 可变：我们自己的留言层（不是原帖评论）
      ├─ raw\
      │  ├─ v0001\
      │  │  ├─ mcp_raw.json                          ← MCP 原始响应，原样
      │  │  ├─ source.json                           ← 归一化后的结构，后续代码只认它
      │  │  ├─ manifest.json                         ← 每个媒体文件一条记录
      │  │  └─ assets\image-001.webp ...             ← 原始 bytes，不转码
      │  └─ v0002\ ...                               ← 内容变了才有
      └─ derived\
         ├─ vision.json                              ← 图片 OCR（Lot 3）
         ├─ extracted.json                           ← 小模型派生（Lot 4）
         ├─ agent.md                                 ← AI 版全文（Lot 3/4）
         └─ previews\                                ← Obsidian 显示不了的格式转的副本
```

**`_archive` 用下划线不用点号**：Obsidian 不渲染点号开头文件夹里的图片。
`vault/` 整个目录在 `.gitignore` 里，任何样本数据都不进版本控制。

### RAW 版本规则

- 版本目录名 `vNNNN`，从 `v0001` 起，四位零填充。
- **RAW 不可变**：一个版本目录写完（`manifest.json` 落盘）后就不再打开写。发现抓错/抓漏 → 写下一个版本。
- 写新版本的唯一条件：重新抓取后的 `source.json` 与当前版本做规范化比对（忽略 `engagement` 里的数字、忽略字段顺序）后**有差异**。无差异只更新 `meta.json` 的 `last_checked_at`。
- 旧版本永远保留，`meta.json.current_version` 指向最新一版。

---

## 2. `meta.json`（对象级，可变）

```json
{
  "schema_version": 1,
  "item_id": "xhs-6512ab34cd7e9f0011223344",
  "source": "xiaohongshu",
  "source_id": "6512ab34cd7e9f0011223344",
  "canonical_url": "https://www.xiaohongshu.com/explore/6512ab34cd7e9f0011223344",
  "input_url": "https://xhslink.cn/o/2yNuSBjolWo",
  "kind": "image",
  "title": "P 模式到底怎么用",
  "author": {
    "user_id": "5f2c1a9b000000000101f0aa",
    "nickname": "小相机",
    "profile_url": "https://www.xiaohongshu.com/user/profile/5f2c1a9b000000000101f0aa"
  },
  "published_at": "2026-08-19T20:11:00+08:00",
  "first_archived_at": "2026-09-04T15:02:11+10:00",
  "last_checked_at": "2026-09-04T15:02:11+10:00",
  "current_version": 1,
  "versions": [1],
  "visible_note": "Web/Xiaohongshu/P 模式到底怎么用__11223344.md",
  "images_complete": true,
  "comments_complete": "unknown",
  "attachments_status": "unavailable",
  "origin": "cli",
  "actor": "human",
  "ingest_kind": "shared",
  "tool_versions": {
    "link_brain": "0.1.0",
    "adapter": "xiaohongshu/1",
    "mcp_endpoint": "http://127.0.0.1:18060/mcp"
  }
}
```

字段说明（只列不显然的）：

| 字段 | 取值 | 含义 |
|---|---|---|
| `item_id` | `xhs-<note_id>` | 全局标识；`source`+`source_id` 才是唯一键 |
| `kind` | `image` / `video` / `text` | 视频型笔记只记 `video_url` + 封面，不下载视频 |
| `images_complete` | `true` / `false` | 与 `manifest.json` 顶层同名字段一致；`false` 时 CLI 退出码 2 |
| `comments_complete` | `"unknown"` / `true` / `false` | 抓不全无法证明时是 `"unknown"`，**不阻断** |
| `attachments_status` | `"none"` / `"unavailable"` / `"ok"` | 笔记文件附件；MCP 拿不到就是 `"unavailable"`，主体照常归档 |
| `origin` | `tg` / `cmx` / `cc` / `cli` | 从哪个端进来的 |
| `actor` | `human` / `ai:<name>` | 谁把它丢进来的 |
| `ingest_kind` | `shared` / `favorite` | 主动分享还是收藏同步 |

---

## 3. `source.json`（版本级，不可变；**后续所有代码只认它**）

顶层三块：`note`、`comments[]`、`capture`。

```json
{
  "schema_version": 1,
  "source": "xiaohongshu",
  "source_id": "6512ab34cd7e9f0011223344",
  "note": {
    "note_id": "6512ab34cd7e9f0011223344",
    "xsec_token": "ABxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "canonical_url": "https://www.xiaohongshu.com/explore/6512ab34cd7e9f0011223344",
    "kind": "image",
    "title": "P 模式到底怎么用",
    "body": "第一段正文。\n第二段正文 #摄影 #相机",
    "hashtags": ["摄影", "相机"],
    "links": [
      {"url": "https://github.com/CyberMist123/light-web-archieve", "text": "仓库在这", "where": "body"}
    ],
    "author": {
      "user_id": "5f2c1a9b000000000101f0aa",
      "nickname": "小相机",
      "avatar_url": "https://sns-avatar-qc.xhscdn.com/avatar/xxx.jpg",
      "profile_url": "https://www.xiaohongshu.com/user/profile/5f2c1a9b000000000101f0aa"
    },
    "published_at": "2026-08-19T20:11:00+08:00",
    "engagement": {"liked": 1203, "collected": 880, "comment_count": 96, "shared": 41},
    "images": [
      {
        "index": 1,
        "url": "https://sns-webpic-qc.xhscdn.com/202609/aaaa.webp",
        "original_url": "https://sns-webpic-qc.xhscdn.com/202609/aaaa.webp!nd_dft_wlteh_webp_3",
        "width": 1080,
        "height": 1440
      }
    ],
    "video": null,
    "attachments": [
      {
        "name": "P模式速查表.pdf",
        "hint": "正文提到「文件已放在笔记附件」",
        "url": null,
        "status": "unavailable",
        "reason": "xiaohongshu-mcp 不返回笔记文件附件"
      }
    ]
  },
  "comments": [
    {
      "comment_id": "651300aa000000000a01",
      "floor": 1,
      "author": {"user_id": "60aa", "nickname": "路人甲"},
      "text": "所以 P 模式能锁快门吗",
      "created_at": "2026-08-19T21:02:00+08:00",
      "like_count": 12,
      "ip_location": "上海",
      "images": [
        {"url": "https://sns-webpic-qc.xhscdn.com/202609/cmt1.webp", "width": 720, "height": 960}
      ],
      "sub_comment_count": 3,
      "sub_comments_complete": "unknown",
      "sub_comments": [
        {
          "comment_id": "651300bb000000000a02",
          "floor": 2,
          "author": {"user_id": "60bb", "nickname": "小相机"},
          "target_nickname": "路人甲",
          "text": "能，转盘拨一下",
          "created_at": "2026-08-19T21:10:00+08:00",
          "like_count": 3,
          "ip_location": "广东",
          "images": []
        }
      ]
    }
  ],
  "capture": {
    "captured_at": "2026-09-04T15:02:11+10:00",
    "input_url": "https://xhslink.cn/o/2yNuSBjolWo",
    "input_kind": "shortlink",
    "adapter": "xiaohongshu/1",
    "mcp_endpoint": "http://127.0.0.1:18060/mcp",
    "mcp_tool": "get_feed_detail",
    "comments_complete": "unknown",
    "notes": []
  }
}
```

规则：
- `comments[]` 只放**一级评论**；楼中楼进 `comments[].sub_comments[]`，`floor` 一级=1、楼中楼=2（V1 小红书只有两层）。
- `comments[].images[]` 与 `note.images[]` 字段同构（`url` / `width` / `height` 可为 null）。
- `video` 非 null 时形如 `{"video_url": "...", "cover_url": "...", "duration_sec": 70, "downloaded": false}`。
- `attachments[]` 里 `status` 只有 `"unavailable"` / `"ok"`；拿不到就保留线索，**不阻断归档**。
- 去重只认 `source` + `source_id`；`xsec_token` 是抓取参数，会过期，不参与身份。

---

## 4. `manifest.json`（版本级，不可变）

每个真正落盘的媒体文件一条记录；没下下来的也留一条带 `error`。

```json
{
  "schema_version": 1,
  "version": 1,
  "created_at": "2026-09-04T15:02:14+10:00",
  "images_declared": 3,
  "images_ok": 2,
  "images_complete": false,
  "media": [
    {
      "role": "note_image",
      "index": 1,
      "file": "raw/v0001/assets/image-001.webp",
      "original_url": "https://sns-webpic-qc.xhscdn.com/202609/aaaa.webp",
      "requested_url": "https://sns-webpic-qc.xhscdn.com/202609/aaaa.webp",
      "mime": "image/webp",
      "width": 1080,
      "height": 1440,
      "bytes": 184320,
      "sha256": "3b1f0c7a2d5e4f6a8b9c0d1e2f3a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c",
      "download_status": "ok",
      "error": null
    },
    {
      "role": "note_image",
      "index": 2,
      "file": null,
      "original_url": "https://sns-webpic-qc.xhscdn.com/202609/bbbb.webp",
      "requested_url": "https://sns-webpic-qc.xhscdn.com/202609/bbbb.webp",
      "mime": null,
      "width": null,
      "height": null,
      "bytes": null,
      "sha256": null,
      "download_status": "failed",
      "error": "HTTP 404"
    },
    {
      "role": "comment_image",
      "index": 1,
      "comment_id": "651300aa000000000a01",
      "file": "raw/v0001/assets/comment-651300aa000000000a01-001.webp",
      "original_url": "https://sns-webpic-qc.xhscdn.com/202609/cmt1.webp",
      "requested_url": "https://sns-webpic-qc.xhscdn.com/202609/cmt1.webp",
      "mime": "image/webp",
      "width": 720,
      "height": 960,
      "bytes": 51200,
      "sha256": "aa11bb22cc33dd44ee55ff6677889900aabbccddeeff00112233445566778899",
      "download_status": "ok",
      "error": null
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `role` | `note_image` / `comment_image` / `video_cover` / `avatar` |
| `file` | 相对对象目录的路径；下载失败为 `null` |
| `original_url` | `source.json` 里那条记录的 url（身份用） |
| `requested_url` | 实际请求的那个 URL（可能去过 CDN 档位后缀） |
| `mime` | 按响应 `Content-Type` 记；扩展名由它决定 |
| `width` / `height` | Pillow 读出的真实宽高，不是页面声明值 |
| `sha256` | 落盘 bytes 的 sha256，小写 hex |
| `download_status` | `ok` / `failed` / `skipped`（如视频本体） |
| `error` | 失败原因，成功为 `null` |

**图片下载三检**（全过才算 `ok`）：① HTTP 2xx；② `Content-Type` 以 `image/` 开头；③ Pillow 能打开并读出宽高。
原始 bytes **原样落盘不转码**（webp 就存 webp）。

**缺内容 gate**：`images_declared != images_ok` → `images_complete: false`，CLI 打印缺哪几张并以退出码 **2** 结束。
评论抓不全无法证明 → `comments_complete: "unknown"`，**不阻断**。附件拿不到 → `status: "unavailable"`，**不阻断**。

---

## 5. `comments.jsonl`（对象级，可变；我们自己的留言层）

一行一个 JSON 对象，追加写，永不重写历史行。**这不是原帖评论**（原帖评论在 `source.json`）。

```json
{"comment_id": "cmt1", "actor": "human", "actor_id": null, "target": "none", "status": "open", "created_at": "2026-09-04T15:02:11+10:00", "date": "20260904", "text": "顺手存的，回头看 P 模式那段", "origin": "cli"}
```

| 字段 | 取值 |
|---|---|
| `comment_id` | `cmt<n>`，从 `cmt1` 起递增 |
| `actor` | `human` / `gpt` / `fable` / 其他角色名 |
| `target` | `none` 或角色名；`inbox --for X` 只看 `target == X` |
| `status` | `open` / `resolved` |
| `date` | `YYYYMMDD`，与可见 md 里那行显示的日期一致 |

`cmt1` 恒为 `ingest --note` 的原始附言（没有 `--note` 就没有 `cmt1`）。

---

## 6. 可见 md 模板（`vault/Web/Xiaohongshu/<标题>__<id8>.md`）

文件名：标题过 Windows 非法字符 sanitizer（`< > : " / \ | ? *`、控制字符、保留名 CON/PRN/AUX/NUL/COM1-9/LPT1-9、结尾点和空格）→ 截断到 60 字符 → 加 `__<note_id 后 8 位>`。

```markdown
---
cssclasses: [link-brain]
tags: [摄影, 相机]
link_brain:
  item_id: xhs-6512ab34cd7e9f0011223344
  source: xiaohongshu
  source_id: 6512ab34cd7e9f0011223344
  canonical_url: https://www.xiaohongshu.com/explore/6512ab34cd7e9f0011223344
  origin: cli
  ingest_kind: shared
  actor: human
  actor_id: null
  first_archived: 2026-09-04T15:02:11+10:00
  current_version: 1
  images_complete: true
  comments_complete: unknown
---

<!-- link-brain:comments:start -->
> [!quote] 留言
> 「20260904 人」顺手存的，回头看 P 模式那段
<!-- link-brain: id=cmt1 actor=human target=none status=open -->
<!-- link-brain:comments:end -->

<!-- link-brain:content:start -->
<div class="lb-cols"><div class="lb-imgs">
<img src="_archive/xiaohongshu/6512ab34cd7e9f0011223344/raw/v0001/assets/image-001.webp">
</div><div class="lb-body">

第一段正文。

第二段正文 #摄影 #相机

</div></div>

[原图 1](_archive/xiaohongshu/6512ab34cd7e9f0011223344/raw/v0001/assets/image-001.webp)

## 评论

> **路人甲** · 2026-09-01
> 所以 P 模式能锁快门吗
>
>> **小相机** · 2026-09-01
>> 回复 路人甲：能，转盘拨一下
>

## 归档信息

- 原链接：https://www.xiaohongshu.com/explore/6512ab34cd7e9f0011223344
- 首次归档：2026-09-04 · 版本 v0001
- 附件：unavailable（笔记文件 MCP 拿不到，线索见 source.json）
<!-- link-brain:content:end -->
```

硬规则：
- **顺序固定**：frontmatter → 留言层（callout） → 图文两栏容器 + 原图链接行 → 评论 → 归档信息。**没有 H1**（Obsidian 用文件名当标题），也没有「## 图片」「## 正文」这类小节标题。
- 两个分层标记 `<!-- link-brain:comments:start/end -->` 与 `<!-- link-brain:content:start/end -->` 必须成对存在。
  rerender **只重写 content 层**；comments 层里 Owner 手写的行原样保留。
- 留言层渲染成 Obsidian callout（`> [!quote] 留言`），是 frontmatter 之后第一块可见内容。
- 图文两栏：`<div class="lb-cols"><div class="lb-imgs">…</div><div class="lb-body">…</div></div>`，图片用 `<img src="vault相对路径">`（HTML 块里 `![[ ]]` 不渲染）；HTML 块内的 Markdown 段落之间要空行才生效。原图/视频原链接是容器**外面**的一行普通 Markdown 链接，这样 Obsidian 才能点。视频型（`note.kind == "video"`）图片栏只放封面，链接行换成 `🎬 视频 · 未下载 · [原链接](canonical_url)`。
- Obsidian 显示不了的格式（如 avif）`<img src>` 改指 `derived/previews/` 转码结果，原图链接仍指向 `raw/vNNNN/assets/`。
- 评论区渲染成 blockquote：一级评论 `> **昵称** · 日期` 换行接文本；楼中楼多一层 `>>` 嵌套；点赞数 > 10 才在头一行追加显示。
- `cssclasses: [link-brain]` 配 `vault/.obsidian/snippets/link-brain.css`（render 时不存在就写、存在不覆盖）：两栏 flex 布局、缩略图网格、隐藏属性面板、`## 评论`/`## 归档信息` 调成浅色小字。**Owner 要在 设置 → 外观 → CSS 片段 里手动打开一次 `link-brain`**。
- 可见 tag 只放原帖 hashtag（Lot 4 起可加小模型建议 tag）；用户手写 tag 永不被覆盖。
- 留言层永远不出现 `@ # todo` 之类协议词，人看到的就是「日期 角色」引用行。

### 留言行格式

```
「YYYYMMDD 角色」文本
<!-- link-brain: id=cmt1 actor=human target=none status=open -->
```

- 显示行的角色是中文短名（`人` / `fable` / `gpt`），隐藏注释里的 `actor` 才是机器认的值。
- 解析器必须容忍 Owner 在 Obsidian 里手写的裸 `「20260904 人」xxx` 行（没有隐藏注释）：按 `actor=human, target=none, status=open` 处理，不改写原行。

---

## 7. `derived/agent.md`（AI 版）

固定小节，缺的写"（未生成）"而不是省略：

```
# <标题>
## 概要
## 重要细节
## 数据点
## 外链
## 原文
## 图片 OCR
## 评论
## 元信息
```

---

## 8. SQLite（`vault/_archive/index.db`）

```sql
CREATE TABLE IF NOT EXISTS objects (
    item_id            TEXT PRIMARY KEY,
    source             TEXT NOT NULL,
    source_id          TEXT NOT NULL,
    canonical_url      TEXT NOT NULL,
    kind               TEXT NOT NULL,
    title              TEXT,
    author_nickname    TEXT,
    author_id          TEXT,
    body               TEXT,
    tags               TEXT,              -- JSON 数组字符串
    published_at       TEXT,
    first_archived_at  TEXT NOT NULL,
    last_checked_at    TEXT NOT NULL,
    current_version    INTEGER NOT NULL,
    object_dir         TEXT NOT NULL,     -- 相对 vault 的路径
    visible_note       TEXT,              -- 相对 vault 的路径
    images_complete    INTEGER NOT NULL DEFAULT 1,
    comments_complete  TEXT NOT NULL DEFAULT 'unknown',
    attachments_status TEXT NOT NULL DEFAULT 'none',
    summary            TEXT,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       TEXT NOT NULL REFERENCES objects(item_id) ON DELETE CASCADE,
    version       INTEGER NOT NULL,
    raw_dir       TEXT NOT NULL,          -- 相对对象目录，如 raw/v0001
    captured_at   TEXT NOT NULL,
    adapter       TEXT NOT NULL,
    input_url     TEXT,
    input_kind    TEXT,                   -- url / shortlink / share_text
    source_sha256 TEXT NOT NULL,          -- source.json 规范化后的 sha256
    UNIQUE (item_id, version)
);

CREATE TABLE IF NOT EXISTS relations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL REFERENCES objects(item_id) ON DELETE CASCADE,
    origin       TEXT NOT NULL,           -- tg / cmx / cc / cli
    actor        TEXT NOT NULL,           -- human / ai:<name>
    actor_id     TEXT,
    ingest_kind  TEXT NOT NULL,           -- shared / favorite
    note         TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_objects_title ON objects(title);
CREATE INDEX IF NOT EXISTS idx_relations_item ON relations(item_id);
```

同一对象被多次丢进来：**只加一行 `relations`，不重抓**。

---

## 9. 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 一般错误（解析不出 note_id、MCP 不在线等） |
| 2 | 缺内容 gate：明确知道缺东西（图片没下全） |
| 3 | 子命令尚未实现 |
