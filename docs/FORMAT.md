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
  "input_url": "https://xhslink.cn/o/FakeLink00",
  "kind": "image",
  "title": "P 模式到底怎么用",
  "author": {
    "user_id": "5f00000000000000000000a0",
    "nickname": "小相机",
    "profile_url": "https://www.xiaohongshu.com/user/profile/5f00000000000000000000a0"
  },
  "published_at": "2026-08-19T20:11:00+08:00",
  "first_archived_at": "2026-09-04T15:02:11+10:00",
  "last_checked_at": "2026-09-04T15:02:11+10:00",
  "current_version": 1,
  "versions": [1],
  "visible_note": "Web/Xiaohongshu/P 模式到底怎么用__11223344.md",
  "images_complete": true,
  "comments_complete": "unknown",
  "attachments_status": "metadata_only",
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
| `comment_load` | 对象 / `null` | 读取组件（≥ 10-04）给的评论加载结论，压缩后：`stop_reason`、`floor_limit`、`floors_loaded`、`floors_expanded`、`has_more`、`replies_missing`、`gaps[]`（只留 `missing>0` 的楼：`floor / comment_id / shown / loaded / missing / reason`）、`seconds`；续读过的多 `fill_attempts`、`fill_last_at`、`floors_not_found[]`。老组件没有 → `null` |
| `attachments_status` | `"none"` / `"metadata_only"` / `"downloaded"` / `"unavailable"` | 由 `attachments[].status` 取最好的一个汇总而来；见 `source.json` 那节 |
| `origin` | `tg` / `cmx` / `cc` / `cli` | 从哪个端进来的 |
| `actor` | `human` / `ai:<name>` | 谁把它丢进来的 |
| `ingest_kind` | `shared` / `favorite` | 主动分享还是收藏同步 |
| `visible_note_pinned` | `true` / 缺省 | 1001：`visible_note` 指的文件找不到时，按 frontmatter 的 `link_brain.item_id` 在可见目录（含子目录）找回她改过名 / 挪过位置的那份并沿用；此后重渲染不按标题挪回去 |

可见 md 的身份只认 frontmatter 里的 `link_brain.item_id`（YAML 写坏了退回正则找这一行）。
她手写的属性 YAML 写坏时：单行 `键: 值` 解析不了的值原样当字符串留下；再解析不了就整段 frontmatter 原样保留、
不改名，只在日志里记警告。

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
      "user_id": "5f00000000000000000000a0",
      "nickname": "小相机",
      "avatar_url": "https://sns-avatar-qc.xhscdn.com/avatar/xxx.jpg",
      "profile_url": "https://www.xiaohongshu.com/user/profile/5f00000000000000000000a0"
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
        "doc_id": "7658854832003020032",
        "hint": "正文提到「文件已放在笔记附件」",
        "url": "https://www.xiaohongshu.com/file/7658854832003020032",
        "icon_url": "https://fe-platform.xhscdn.com/platform/xxx",
        "page_num": 19,
        "download_num": 644,
        "view_num": 1468,
        "file": null,
        "status": "metadata_only",
        "reason": "小红书网页版要登录才给附件字节；元数据取自笔记页 relatedFile"
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
    "input_url": "https://xhslink.cn/o/FakeLink00",
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
- `attachments[]` 的 `status`：
  | 值 | 含义 |
  |---|---|
  | `"metadata_only"` | 网页版 `relatedFile` 拿到了名字 / `doc_id` / 页数，**字节还没拿到**（小红书要登录才给文件）。`url` 是网页预览地址，`file` 为 `null` |
  | `"downloaded"` | 字节已落**对象级** `attachments/`，`file` 是相对对象目录的路径（见下） |
  | `"unavailable"` | 网页探测失败，只有正文正则抠出来的 `hint`，其余字段全 `null` |

  网页探测成功且 `relatedFile` 为空 = 这篇**确实没挂文件**，此时 `attachments` 直接是 `[]`
  （正文提到"文件"也不再误报）。拿不到附件**永不阻断归档**。
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

## 6. 可见 md 模板（`vault/Web/Xiaohongshu/<标题>.md`）

文件名就是清洗过的标题，**不带 `__<id8>` 后缀**（Owner 2026-09-04 点名）。
只有那个名字已经被别的笔记、或者 Owner 手写的同名老文件占了，才退回 `<标题>__<id8>.md`——
判断靠读对方 frontmatter 里的 `link_brain.item_id`，绝不覆盖不属于自己的文件。

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
- （批次 D · L3）内容层的 `.lb-note` 带 `data-lb-item="<item_id>"`（插件图片导航按它记住每篇钉没钉 / 第几张 / 正文滚到哪；没有时退回文件路径）；笔记图和评论图 `<img>` 带 manifest 里的 `width` / `height`（两个都是正整数才写），视频的行内 style 带 `aspect-ratio:<宽> / <高>`（视频条目自己的，没有就用封面的）。评论缺口和「原帖有 N 条评论，这次没存下来」行末尾有 `<span class="lb-act lb-act-fetch-comments" role="button" tabindex="0">`（插件开着时才显示）；正文标签 `<span class="lb-tag" title="在目录里看带 #x 的收藏">`。HTML 属性一律双引号。CSS 片段写到插件传来的 `LINK_BRAIN_OBSIDIAN_DIR/snippets/`（没有就写收藏库已有的 `.obsidian`，再没有往上 3 层找带 `app.json` 的库），不再在收藏子目录里新建 `.obsidian`；桌面插件另把同一份样式（`obsidian-plugins/link-brain-actions/note.css`，和 `link_brain/assets/link-brain.css` 逐字节相同）挂进 head。

### 留言行格式

```
「YYYYMMDD 角色」文本
<!-- link-brain: id=cmt1 actor=human target=none status=open -->
```

- 显示行的角色是中文短名（`人` / `fable` / `gpt`），隐藏注释里的 `actor` 才是机器认的值。
- 解析器必须容忍 Owner 在 Obsidian 里手写的裸 `「20260904 人」xxx` 行（没有隐藏注释）：按 `actor=human, target=none, status=open` 处理，不改写原行。

---

## 7. `derived/agent.md`（AI 版）

给 AI 读的精简版（2026-10-08 批次 B 起；拼法 `render.render_agent_md`，清洗规则 `link_brain/agentmd.py`）。
节的顺序固定，**没内容的节整节省略**（不再写"（未生成）"）：

```
# <标题>

来源 <canonical_url> · 作者 <昵称> · 发布 YYYY-MM-DD · 赞 N / 藏 N / 评 N · vN[ · 图片没下全][ · 评论没读全]
## 概要
## 重要细节
## 外链
## 原文
## 图片 OCR
## 视频文字稿
## 视频画面文字
## 评论
```

- 标题下一行 = 原「数据点」「元信息」两节合并；值为 None 的不写。item_id / 路径不写（frontmatter 和目录里都有）。
- `概要` / `重要细节` 由 `derived/extracted.json`（第 7b 节）填；和概要重复（归一化后 partial_ratio ≥ 90）的要点不写。
- `外链`：原帖链接（标出处：正文 / 评论 c1.1）+ 小模型建议的 http 链接；同一 URL 只写一次（建议理由并到那行后面）；
  没有 http 链接的「hint」线索不写。附件行照旧。
- `原文`：正文全文，不删改。
- `图片 OCR`：节开头一行写原图目录（`_archive/<源>/<id>/raw/vNNNN/assets/`，image-NNN.webp 按图号、评论图 comment-<评论id>-N.webp，
  远程用 read_asset）；≥3 张图时，≥50% 的图里都有的短行（≤12 字，水印 / 栏目名）在开头写一次「每张图都带：…」。
  每张图一个小标题 `### 第N张（图N · image-NNN.webp）`（10-15 起），下面依次「描述：…」「图上文字：」+ OCR 原样逐行（行框竖向空隙大的地方空一行分段），
  空的不出。OCR 去掉二进制装饰串、≤2 个有效字符的行（两个汉字的词保留）、只有数字和符号的短行；顶格 `#` 转义成 `\#`。
  识图描述去掉「图内文字转录如下」段和与 OCR 重复的句子，和前面某张图描述相似 ≥ 80% 的写「描述：同第N张」；
  描述不硬截，安全上限 400 字且只在句末（。！？；）截、超出「…（略）」；每图 OCR ≤ 600 字（按整行截，超出「…（略）」），
  全节 ≤ 3000 字，超出后的图只留小标题和「（略，超出图片字数上限）」。按图校对的文字 / 表格 / 流程图要点每图 ≤ 800 字（按整行截）；
  精细识别（refined）结果不截。只有识别没把握（`visual.shaky` / 识图失败 / 图片识别失败）的图单独写原图路径。
  （1017）识图存疑的图（判据见第 7c 节，与 vision.json 的 `doubt_reason` 同一个函数）在这张图最后写**一句**：`识图存疑（<原因>），文字仅供参考，以原图为准。原图：<路径>`（识别失败的那张前面已写原因，只写 `原图：<路径>`）；评论图写在那张评论图的行下面。这一句不计入图片节 3000 字上限，图片被「略」掉时也照写。
  图号与资产的对应不变（问答证据身份「图3」读 vision.json，不读这里）。
- `视频文字稿`：连着重复的英文词 / 短语合并（we we → we）；和正文重复的句子去掉；超过 3000 字按句切成 ≤ 400 字的段落（空行分开）。
- `视频画面文字`：去乱码行，和已留下的行 ratio ≥ 85 的去掉，和正文 / 文字稿 partial_ratio ≥ 90 的去掉；≤ 1500 字，
  超出留最长的若干段并写「（已截断，共 N 段）」。`transcript.json` 的 `screen.v` 为 2（10-08 起，按 OCR 行存）时逐行比；
  没有 `v` 的旧数据是一帧一行（空格拼），按空格拆成小块再比。
- `评论`：每行 `- [c3] 昵称：内容`，楼中楼缩进 `  - [c3.1] …`；**楼号是 `llm.comment_labels` 的原编号，略去的楼不让号**。
  作者本人标「（作者）」，小模型标的有价值评论行尾「（值得看：…）」。水话（去掉表情码 `[xxxR]` 和 @ 后 ≤ 10 字且没有实词）
  和小模型标的广告 / 噪音不写；作者回复过的楼、作者本人（非水话）的回复、值得看的、带图片文字的优先留。评论图片只写有文字的
  （按图校对的文字或去乱码后的 OCR，≤ 300 字），表情包 / 无文字 / 识图描述不写。上限 30 条、3000 字（优先的楼不受字数限），
  末尾一行「（另有 N 条评论略去：水话 / 噪音 a 条，超出上限 b 条）」。读评论缺口那行（楼中楼还缺）照旧在节首。
- 全文软上限约 1 万字符：超出时依次压评论（20 条 / 2000 字 → 12 条 / 1000 字）→ 图片（1500 字）→ 画面文字（800 字）→ 再全压一档；
  正文、概要、文字稿不压。正文 / 文字稿本身就超长时，可压的三节仍保留约 3000 字。

---

## 7a. `attachments/` + `attachments.json`（对象级，可变）

附件字节是**事后**补下来的（小红书要登录才给文件），而 RAW 版本写完就封存，
所以字节**不进 `raw/vNNNN/`**，落对象级目录：

```
_archive/xiaohongshu/<note_id>/
├─ attachments/<原文件名>          ← 字节原样落盘
└─ attachments.json               ← 索引：doc_id / sha256 / 大小 / 下载时间
```

```json
{
  "schema_version": 1,
  "files": [
    {
      "doc_id": "7658854832003020032",
      "name": "p模式教程-机教版.pdf",
      "file": "p模式教程-机教版.pdf",
      "bytes": 1436001,
      "sha256": "13543169d7010630c0b74670d1000c9e79a5de88074bbe22cacbc0e84a965f23",
      "downloaded_at": "2026-09-04T21:49:03+10:00"
    }
  ]
}
```

`render` 按 `doc_id` 把它回填到 `source.json` 的附件条目上（`file` / `status="downloaded"`），
可见 md 里那行 📎 就从"未下载"变成指向本地文件的链接。**RAW 目录一个字节都不动。**

1001 起记录上可能多出的键：
- `manual_ids`：手动挂过（`manual-…`）后又认回真编号，合并成这一条，原 manual 编号记在这里（`attachments --dedupe` 修存量）。
- `conversion_failed`：`{note, sha256, code, at}`。字节下好了（文件头对得上）但转不成 md：字节保留、不重下。
  `code` 是故障码（CONVENTIONS §2）：`PERMANENT.*`（加密 / 损坏 / 不支持的格式）同一份 sha256 不再每晚重转，`pdf2md --force` 才重试；
  `TRANSIENT.*` 下次照转。1B 之前的旧记录没有 `code`，按 PERMANENT 算。没开 OCR 的扫描件是「跳过」，不写这个键。
- `conversion_partial`：`{pages_failed, sha256, tries}`。有几页 OCR 没认出来，那几页写占位、整份照出，最多再试 3 次。

事后才知道的附件声明（正文线索解析出的真编号、`--recheck` 探到的文件）写对象级
`attachments-resolved.json`（`{"schema_version":1,"resolved":[{doc_id,name,url,page_num,hint,via,resolved_at}]}`），
读的时候和 `source.json` 的 `note.attachments` 合并（`attachments.declared_attachments`）；**不回写已封存的 source.json**。

---

## 7b. `derived/extracted.json`（小模型派生，Lot 4）

对象级、可重生成：删掉它重跑 `render --extract` 只会重新调模型，**不会重抓网页**。
用哪个模型 = 设置里的「归档摘要模型」（`summaryAI`，默认和文本 AI 相同；第 1B 批起）。
`data` 只有 `status == "ok"` 时才可信；`status == "failed"` / `"skipped"` 时 `data` 为 `null`，
渲染层不写概要 / 重要细节两节并且**不阻断**。`skipped` = 没配模型（`code: "SKIPPED.NOT_CONFIGURED"`），配上后 enrich 会补。

```json
{
  "schema_version": 1,
  "status": "ok",
  "version": 1,
  "model": "qwen3.7-flash",
  "generated_at": "2026-09-04T19:20:31+10:00",
  "attempts": 1,
  "first_try_ok": true,
  "usage": {
    "input_tokens_est": 3979,
    "output_tokens_est": 593,
    "cost_usd_est": 0.00017664,
    "note": "接口回传的 usage"
  },
  "code": "",
  "error": null,
  "data": {
    "summary": "不超过 3 行的概要",
    "key_points": ["要点"],
    "tags": ["AI", "开源"],
    "links_worth_opening": [
      {"url": "https://example.com/a", "hint": "", "why": "正文里的链接"},
      {"url": "", "hint": "Yinglianchun/Ombre-Brain", "why": "原帖只提到仓库名，没给链接"}
    ],
    "valuable_comments": [{"id": "c3", "why": "有实操细节"}],
    "ads_or_noise": ["c8"]
  }
}
```

字段规则：

| 字段 | 规则 |
|---|---|
| `version` | 派生自哪个 RAW 版本；`current_version` 变了要重跑 |
| `attempts` | 1 或 2（schema 校验失败只重试 1 次） |
| `usage` | 接口回传了 usage 就用它，否则按字符估（`note` 写明是哪种）；价格按模型名查 `link_brain/assets/llm-config.yaml` 的 `pricing`，查不到记 0 |
| `code` | 失败 / 跳过时的故障码（CONVENTIONS §2），成功为空 |
| `data.tags` | 先按 `docs/tag-vocab.yaml` 归一，再洗成 Obsidian 合法 tag（只留字母数字 `_ - /`，空格转 `-`） |
| `data.links_worth_opening[].url` | 只可能是 `http(s)://` 开头；模型给的其他东西（仓库名、`javascript:` 之类）一律降级进 `hint`，永不当链接渲染 |
| `data.valuable_comments[].id` / `ads_or_noise[]` | 只能是输入里出现过的评论编号，其余丢弃 |

可见 md 的 `tags:` = 原帖 hashtag ∪ 文件里已有的（含 Owner 手写）∪ 小模型建议，
大小写不敏感去重，**只增不减**。frontmatter 里非 `cssclasses` / `tags` / `link_brain` 的键
一律当作 Owner 手写，rerender 原样保留。

---

## 7c. `derived/vision.json`（图片 OCR / 识图，对象级，可变）

```jsonc
{"schema_version": 1, "version": 1, "upgraded_v": 3,
 "images": [{"asset": "raw/v0001/assets/image-003.webp", "status": "ok",           // 本地 OCR 这一张成没成
             "ocr": "…", "ocr_v": 2, "lines": [{"text": "…", "box": [x0, y0, x1, y1], "score": 0.93}],
             "layout": "text",                                                       // 本地版面判断 / 第一层判的类型
             "visual": {"kind": "text|table|diagram|picture|title", "status": "ok", "text": "…", "v": 3,
                        "shaky": "", "model": "…"},                                  // 第一层识图
             "refine": {"status": "pending|done|failed", "reason": "…", "tries": 3, "at": "…",
                        "error": "出现复读", "fallback": "layer1", "tried": "m / 换参数（温度 0.6） / 换模型 x"},
             "refined": {"kind": "text", "status": "ok", "text": "…", "model": "…"},  // 第二层精细识别（成功才有）
             "doubt": true, "doubt_reason": "疑似手写，精细识别没过"}]}             // 1017：识图存疑
```

- **`doubt` / `doubt_reason`（1017 新增，只加字段、向后兼容）**：这张图的识图 / OCR 文字靠不住时才有（`doubt: true` + 一句短原因，多个原因用「，」连）；
  靠得住时两个字段都不写。写入时机：`build_vision`（第一层 / OCR 跑完）和 `refine_object`（每张精细识别后）。
  没有这两个字段的旧文件，机读版按同一判据现算（`agentmd.doubt_reasons`），读的一方别把「没有字段」当成「靠得住」以外的意思。
- **判据**（`link_brain/agentmd.py` 的常量，有回归用例）：
  - `识别失败`：本地 OCR 这张没成（`status != ok`）。
  - `精细识别没过`：`refine.status == "failed"`——换参数 / 换模型 / 分段都不合格退回第一层（`fallback: "layer1"`），或请求被拒累计 3 次。
  - 第一层自己的毛病：`visual.shaky`（输出被截断 / 出现复读 / 输出过长）原样写；第一层失败写 `识图没成功`。
  - `OCR 大半没认准`：参与计算的有效字（字母数字汉字假名谚文）≥ `DOUBT_MIN_CHARS`=20，且其中 ≥ `DOUBT_RATIO`=50% 出自信心
    < `DOUBT_LOW_SCORE`=0.65 的行。`junk_line` 判掉、但认得很有把握的装饰行（二进制串、键盘单字、表盘数字）不参与；没有逐行信心的旧 OCR 不判。
  - `疑似手写`：同上，但第一层识图文字里说了「手写」时门槛放宽到 `DOUBT_RATIO_HANDWRITE`=30%。
  - `多处看不清`：显示给 AI 的识图文字（精细识别成功就看它，否则第一层）里 `[看不清]` / `[无法辨认]` ≥ `DOUBT_UNREADABLE`=3 处。
  - 精细识别成功（`refined.status == "ok"`）的只按最后一条判（强模型看过原图）；标题图（`visual.kind == "title"`）不判。
- 识图存疑**不是故障**：不进 `problems.jsonl`、不上目录卡片角标（1017 作者裁决；接口那一侧的故障照旧走 `ai_health`）。

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
| 0 | 成功 / 部分完成（到 `--budget-min`、到每日上限，剩下的下次接着来；同步撞限频「刚同步过」也是 0） |
| 1 | 一般错误（解析不出 note_id、MCP 不在线、同步连续 3 篇没抓到、收藏数可疑等） |
| 2 | 缺内容 gate：明确知道缺东西（图片没下全） |
| 3 | 子命令尚未实现 |
| 5 | **要人处理**：登录态失效 / 风控验证码 / 被跳到登录异常页 / 读取服务熔断中（`RISK_HOLD`）/ 18060 的 MCP 挂了。批量脚本看到这个码就该停车，**后面所有会用号开页的步骤都跳过**，接着跑只会把剩下的全刷成失败 |
| 6 | 号正被别的任务占着（`~/.link-brain/account.lock`：同步收藏 / 附件 / catch 同一时刻只有一个在用号），过会儿再试 |

退出码 5 同时会走一次报警（见下）。`login --status` 另有一套：0 已登录 · 3 游客 · 4 查不清（忙 / 超时 / 连不上 / 锁被占）· 5 熔断中；
`--json` 那一行照旧给插件画按钮（`state`=ready/expired/…），脚本读 `login_state`（logged_in / guest / unknown / risk_hold）。

**`login --status --json` 契约（1001 定稿，偏离跨组件契约 B.5 的地方以这里为准）**：

| 字段 | 取值 | 谁读 |
|---|---|---|
| `state` | 插件账号面板的取值：`ready` / `expired` / `not_logged_in` / `captcha` / `busy` / `unknown` / … | Obsidian 插件（按它画状态和按钮）。**脚本不要判它**：它永远不是 `guest` / `risk_hold` |
| `login_state` | `logged_in` / `guest` / `unknown` / `risk_hold`（契约里叫 `state` 的那个值） | 20:00 登录检查等脚本 |
| `code` / `detail` | 码和细节；熔断中 `code`=`RISK_HOLD`，另带 `risk_hold` 对象 `{code, since, detail}` | 人和日志 |
| `hold_cause` | 熔断中时是熔断起因（`NOT_LOGGED_IN` / `ACCOUNT_RISK` / `CAPTCHA_REQUIRED`），否则空串 | 脚本据此说「掉登录了，去扫码」还是「风控暂停中」 |

退出码和 `login_state` 一一对应（0/3/4/5），脚本优先按退出码判，退出码不在这四个里（崩了）再看 `login_state`。

**附件 `--budget-min N`**（`attachments --all` / `--recheck` / 单篇）：从进程开始算（等账号锁的时间也在里面）。
开下一个附件页 / 下一次登录号补看之前，剩下的时间装不下它的最坏耗时（歇够 + 开页间隔 + 下载 240 秒 / 补看 150 秒）
就收手，照常转 md、渲染、重建目录、汇总，退出码 0；没轮到的记 `deferred`（不算失败、不报警），下次接着补。
补查里「探到了附件但没时间下」的那篇保持待查，明晚接着下。

**同步里的已知坏篇**：以前就抓不到的收藏（`_archive/sync-failures.json` 里有记录：已删 / 仅作者可见）排在最后抓；
它们再失败时条目带 `known_bad: true`，不算这次同步出错（不让退出码变 1、状态变「部分失败」），
但一晚里连着失败 3 篇就收手，余下的已知坏篇当晚不再开页（`held_known_bad` 计数，也计入 `skipped_failing`）。

### 报警

出这种事不许不知不觉挂着跑（Owner 2026-09-04 点名）。`link_brain/alert.py` 只认一个环境变量，
**本仓库公开，所以这里不含任何推送地址/key**：

```
LINK_BRAIN_ALERT_CMD="python C:\...\lwa-alert.py"
```

那条命令从 **stdin 收一个 UTF-8 JSON**，自己决定怎么送（Bark / TG / 邮件）：

```json
{"kind": "service_down", "title": "小红书归档停了：18060 的服务要人管", "body": "MCP get_feed_detail 说「[launcher] Failed to get the debug url」", "url": "https://www.xiaohongshu.com/explore/..."}
```

`kind` 四种：`account_blocked`（登录态/风控）、`service_down`（18060 或它的浏览器挂了）、
`attachment_failed`（附件字节没拿到）、`batch_aborted`（批量停车）。
没配这个变量时读 `~/.link-brain/alert-cmd.txt` 的第一行（`#` 开头的是注释）；两处都没有就退化成 stderr 一行；
报警命令自己挂了也**不会**影响归档。

---

## 10. `catch` / `--json` 输出（给主模型的摘要通路）

给人用的是 CLI 文本，给主模型用的是**一行 JSON**。约定：

- **stdout 只有那一个 JSON**，一行，UTF-8 字节（不受 Windows 控制台 GBK 影响）；
  所有日志、错误说明都走 stderr。调用方可以直接 `json.loads(stdout)`。
- 路径一律**绝对路径**（调用方的 cwd 不确定）；文件不在盘上就是 `null`。
- 不起 HTTP / MCP 服务（硬约束 8），TG / CMX 端就是 Bash 直调这个 CLI。

### `catch "<消息全文>"`

消息全文里自己找小红书链接（host 白名单：`xiaohongshu.com` / `xhslink.cn` / `xhslink.com`），
每条链接跑一次 `ingest`（命中索引就是 `hit`，不联网），整条消息当 `--note` 存成留言 cmt1。
没有链接就是 `{"found": 0, "items": []}`，零成本、不碰网络。同一篇笔记在一条消息里出现两次只算一条。

```json
{
  "found": 1,
  "items": [
    {
      "item_id": "xhs-6a49b7ff000000001502522c",
      "status": "new",
      "title": "ClaudeCode自建前端-P模式全教",
      "summary": "小模型概要；没有 extracted.json 就退回正文前 120 字",
      "tags": ["ai编程", "教程"],
      "kind": "image",
      "visible_note": "D:\\LIGHT WEB ARCHIEVE\\vault\\Web\\Xiaohongshu\\ClaudeCode自建前端-P模式全教.md",
      "agent_md": "D:\\LIGHT WEB ARCHIEVE\\vault\\_archive\\xiaohongshu\\6a49b7ff000000001502522c\\derived\\agent.md",
      "attachments": {
        "status": "downloaded",
        "items": [
          {
            "name": "p模式教程-机教版.pdf",
            "doc_id": "7658854832003020032",
            "status": "downloaded",
            "pages": 19,
            "url": "https://www.xiaohongshu.com/file/7658854832003020032",
            "file": "D:\\LIGHT WEB ARCHIEVE\\vault\\_archive\\xiaohongshu\\6a49b7ff000000001502522c\\attachments\\p模式教程-机教版.pdf"
          }
        ]
      },
      "url": "https://www.xiaohongshu.com/explore/6a49b7ff000000001502522c"
    }
  ]
}
```

字段：

| 字段 | 说明 |
|---|---|
| `status` | `new`（这次才归档）/ `hit`（早就有了，没联网）/ `error`（这条链接没抓成）/ `blocked`（号出事，已停车）/ `busy`（号正被同步收藏占着，`--wait-lock-min` 内没等到，稍后再收） |
| `summary` | `derived/extracted.json` 的小模型概要；没有就是正文前 120 字 |
| `tags` | 可见 md frontmatter 里的 `tags`（原帖 hashtag + 小模型建议 + Owner 手写都在里面） |
| `attachments.status` | `none` / `unavailable` / `metadata_only` / `downloaded`（见 §7a） |
| `error` | 只在出问题时出现：`status=error` 是这条没归档成；归档成了但渲染失败也会带这个键 |
| `url` | `canonical_url`，**只当去重键**（硬约束 7） |
| `open_url` | 能真正点开的地址：canonical + 抓取时那个 `xsec_token`。光有 `/explore/<id>` 小红书现在回 404（2026-09-05 实机），给人看链接一律用这个 |

`status=error` 的条目只有 `item_id`（可能是 `null`）/ `status` / `url` / `error` 四个键：

```json
{"found": 1, "items": [{"item_id": null, "status": "error", "url": "https://xhslink.cn/o/xxxx", "error": "AdapterError: 短链解不出笔记 URL"}]}
```

退出码：全部成功 `0`；有任何一条 `status=error` 是 `1`；`blocked` 是 `5`；`busy` 是 `6`（JSON 照样打全）。
识图（带 `--extract` 时连概要）在放掉账号锁之后跑，每篇一个子进程、20 分钟上限；没补完的条目带 `error`，夜里 `enrich --pending` 会补。

### `read <target> --brief --json`

和 `catch` 的 item 同一份结构，只是没有 `status` 键（它没有 new/hit 的概念）。

### `read <target> --full --json`

```json
{"item_id": "xhs-6a49b7ff000000001502522c", "agent_md": "D:\\...\\derived\\agent.md", "markdown": "# 标题\\n## 概要\\n..."}
```

### `search <词> --json`

只查 SQLite，不读对象目录（快），所以 `summary` 是正文前 120 字而不是小模型概要：

```json
{
  "found": 1,
  "items": [
    {
      "item_id": "xhs-6a2758e00000000008031731",
      "title": "ombre二改更新介绍：跨窗口/平台无缝对话",
      "summary": "正文前 120 字",
      "tags": ["人机恋"],
      "kind": "image",
      "url": "https://www.xiaohongshu.com/explore/6a2758e00000000008031731",
      "first_archived": "2026-09-04"
    }
  ]
}
```


## 2026-09-16 搜索和附件补充契约

- 2026-10-02 第 2 批：`items[].cover_w / cover_h` 是封面原图宽高（取 manifest，拿不到为 null，目录页用来先占位）；
  `items[].starred / starred_at` 在 `note star` 时就地更新（不必等重建），目录页以它为准、不再逐篇读 notes.json。
- 2026-10-08 批次 D：`items[].hashtags` = 原帖话题（source.json 的 `note.hashtags`，去掉开头 `#`，最多 30 个）；目录页「#x」筛选看 `tags ∪ hashtags`
  （她改过的 frontmatter tags 可能删掉了某个原帖话题）。`note star <target...> [--off]` 一次接多个 id：
  `{ok, code, message, results:[{item_id, status, starred, starred_at, error}], count_ok, catalog_patched, catalog_stat?}`，
  catalog-data 整批只改一次；`catalog_stat = {mtime, size}` 是锁内写完那一刻的 stat（mtime = round(st_mtime_ns / 1e6)），只在真改了才给；
  只有一个 target 时额外带旧顶层键 `item_id / status / starred / starred_at`。全部 ok 退出码 0，否则 1。
- 2026-10-03 第 10 批：`search_fields.notes` = 用户在这篇里写的批注（notes.json 里没删的、非空的，一条一行，草稿不算），
  词法权重同标签、语义单独成块（改批注只重算那一块）；问收藏按 notes.json 修改时间现读，不等重建。
  问答结果多 `related`（候选池里没送进模型的其余篇，`tier: "related"`）、`sources[].tier = "primary"`、`expansion`；
  请求可带 `source_ids`（只用这些来源重答）。扩词缓存 `_archive/query-expand-cache.json`（问题 → 词，最多 500 条）。
- `catalog-data.json.items[].search_fields` 分为 `body/comments/ocr/attachments`，均保留原文；
- 1017：目录页 / 已收藏页的 md 里只有一小段 dataviewjs 引导（`link_brain/assets/page-bootstrap.js`），页面脚本（lb-page-lib + catalog-search + catalog-view）由 `catalog.build` 写到 `_archive/catalog-page.js` / `_archive/starred-page.js`（和 `_archive/annotate-view.js` 同一个做法）；引导按文件 mtime:size 认版本，编译好的函数缓存在 `globalThis.__lbPageCode`。
- 1015：`search_fields` 和 `pinyin` 不再写在 `catalog-data.json` 里，拆到 `_archive/catalog-search-index.json` = `{built_at, items: {<id>: {search_fields, pinyin}}}`（catalog-data 顶层 `search_index` 指向它）。目录页首开不读，第一次带词搜索才读（catalog-search.js `ensureSearchIndex`）；Python 读方经 `catalog.merge_search_index` 并回（`ask.load_items`、`indextree.catalog_items` 已接）。items 自带 `search_fields` 的旧数据照旧能用。
  `summary` 为模型摘要，检索权重低，不伪装成原文。`agent_md` 是 vault 相对路径。
- 2026-10-15 第二批：`search_fields` 再分出三路（空的不写）——`comment_ocr` = 评论区图片的文字（资产名 `comment-<id>-<n>.*`，
  不再混在 `ocr` 里）；`screen` = 视频画面文字（以前拼在 `transcript` 尾巴上，`transcript` 现在只有口播稿）；
  `highlights` = 她划的重点（可见笔记里的 `<mark>` / `==x==` + notes.json 的 `highlights`，一条一行，权重同批注）。
  `comments` 仍只放评论原文（昵称不进检索，免得昵称当内容命中）；说话人由问收藏证据阶段按楼号另挂。语义索引同样分块（重建 embed 时补）。
- `attachment_files` 逐条提供 `doc_id/name/downloaded/status/file/markdown/url`，文件和 Markdown
  路径为本机绝对路径（该索引仅用于本机 UI/CLI）；`attachment_missing` 是未落字节数。
  `attachment_errors` 来自对象级 `attachment-state.json`，包含上次自动下载的错误。
- `attachments --audit` 返回 `items/missing/total/unconfirmed`，`unconfirmed` 是只有正文线索、
  没有确认 doc_id 的待处理项，不能声称这些都是已确认存在的文件。
- `search --json` 返回 `query/total/results`，保留旧 `found/items` 字段；每项的 `excerpts`
  是 `{field,text}` 原文窗口，含 `score/agent_md/visible_note/attachments`。
- `ask` 返回 `{status,kind:"answer",markdown,sources,matches,materials,model_called}`；
  sources 提供编号、标题和正文路径。失败使用 `status:"error"`，不会把摘录伪装成模型回答。
- `ask --history-stdin` 接收 `[{role:"user"|"assistant",content:"..."}]`，最多使用最近 8 条；
  用户问题可辅助召回，旧模型答案不能作为证据。引用正文与附件 MD 可继续由 CC/Codex 读取。

- 跨渠道统一请求：`ask --request-stdin` 接收 `{question,history?,include?}`，include 仅支持
  `body/links/files`。`body` 总会提供，默认只返回 `delivery.body`，不自动附来源编号或文件。
- `delivery.links[]` 为 `{title,url,source_id,markdown_path}`；`delivery.files[]` 为
  `{name,path,mime_type,bytes,source_id,markdown_path}`。仅使用实际存在的本地文件，
  来源编号存在时只选择被引用材料。链接地址来自归档索引，不从模型文字里提取或虚构。
- `history` 是可供下次请求传回的最近对话；失败请求不追加一条假答案。
  发送器应消费 `delivery`，不要把内部 `sources` 或本机路径直接展示为公共下载地址。

### 问收藏响应：档位 / 目录 / 展开（2026-10-15 第二批，ask 车 ↔ chat 车约定）

请求（`ask.answer(...)`、`ask --request-stdin`、问答常驻进程 `serve` 的一行 JSON 都一样，新增键可省略）：

```jsonc（带注释，示意）
{"question": "我要吃辣的", "history": [...], "exclude_ids": [], "pin_ids": [],
 "mode": "direct | toc（可省略 = 自动判档）",
 "expand": {"turn_id": "t1015093012ab12cd", "ids": ["xhs-…", "xhs-…"], "all": false}}
```

- `expand`：展开某一答里的几条。后端按 `turn_id` 查那一答的登记（`_archive/ask-turns.json`，最近 200 轮）：问题用那一答的原问题，
  `ids` 只留那一答里真有的（别的丢）；省略 `ids` 或 `all:true` = 那一答目录全部（最多 20 条）。登记查不到（过期 / 换机）时
  用请求里的 `question + ids` 照答。**不再发固定话术、不再绑「上一答」**。展开不重搜、不出目录、每条预算放足（≤3 条按深读）。
- 默认每问重搜：前端不带 `source_ids` 就是重新检索（「在当前来源里追问」= 照旧带 `source_ids`）。

响应（在原有 `{status,kind,markdown,sources,related,…}` 上新增；旧字段一个不少）：

```jsonc（带注释，示意）
{"mode": "toc",                      // direct = 直接答（调作答模型）；toc = 目录（不调作答模型，零 token）
 "turn_id": "t1015093012ab12cd",     // 每一答都有（链接 / GitHub 清单也有）；展开时带回来
 "source_ids": ["xhs-…", "…"],       // 这一答的来源 id（toc = 目录顺序；direct = sources 顺序）
 "toc": [{"n": 1, "id": "xhs-…", "title": "…", "author": "…", "date": "2026-09-24",
          "kinds": ["video"],          // video / attachment / pdf / image
          "hit": {"type": "comments", "label": "评论区", "text": "≤80 字命中原文", "loc": "c3", "speaker": "评论者：某某（不是作者）"}}],
 "toc_total": 14,                    // 真命中篇数（toc 最多列 20，其余在 related）
 "understanding": {"goal": "find|ask|survey", "core": "鱼露", "depth": "precise|detailed",
                   "filters": {"author": "…", "since": "YYYY-MM-DD", "until": "…", "kind": ["video"]},
                   "filters_applied": ["author"], "relations": [...], "constraints": {...}, "skill": "recipe", "skill_source": "explicit|model"},
 "skill": "recipe",                  // 这一答用的技能 id（general = 通用）
 "layout": "board",                  // 1020 可选：问题以 `/报告` 开头（问收藏页「回答 · 报告」开关选了报告，ask.REPORT_MARK；
                                     //   标记去掉后再检索 / 作答，直接答不出目录；技能不是陈列型的换 wiki）时出现。markdown 照
                                     //   skills.BOARD_FORMAT 写（# 报告名 / > 一句 / ## 先看这几个 / ## 类别 / - **名字** · 网址 —— 帖里：…；借鉴：…[来源N]），
                                     //   网址只留材料里逐字出现的（ask.unseen_links，其余换「看原帖」）；问收藏页解析成陈列卡，解析不出 2 条就照普通 Markdown
 "suggest": "可补：在小红书搜「寿司醋」…",  // 库里没真命中时才有（她 1015 拍板：只给一行建议，不自动搜）
 "expanded_from": "t…",              // 展开答才有：展开的是哪一答
 "mode_reason": "find-main | find-scatter | survey | ask | deep | precise | forced"}
```

- **chat 车最终字段（1015 协调对齐）**：请求也可平铺 `{"turn_id": "…", "expand_ids": ["…"]}`（等同 `expand`），可同时带 `source_ids`；
  响应读 `mode` / `toc` / `turn_id` / `source_ids` / `coverage_note`（一句覆盖说明，两种档位都有）/ `suggest`（目录档为空串）；
  `toc[]` 每条另有 `source_type`（= `hit.type`）、`kind`（主类型，= `kinds[0]`）、`line`（概要第一句 ≤60 字）。
- 技能隐藏：插件设置 `skills.hidden`（技能文件夹名数组）里的技能照列（`hidden: true`），但路由 / 选用时跳过；技能目录统一 `vault/_skills/`。
- `sources[]` 新增：`tier`（`primary` 主要依据 / `also` 找回时「也提到」的一行一篇 / `toc` 目录条目）、`hit_types`（这一条用到的
  来源类型：`body` 正文 · `ocr` 图片文字 · `comment_ocr` 评论区图片 · `comments` 评论区 · `transcript` 视频文字稿 ·
  `screen` 视频画面文字 · `attachments` 附件 · `notes` 批注 · `highlights` 划重点）、`date`；`excerpts[]` 的评论片段带
  `comment_labels`（楼号）和 `speakers`（「评论者：昵称（不是作者）」/「作者本人回复」）。目录条目另带 `hit`。
- 档位规则（她 1015 拍板「多 → 目录；适中 / 要精准 → 直接答」）：深读或 `depth=precise` → direct；`survey` 真命中 ≥5 → toc；
  `find` 主角篇（标题 / 标签 / 概要就是它）1–3 篇 → direct，否则散在 ≥4 篇 → toc；`ask` 真命中 ≥8 → toc。
  留来源重答（`source_ids`）、手动保留（`pin_ids`）、展开都不出目录。
  1017 阶段 1 改口径：`survey` 只在她明说要清单 / 目录（核心词里有「列出 / 清单 / 目录 / 盘点一下」）时才出目录，其余盘点题直接答。

### 问收藏响应 v2.1：判断＋导读、会话状态（2026-10-18）

请求新增（都可省略；`ask --request-stdin`、`serve`、`ask.answer(...)`、MCP `ask` 一样）：

```jsonc
{"question": "只看刚才第一篇，它怎么说的",
 "thread_id": "th10180930ab12cd",    // 上一轮返回的 turn.thread_id：追问带它，后端按这条线最近一轮继承来源 / 解析「第 N 篇」
 "parent_turn_id": "t1018093012ab12cd"}   // 本地页面：上一答的 turn_id（比 thread_id 更准；两个都没有 = 新话题）
```

- 本地页面（chat-view）每个助手轮记 `turnId` / `threadId`，接着这段问时把上一答的两个 id 带上；新话题 / 展开 / 重试不带。
  后端**不再按问题原文**在全局登记表里找上一轮（同一句话问两次会串，本地远程共用一张表）。
- MCP `ask` 另收 `context: {previous_question, source_ids}`（存不了状态的客户端）。都没带时，只有问句是追问（第 N 篇 / 刚才 / 其他 / 那 X 呢）
  才取**同一凭据** 15 分钟内的最后一轮，回答第一行写「（接着上一问「…」）」；绑不到又是指代型 → 不检索，回「找不到上一轮，告诉我是哪篇？」
  （`needs_context: true`）。指代解析（`ask_followup.resolve`）：第 N 篇 → 只用 `ordered_sources[N-1]`（`source_ids` 单篇模式）；
  第 N 个（地方 / 方案）→ `objects[N-1]` 对应的来源；其他 / 别的 → 排除上一轮的来源 id 和对象、去掉最窄限定（「中国旅行推荐」→「旅游推荐」）；
  那 X 呢 → 照常检索（switch）。响应另带 `followup: {bound: parent|thread|fallback|context, kind, parent_turn_id, question?}`。

响应新增（`mode=direct`）：

```jsonc
{"turn": {"turn_id": "t…", "thread_id": "th…", "parent_turn_id": null,
          "ordered_sources": [{"n": 1, "id": "xhs-…", "title": "…", "role": "A|S|M"}],   // 顺序 = 来源导读的顺序 =「第 N 篇」的编号依据
          "objects": [{"name": "Lucie Dream", "ns": [1]}],                          // 答案里出现的对象（表格第一列 / 加粗条目），按出现顺序
          "scope": {"topic": "…", "task": "synthesize", "must": [], "must_not": [], "excluded_ids": [], "pinned_ids": []}},
 "thread_id": "th…", "task": "find|howto|synthesize|survey|inspire|adapt|evaluate|browse|absence|portrait",
 "thought": "1 核心判断：…",            // 模型先写给自己看的 <想法> 块（不在 markdown 里；流式时也不显示；模型没写就没有这个键）
 "images": [{"n": 1, "image_no": 3, "asset": "_archive/…/image-003.webp"}],   // 回答里放的图（本地 markdown 里是 ![[…|360]]）
 "cached": false,                       // 撞到答案缓存（只记录，不再把上次结论注进提示词、不再挂「以前问过」那一行）
 "understanding": {"task": "…", "note": "研究笔记 100–200 字", "clues": ["她记得的线索"], "...": "旧字段照旧"},
 "checks": {"defense": {"hits": 0, "allowed": 0, "over": false}, "copy": {"ratio": 0.12, "limit": 0.25, "over": false},
            "per_source": {"max_run": 1, "flagged": false}, "guide": {"present": true, "lines": 4, "cited": 4, "missing": [], "bad_locations": []},
            "...": "1017 的 alignment / absence / speaker / leak / padding / uncited 照旧"}}
```

- `sources[]` 新增 `guide`：回答末尾「## 来源导读」里这篇那一行（`[来源N]《标题》— 贡献。必看 / 选看：看哪里`），界面可挂在来源卡下面。
- 远程 MCP（`ctx.local=False`）：结果剥本机绝对路径（`agent_md` / `markdown_path` / 附件只留文件名 / 不带 `delivery` / `history`），
  `![[…|360]]` 换成「（图：来源N 图M）」，图按 `images[].asset` 用 `image` 工具取。
- 轮次登记 `_archive/ask-turns.json` 每轮多记 `thread_id / parent_turn_id / who / ordered_sources / objects / scope / head`（回答开头 ≤300 字）。

### 技能（`link_brain/_skills/<id>/SKILL.md` 内置；`<vault>/_skills/<id>/SKILL.md` 用户，同 id 覆盖内置）

- 格式 = Anthropic Agent Skills：frontmatter `name`（小写英文 id）+ `description`（路由只看这一句）+ 可选 `lwa: {title, aliases, domains, depth_default}`；
  正文 = 作答时的写法要求（截 1500 字）。可选 `examples.txt`（一行一句路由示例）。
- 只读文字：导入（`python -m link_brain skills import <SKILL.md 或文件夹> [--overwrite]`）只拷 `SKILL.md` 和 `examples.txt`，
  别的文件列在 `skipped_files` 里不碰；正文里「忽略以上 / ignore previous」这类行在加载时删掉。坏文件跳过并登记 `SKIPPED.SKILL`。
- `python -m link_brain skills list` → `{status, skills: [{id, name, title, description, aliases, source: builtin|user, path, ok, error?, overrides?}], user_dir, builtin_dir}`；
  `skills show <id>` → `{status, skill: {…, body}}`。设置页技能页签读这两个。
- 选哪个：问句里点名（`/菜谱`、`用 wiki 技能`）> 扩词那次小模型顺带选的（只给它 id + description）> `general`。

## 2026-10-02 远程阅读（MCP）的配置与本机状态（第 6 批）

- 配置唯一来源：插件 `data.json` 的 `remote` 段（插件写、服务只读，按 mtime 热重载）。**口令和令牌不在这里**。

```json
{"remote": {"enabled": false, "domain": "https://read.example.com", "port": 18071, "folders": ["@xhs", "其他资料"]}}
```

  `domain` 是完整来源（https + 主机名，不带端口和路径），空 = 只认本机；`folders` 里 `@xhs` = 小红书收藏库
  （`Web/Xiaohongshu/**` + 每篇 `_archive/xiaohongshu/<id>/derived/agent.md`、`derived/attachments/*.md`、`notes.json`），
  其余是 vault 内的相对文件夹（`/` 分隔、不以 `.` 开头、不是 `_archive` / `_trash`）。
- 本机状态在 vault 外：`$LINK_BRAIN_HOME/remote/`（默认 `~/.link-brain/remote/`），不进 vault、不进仓库、不随手机同步。
  - `auth.json`：`{schema_version, passphrase: {salt, hash, algo:"scrypt", n, r, p, set_at} | null, clients: {<client_id>: {name, redirect_uris, created, token_at, last_used}}, access: {<sha256>: {client_id, expires}}, refresh: {<sha256>: {client_id, expires}}, personal: {<id>: {hash, label, created, last_used}}, revoked_all_at}`——令牌只存 sha256。
  - `status.json`：服务自报 `{pid, port, version, state: running|stopped|error, code, message, started_at, domain, folders, updated_at}`。
  - `access.log`：一行一条 `{ts, client, tool, path?, status: ok|denied|error, code?, n?}`，不记查询词和内容；超过 1 MB 轮转一份 `.log.1`。
  - `server.log`：服务自己的运行日志（1 MB × 3）。

## 2026-10-08 问收藏会话（`_archive/chat-session.json` 与 `_archive/chat-history/<id>.json`，批次 D · L2）

两者同一个形状（历史文件 = 某一段对话的快照）；只由问收藏页经插件写链串行写，手机 / 插件没启用时只读不写。旧文件没有的字段照读，第一次写盘时补上轮次 `id`。

```json
{
  "id": "m1abc2de",
  "startedAt": "2026-10-08T09:00:00+10:00",
  "private": false,
  "follow": "sources",
  "excluded": ["xhs-9"],
  "pinned": ["xhs-2"],
  "turns": [
    {"id": "m1abc3fg", "role": "user", "content": "番茄炒蛋放几个蛋", "mode": "scope", "scopeTitle": "番茄炒蛋", "sources": 1, "askedAt": "2026-10-08T09:00:05+10:00"},
    {"id": "m1abc4hi", "role": "assistant", "content": "三个 [来源1]", "q": "番茄炒蛋放几个蛋", "askedAt": "2026-10-08T09:00:05+10:00", "sources": [], "related": [], "removed": [], "added": [], "savedId": null},
    {"id": "m1abc5jk", "role": "user", "content": "要放糖吗", "mode": "follow", "sources": 3, "askedAt": "2026-10-08T09:01:00+10:00"},
    {"id": "m1abc6lm", "role": "assistant", "failed": true, "error": {"kind": "api", "code": "TRANSIENT.HTTP_429", "detail": "429"}, "content": "接口限流了，过一会儿再试", "q": "要放糖吗", "askedAt": "2026-10-08T09:01:00+10:00", "retry": {"sourceIds": ["xhs-1", "xhs-2", "xhs-3"]}, "mode": "follow", "sources": [], "related": []}
  ]
}
```

- 轮次 `id`：页面按它缓存每一轮的 DOM、把答完的回答插回自己那条问题后面；同一文件内唯一。
- 用户轮 `mode`：`ask`（照常检索）/ `follow`（绑上一轮留下的来源，`sources` = 条数）/ `reask`（按留下的重答）/ `scope`（问这篇，`scopeTitle` = 标题）/ `search`（旧版搜索轮）。
- 回答轮失败：`failed: true` + `error: {kind: config|api|crash|timeout, code, detail}`，`content` 是页面给她看的一句人话；`retry` 是「重试」原样再问要带的参数（`{sourceIds}` / `{fresh: true}` / `{}`）。停止的：`failed: true, stopped: true`，`content` 末尾一行「> 已停止生成。」。旧版失败轮没有 `error`，照原文显示。
- `removed`：这一轮被 × 的来源 key（`id || note || title`）；`added`：从「其他相关」加入主要依据的 id。会话级 `excluded` / `pinned` 跨轮生效。
- 历史目录 `_archive/chat-history/index.json`：`{"conversations": [{id, startedAt, updatedAt, title, turns}]}`，写前重读、按 id 合并。草稿不进文件（只在 `sessionStorage['lb:chat']`）。

## 2026-10-09 单篇快照 / 导出 / 连播（批次 D · L5）

### 对象目录 `history/`（可见 md 的快照）
- `_archive/<source>/<source_id>/history/visible-YYYYMMDD-HHMMSS[-n]-<reason>.txt`：整篇可见 md 的原文，原子写，每篇只留最近 20 份。
- `reason` 词表：`restore`（恢复前）/ `undo`（撤销前）/ `render`（重渲染发现块外内容，先存一份）/ `heal`（夜里自愈前）。
- 任何「整篇重写可见 md」的功能都先存快照。块外她手写的段落重渲染时一行一条搬进留言层（`id=moved-YYYYMMDDHHMMSS-n`，幂等）；机器碎片不搬，只在快照里留原样。

### `restore [<item_id>] [--path <收藏库相对路径>] [--undo [--snapshot NAME]] [--list] [--scan [--report]] [--dry-run] --json`
- 恢复：`{ok, code, message, item_id, path, snapshot, issues_before, kept}`；失败 `code=PERMANENT.NOTE_DAMAGED`，文件不动。
- `--list`：`{ok, item_id, path, snapshots:[{name, ts, reason, bytes}]}`（新的在前）。
- `--scan`：只读，`{ok, total, damaged, stray, results:[{item_id, path, issues, stray_human, stray_machine}]}`；`--report` 时坏的登记 `render.check` / `PERMANENT.NOTE_DAMAGED`，好了自动解除。
- 问题码（`issues`，固定顺序）：`FRONTMATTER_BROKEN / ITEM_ID_MISSING / CSSCLASSES_MISSING / CONTENT_MARKERS_MISSING / NOTE_BLOCK_MISSING / NOTE_BLOCK_SPLIT / COMMENTS_MARKERS_MISSING / ANNOTATE_BLOCK_MISSING`；插件 `noteDamage` 与它同口径（共用样本 `tests/fixtures/note_damage_cases.json`）。
- 夜里自愈默认关：环境变量 `LINK_BRAIN_AUTO_RESTORE=1` 才让 repair 自愈轮自动恢复（只动 24 小时没改过的文件）。

### `export-note <target> --pdf|--html|--zip [--no-video] [--no-pdf] [--font F | --stdin] --json`
- 落在收藏库根的 `收藏导出/`，重名加「（2）」，先写 `.part` 再改名。stderr 阶段行 `[export] 排版` / `[export] 打印 PDF` / `[export] 打包视频（85 MB）`。
- `--pdf`：和笔记页同一套 render 片段 + `link-brain.css` + `lb-print.css` 拼打印 HTML（`<base>` 指可见目录），系统 Edge / Chrome 无头打印（独立临时 profile，只开本地 file://）。
  `{ok, code, message:'已导出 PDF（6 页）', path, rel, pages, engine:'msedge'|'chrome'|'', fallback:''|'html', item_id, results}`；
  没浏览器 → `ok:true, fallback:'html'`，path 指 `.html`；打印失败 / 超时 → `ok:false, code:'TRANSIENT.STEP_TIMEOUT'`，网页版照样写出（当场告知，不进问题记录）。浏览器可用 `LINK_BRAIN_PDF_BROWSER` 指定。
- `--zip`：`<标题>_<作者>_<YYYYMMDD-HHMMSS>.zip`，包内一个同名文件夹：`索引.md`（有什么 / 缺什么）、`笔记页.pdf`（有浏览器才有）、`正文与识图.md`、`批注.md`、`留言.md`、`images/NN.<原扩展名>`、`comments/c<楼>-<n>.<ext>`、`video/video.mp4`（ZIP_STORED）、`attachments/<原名>` 与转出的 `.md`。不放 raw JSON（有 xsec_token）。
  `{ok, message:'已打包：12 张原图、1 个视频、2 个附件（86 MB）', path, rel, counts:{images, comment_images, comment_audio, video, attachments}, missing, bytes}`。

### `playlist --tag X [--order newest|oldest|shuffle] [--seed N] [--start ITEM] --json` / `playlist --tags --json`
- 纯读 `_archive/catalog-data.json` + 对象 manifest：只收 `kind=video` 且视频下载成功、文件在的；标签不分大小写、带不带 `#`、子标签（`健身/拉伸`）都算命中。
- `{ok, code, message, tag, order, seed, start_index, items:[{item_id, title, author, note, video, poster, duration_sec, width, height, bytes, date}], skipped:[{item_id, title, reason}], suggestions}`；路径都是收藏库相对。乱序不给 seed 时用当前毫秒并回传（可复现）。
- `--tags`：`{ok, tags:[{tag, count, playable}]}`，按能播的条数降序。退出码：0 有结果；1 目录还没建好；2 没命中（带 suggestions）。

## 2026-10-09 评论补齐（`comments --fill-pending`，1009 Owner：设置楼数内的楼中楼都要抓全）

- 缺口按**存下来的评论**现算（`link_brain/comment_fill.py` 的 `scope`）：设置「评论楼层」N（10–50；「全部」= 2000）→ 前 N 个一级评论里
  「原站显示的回复数 `sub_comment_count` > 存下的 `sub_comments` 条数」就是缺口；没有 `comment_load` 的老笔记（10-08 以前入库）照样算。
  读取组件判「展开到底、原站多显示」的 `count_mismatch` 和续读时报 `floors_not_found` 的楼（原帖里已找不到）不算缺口，页面照实标。
  存下的楼不到 N、原帖可能还有（`comments_complete` 不是 true、`comment_load.has_more` 不是 false、评论总数对不上）→ 按 N 楼重读一次。
- 续读一律并集合并：一级评论、每楼楼中楼按 id 取新旧并集（删掉的、这次没展开到的留着），原站显示数取较大的——调小楼数不删已抓的。
  续读只为评论开页：正文 / 图片 / 附件沿用上一版，不做附件网页探测；**没多拿到评论就不写新 RAW 版本**；写新版本时上一版下好的
  图 / 视频 / 语音直接引用旧版本文件（`manifest.media[].file` 可以是 `raw/v0001/assets/…`，`manifest.reused` = 引用了几个）。
- 对象级 `derived/comments-fill.json`（可变）：`attempts` 续读次数 · `last_at` 上次开页 · `last_mode` expand|floors · `last_missing` ·
  `no_progress` 连着没多拿到的次数 · `floors_done` 按这个楼数重读过、楼没变多 · `gone_floors[]` · `stuck` / `stuck_floors` / `stuck_at` /
  `stuck_reason`（连着 3 次没进展：不再自动续，问题记录 `comments.fill` + `PERMANENT.COMMENTS_INCOMPLETE`）· `done_at` · `history[]`（最近 8 次）·
  `legacy_released`（1011：以前因「not found in noteDetailMap」放弃的，补评论开跑时本地解开过一次的时刻，见 restricted.release_legacy_fill_stuck）。
- 对象级 `derived/restricted.json`（1011，可变；网页版要验证才给看的笔记，`link_brain/restricted.py`）：`restricted` 现在是不是标着 ·
  `since` / `last_at` / `count` · `via[]`（comments.fill / comments / attachments：哪一步撞见的）· `detail` · `title` ·
  `search {on: 日期, at, result: running|found|not_found|same_token|no_title|error, error?}`（用标题搜新口令；每篇每天最多一次，先记再搜）·
  `token` / `token_at`（搜到的 / 验证窗口里拿到的新口令，之后补评论 / 下附件优先用它）· `verify {at, result, text}`（上次「打开验证」的结论）·
  `verified_at`（她过了验证；补评论按它也隔 45 分钟再开这篇）· `recapture {queued_at, comments, attachments}` · `cleared_at` / `cleared_why`。
  标着的笔记：后台补评论（`survey().restricted`）、附件补下（结果 `status=restricted`，不进跨夜退避、不报「附件没下好」）、碰号的附件补查都跳过；
  问题记录 `note.restricted` + `PERMANENT.NOTE_RESTRICTED`（一篇一条）；卡片角标同码。`note-verify <item_id> [--wait]` →
  `{ok, code, message, item_id, mode: note|hold|unsupported, result: note_ok|note_not_seen|still_risk|not_logged_in|not_read|window_failed|opened, requeued?}`。
- `_archive/comments-fill-status.json`（后台补跑 / 夜跑这一步写，插件状态栏读）：`state` running|waiting|paused|done|deferred|stopped ·
  `pid` · `background` · `floors` · `total` / `done` / `left`（篇）· `missing`（条）· `stuck` · `current {item_id,title}` ·
  `wait_code`（CAPTCHA_REQUIRED / NOT_LOGGED_IN / NIGHTLY / YIELD / ACCOUNT_BUSY / COOLING / CAPTCHA_COOLDOWN（1011：撞验证后冷却等自查）…）· `message`（一句人话）· `updated_at`（等待时每分钟刷新）。
  进程没了而状态还停在 running/waiting/paused：Python（`comments --fill-status`）改报 stopped。
- `comments --fill-status` → `{ok, code, message, floors, pending, ready, cooling, stuck, missing, running, status}`（本地读，不碰号）；
  `comments --fill-pending --detach` → 拉起 `--until-done` 后台补跑（单实例，已在跑就 `already`）。

## 2026-10-11（晚）同步进度的数 / 同步记录的被中断与自愈

- **收藏同步进度的数只有一份口径**：`link_brain/fav_counts.py` 的 `counts()` → `{favorites_total, archived, remaining, library_total, basis}`。
  总数 = `_archive/fav-list.json` 条数（没有名单退到 sync-status.json 的 `last_favorites`，`basis:"baseline"`）；已入库 = 名单里在库里或回收站里的；
  还差 = 总数 − 已入库；库里一共 = 对象数（含分享 / 导入单篇、后来取消收藏的）。进度条（`live.archived / favorites_total / remaining`）、
  `synclog list` 的 `backlog`（多 `remaining`，`message` =「收藏 T 篇，已入库 A 篇，还差 R 篇，预计还要 D 天同步完」）、`setup backfill`
  （`deferred` = `remaining` = 还差；上次同步自记的 deferred 改放 `last_sync_deferred`；`deferred_from: favorites_list|total_minus_archived`）都从它取。
  界面统一说「收藏已入库 A/T（还差 R 篇）」；目录页标题下的「筛出 n 篇（共 N）」里 N 是目录 items 数（= 库里一共），悬停写明两者区别。
- `_archive/sync-status.json` running 时多 `trigger`（`synclog.default_trigger()`：manual / nightly / schedule / cli / retry），`problems summary` 的 sync 段同名字段；
  插件「这里停不了」照它说（命令行 / 夜跑 / 定时…）。`LINK_BRAIN_UNATTENDED` 非空时按时段算 nightly / schedule，不再因为控制台 isatty 记成 cli。
- `_archive/sync-log.jsonl` 每行多：`pid`（开这一行的进程）、`fetch_pid` / `fetch_done` / `fetch_exit`（收藏同步的抓取进程；正常收尾才标 done）。
  收藏同步每篇当场 flush（不再攒到命令结束）。`synclog list` 读出来的行可能多：`interrupted`（抓取进程没了又没收尾；或下一条）、`recovered`
  （老记录一条没写进去、按 index.db `first_archived_at` 落在 [开始, 下一趟开始) 的收藏补回 `new` / `items`）；`errors[]` 多 `resolved` / `resolved_at` / `label`
  （夜跑离线步骤——重写目录页 / 补转写视频 / 语义索引 / 补识图概要 / 识图补跑 / 精细识图——在问题记录里那一步已全部解决、且解决晚于这条报错），
  `error` 只看没好的。离线命令成功收尾（`catalog`、`videos --all --transcribe`、`embed`、`enrich --pending`、`vision --upgrade|--refine`）时
  `synclog.heal_after_success` 解决问题记录里对应的 `nightly.<步骤>`。

## 2026-10-11 收藏名单 / 口令 / 夜里撞验证的状态

- `_archive/fav-list.json`（`favorites.py`）：上次**全量**读到的收藏名单，最新在前 —— `{schema_version:1, full_at, at, items:[{note_id, xsec_token, url, title?, type?, author?, author_id?}], full_next?}`。
  全量读全（不是一截、不可疑）才整份换（`full_at` = 那一刻）；增量读 / 一截只把读到的那段合进最前面（`at` 变、`full_at` 不动）。
  增量那晚的待抓清单 = 读到的最新一段 + 名单里其余的（积压从这里接着补）。`full_next` = 按名单（旧口令）抓连着失败，下次读收藏读全量。
- `_archive/fav-tokens.json`（`attachments.py`）：`{schema_version:1, at, full_at, tokens:{note_id:{token, at}}}`；全量整份换，增量只合并读到的那段（各条自己的 `at` 算新不新，7 天内有效）。
- `~/.link-brain/night-captcha.json`（`night_captcha.py`，`LINK_BRAIN_HOME` 可改）：`{nights:{"YYYY-MM-DD":{incidents, first_at, last_at, probe_at, probe_result, result: recovered|unrecovered|not_logged_in, recovered_at?, why?, escalated?}}}`，
  「夜跑日」= 当地时间往前推 3 小时的日期，只留最近 14 晚。
- 读取组件 `<XHS_PROFILE_DIR>/risk-hold.json` 多两个键：`auto_probe_at`（冷却后自查过的时刻；同一次熔断一晚一次）、`auto_probe_result`（没解除时的结论）；
  `/login/session` 多 `auto_probe: {result, at, hold_since}`。

## 2026-10-10 索引树（库根 `索引.md` → `_archive/index-data.json`）与节点 wiki

**唯一真相 = 库根一个 `索引.md`**（路径在插件设置 `indexFile` 里可改，库根相对、必须 `.md`、不许进 `_` / `.` 开头的目录）。
解析与归类只在 `link_brain/indextree.py`；插件和 MCP 只读结果。

- 写法：一行一个节点；缩进 = 下一级（Tab 按 4 列算、空格按 1 列、全角空格按 2 列，按相对缩进判层级，可混用）；行首 `- ` `* ` `+ ` `1. ` `1、` 可有可无；
  `名字：标签1, 标签2`（`：` `:` 都认；标签之间 `,` `，` `、` `;` 或空格）= 绑标签；没有冒号的 `A, B, C`（`,` `，` `、`）= 一行几个同级节点；
  行里任意位置的 `[wiki]`（`［ wiki ］` `【WIKI】` 也认）= 给这个节点做 wiki（一行几个节点时这一行都算）。
  忽略：frontmatter、`%% … %%`（没闭合的到文件尾）、`<!-- … -->`、标题行（`# `）、分隔线、空行。名字里的 `[[…]]`、`**…**`、开头的 `#` 去掉。
- 容错进 `warnings`（不报错）：同一父节点下重名 → 合并（标签并集；只写名字的那份把名字留作标签）；冒号前没名字 → 用第一个标签当名字；
  一行几个节点、下面又有缩进的 → 算在最后一个下面；`[wiki]` 前没名字 → 跳过。
- 节点路径 = 各级名字用 `/` 连（名字里本来的 `/` 换成 `∕`）；查找时分隔符 `/ ／ > › »` 都认、大小写 / 全半角不敏感、唯一的名字也行。
- 归类：笔记标签（frontmatter `tags`，不含原帖话题 hashtags）和节点标签都按 `docs/tag-vocab.yaml` 别名归一 + NFKC + casefold 后**相等**才算；
  笔记的子标签 `美食/菜谱` 也算 `美食`；只写名字的节点 = 名字当标签 + 标题里出现这个名字（大小写 / 全半角不敏感）。
  一篇可挂多个节点；父节点 = 自己命中 ∪ 子孙命中；哪个都没命中 = 未归类。
- 第一次没有 `索引.md`：按 `catalog.effective_big_cats()`（设置「分类」/ 内置 BIG_CATS）迁移——每类一行，后面是库里含那些关键词的标签
  （出现 ≥2 次的全列 + 只出现一次的挑最少几个保证现有每篇都还在）；第一级 = 今天目录页那排分类，每篇的归属和今天一样（别名归一多归进去的除外）。
  之后（有文本 AI、库 ≥30 篇、还没有草稿）后台起草一版（`index draft --auto`）。文件被删了下次重算再迁移一次并在 warnings 里说。

```jsonc
// _archive/index-data.json（indextree.build 原子写；锁 index-build；catalog build 每次 force 重算，插件监听 索引.md 保存后 `index build`）
{"version": 1, "code_version": "1010.1", "generated_at": "…", "file": "索引.md", "draft_file": "索引.草稿.md",
 "source_hash": "sha256:…", "vocab_hash": "sha256:…", "catalog_built_at": "…（= catalog-data.json 的 built_at）",
 "total": 601, "classified": 444, "roots": ["美食", "旅游"], "cats_order": ["美食", "旅游", "未归类"],
 "nodes": [{"path": "美食/菜谱", "name": "菜谱", "parent": "美食", "depth": 2, "line": 6, "tags": ["红烧肉"], "explicit": true,
            "wiki": false, "count": 12, "self_count": 9, "items": ["xhs-…"], "children": ["美食/菜谱/红烧肉"]}],   // 先序；items 按目录顺序（新→旧）
 "unclassified": {"count": 157, "items": ["xhs-…"]},
 "warnings": [{"line": 12, "text": "第 12 行「菜谱」在「美食」下面重复了（第 5 行已有），合并成一个"}],   // line=0 是整份文件的提示
 "draft": null | {"file": "索引.草稿.md", "exists": true, "hash": "…", "generated_at": "…", "mode": "ai|tags", "roots": […], "nodes": 23,
                  "classified": 510, "unclassified": 91, "total": 601, "warnings": 0, "wiki_suggest": ["旅游", "美食/菜谱"]},
 "wiki": {"旅游": {"file": "wiki/旅游.md", "exists": true, "marked": true, "in_index": true, "based": 12, "new_since": 2, "generated_at": "…"}},
 "migrated_at": "…"}   // 第一次迁移的时间；build() 的返回值另有 migrated={at, again}，只在刚迁移那一次、不落盘
```

- `catalog-data.json`：`cats_order` / `items[].cats` 改由索引第一级给（没归进任何节点 = `["未归类"]`）；顶层多 `index: {file, generated_at, roots, unclassified, migrated} | null`
  （null = 索引没算出来，照旧按关键词分）。`cats`（关键词表）照留给旧的「管理分类」。
- 只在这一处写回 `索引.md`：`index use-draft`（草稿去掉 `%% AI 起草` 那一行后整份换进去）和 `index apply`（补标签：冒号行接在后面、沿用这一行的逗号写法；
  只写了名字的改成 `名字：名字, 新标签`；一行几个节点的拆出单独一行；新节点插在父节点整棵子树最后一行后面，缩进 / 行首符号照抄兄弟或父节点；
  换行风格 CRLF / LF 原样）。都是原子写，写前把原文存进 `_archive/index-history/索引-YYYYMMDD-HHMMSS[-n]-<reason>.txt`（reason：use-draft / suggest / draft-old / draft-used；留最近 30 份）。
- `_archive/index-suggestions.json`：`{generated_at, source_hash, mode: ai|tags|none, unclassified, suggestions: [{id, action: add_tags|new_node, path（目标节点 / 新节点的父节点，第一级为空）,
  name, tags, why, from: ai|tags, gain（在副本上真算的「未归类少几篇」，只列 >0 的）, count_after, examples: [标题]}]}`；`apply` 按 id 取，用过的删掉。
- `_archive/index-state.json`：`{created_at, migrated_at, draft: {generated_at, mode, wiki_suggest, model, usage}, draft_used_at}`。

CLI（stdout 最后一行 JSON，`read.outcome` 形状；退出码 0 成功 / 1 失败 / 2 参数不对或没东西可做）：
`index build [--force]` → `{total, classified, unclassified, roots, warnings, file, migrated, unchanged, draft}` ·
`index show [--node P | --unclassified]` · `index draft [--no-ai]` → `{file, mode, roots, stats, wiki_suggest, model, usage, ai_error}` ·
`index use-draft` → `{backup, roots, unclassified}` · `index suggest [--no-ai] [--limit N]` → 上面那份文件的内容 ·
`index apply --id X [--id Y]` → `{results: [{id, status: ok|failed|missing, error}], unclassified}`。
文本 AI 取法（起草 / 建议 / wiki 共用 `indextree.text_ai()`）：问收藏正在用的文本 AI（叠上选中的模型）；没有能用的 key 时退到归档摘要模型；本机接口不要 key。

**节点 wiki**（`link_brain/wiki.py`，方法 `docs/deep-report.md`）：`wiki build "<节点路径>" [--estimate]` 只读这个节点收的笔记的机读版（每篇 ≤8000 字，按 24000 字一批抽对象，
3 路并发，再一次定稿分类排序），写 `vault/wiki/<各级名字>.md`（名字里 Windows 不认的字符换 `_`），旧版先备份进 `_archive/wiki-history/`；`--estimate` 不调模型，
给 `{items, calls, tokens_in, tokens_out, model, yuan, message}`。没有能用的文本 AI → `code=SKIPPED.NOT_CONFIGURED`、退出码 2、message 指向 MCP（guide / index / read）。
页面：frontmatter `lb-wiki: "<路径>"`、`cssclasses: [lb-wiki]`；标题下一行 `> 基于 N 篇，生成于 YYYY-MM-DD HH:MM；之后新增 M 篇（点「更新」重新生成）` /
`；之后没有新增`——M = 这个节点现在的篇目减去生成时的篇目，`indextree.build` 每次重算时只改这一行。
链接只收原帖里逐字出现过的（「帖内给出」），其余写「无链接，看原帖」；对象的出处必须在这批篇目里；「出自」写 `[[笔记文件名|标题]]（item_id）`。
`_archive/wiki-meta.json`：`{"pages": {"<节点路径>": {file, based_ids, generated_at, model, usage, objects}}}`。
`wiki list` → `{pages: [{path, file, exists, marked, based, new_since, generated_at}]}` · `wiki show "<路径>"` → `{page, text}`。

MCP（`mcp_tools.py`，本机 stdio 与远程同一份，只读）：`index`（无参数 = 整棵树 `{nodes: [{path, name, depth, count, wiki?, wiki_page?}], total, classified, unclassified, warnings?}`；
`path` = 节点 → `{path, tags, wiki, children: [{path, count}], count, offset, next_offset, items: [{id, title, date, summary}]}`；`path='unclassified'` / `未归类` = 未归类）·
`wiki`（无参数 = `pages`；`path` = 全文分页 `{path, exists, file, based, new_since, generated_at, total_chars, offset, next_offset, text}`）·
`guide`（`docs/deep-report.md` 全文）。`index` / `wiki` 要收藏库开放给这个客户端（`@xhs`），`guide` 不限。


## 2026-10-11 索引树按内容归类（`link_brain/indexai.py`）+ 解析器认她的真写法

**写法加的几条**（`indextree.parse`，旧写法全部照旧）：
- 括号（`（）` `()` `【】` `［］`，`【wiki】` 除外）里的话 = 节点的**说明**（`desc`），给 AI 归类看、页面上显示；不参与「、」「，」拆节点，里面的冒号也不算写法。
- 整行只有括号（`（其他主题）`）或 `...` `…` `等` = **占位**：上一级节点 `open=true`（允许 AI 在它下面按内容建子类，第 3 级的不算）。
- **说明行**不是节点，进 `comments: [{line, text}]`：冒号前是「需求 / 说明 / 备注 / 注 / 注意 / 要求 / 规则 / 写法 / 提示 / ps / note / todo…」；
  有句号 / 问号 / 叹号；超过 40 个字；冒号后面（或没冒号的整行按 `,，、;；` 拆开）有一段 ≥5 字、含中文、带「可以 / 最多 / 不属于 / 放这 / 指向 / 如果 / 需要…」这类词；
  树写完以后（主树 = 节点行最多的那一块，按空行分块）比第一级还靠左的零散行。
- **最多 3 级**：第 4 级往下的名字（和标签）并进第 3 级当关键词（`hints`，规则匹配和 AI 都用），warnings 里说一句。
- 新建第一级节点插在**最后一个大类整棵子树的后面**（不再追加到文件尾，免得插到她末尾的说明下面）。

**归类三层**（`classify(parsed, items, ai=, overrides=)`，后面的压过前面的）：①她写了标签的节点按标签收（永远算）；只写名字的按名字找标签 / 标题——
**只对还没有 AI 结果的篇**；②AI 按内容（`index-ai.json` 的缓存）；③她手动改的（`index-overrides.json`）。

```jsonc
// _archive/index-ai.json（indexai 写；锁 index-ai）
{"version": 2, "model": "deepseek-v4-flash",
 "known": {"美食/菜谱": "<节点签名：路径 + 说明 + hints + 标签 + open>"},          // 所有已判过的篇都对这些节点判过
 "items": {"xhs-…": {"sig": "<标题 + 标签 + 概要的签名>", "paths": ["美食/菜谱"], "at": "…"}},   // paths 空 = 放不进；tries / gave_up = 模型连漏两次
 "splits": {"游戏/游戏": {"sig": "…", "n": 26, "groups": [{"name": "空洞骑士", "items": ["xhs-…"]}], "at": "…"}},  // 直接挂着 ≥6 篇的节点细分
 "leftover": {"hash": "<未归类集合>", "groups": [{"name": "澳洲超市好物", "parent": "", "items": ["xhs-…"]}], "at": "…"},
 "spent": {"calls": 46, "tokens_in": 131022, "tokens_out": 18208, "yuan": 0.41}, "runs": [/* 最近 20 次 */],
 "blocked": {"why": "…超过自动上限 ¥3"} | 无, "last_error": {"code", "error", "at"} | 无}
// _archive/index-overrides.json（她手动改的；锁 index-overrides）
{"version": 1, "items": {"xhs-…": {"only": ["AI/ai功能/游戏"]} | {"add": [...], "remove": [...]}},
 "keep_empty": ["工程/工程管理"], "dismissed": ["<建议 id>"], "history": [{"id": "<撤销号>", "prev": {...}}]}
```
- 不重复花钱：笔记签名没变、节点签名没变就不再问。新笔记 / 内容变了的整篇重判；新加 / 改了说明的节点只问「这批笔记里哪些属于它」（60 篇一批）；
  删掉的节点从缓存里拿掉，拿光了的那篇整篇重判；节点直接挂的篇数比上次细分时多了 3 篇以上才重新细分；未归类集合变了才重新分组。
- 细分（`split`）：第 1–2 级、名字不是「综合 / 其他」的节点，直接挂着 ≥6 篇 → 问有没有 ≥3 篇的具体主题；`open` 的节点 → 直接挂成 **virtual** 子类
  （最多 6 个，节点行 `virtual: true, proposal: <id>, line: 0`，篇目从父节点挪进来；她「保留」才写进 索引.md），别的节点 →「建议新增」。
- 放不进的（`leftover`）：一起分组起名、写清放在树的哪里（位置对不上树就放第一级）。
- 模型输出不可信：路径必须对得上树里的节点（整条路径 / 唯一末级名字），每篇最多 3 个，名字清洗，层级不超过 3，「其他 / 综合」不建。
- 用哪个模型（`indexai.classifier_ai`）：问收藏的文本 AI，没 key 再用归档摘要模型（10-11 真库对照：千问 flash 关思考常把菜谱归进「家居好物」，质量第一）。

`index-data.json` 加的键：
```jsonc
{"nodes": [{"…": "…", "desc": "不属于ai记忆、人格的放这里", "hints": ["血源", "黑魂"], "open": true, "virtual": true, "proposal": "<id>", "keep_empty": true}],
 "assign": {"xhs-…": ["美食/菜谱"]},                     // 每篇直接在哪些节点（不含祖先），页面「移到…」用
 "proposals": [{"id", "name", "parent": "游戏/游戏" | "", "kind": "split|leftover", "count", "loose": 0, "items": [...], "examples": [标题]}],
 "classify": {"ai_ok", "why", "model", "done", "total", "pending": 3, "work": 3, "yuan": 0.02, "spent": {...}, "last_run": {...},
              "running": {"at", "done", "total", "phase"} | 无, "blocked": {...} | 无, "error": {...} | 无},
 "comments": [{"line": 9, "text": "需求：最多3级分类…"}], "ai_stamp": "…", "overrides": 2}
```
- 后台：`index build`（插件监听 索引.md 保存）和 `catalog build` 发现 `classify.work > 0`、配了模型、没在跑、估价 ≤ ¥3 → 拉起 `index classify --auto`
  （单实例，等 索引.md 20 秒没再保存才开跑，跑的时候每 4 批重算一次 index-data 让页面看到进度）。超过上限 = 不跑，页面显示原因和「按内容归类」按钮。

CLI（`read.outcome` 形状；退出码 0 成功 / 1 失败 / 2 参数不对或没配模型）：
`index classify [--auto] [--estimate] [--progress] [--max-yuan X]` → `{full, nodes, splits, leftover, unclassified, usage: {model, calls, tokens_in, tokens_out, yuan}}`
（`--estimate` 不调模型 → `{calls, tokens_in, tokens_out, yuan, pending, work, full, changed, splits, model, ai_ok, why}`；`--progress` stdout 一行一个 `{"type":"progress","done","total","text"}`）·
`index assign --op move|add|remove|reset|undo --path P --item X [--item Y]` → `{undo, unclassified}`（move = 只放这一类；undo 时 `--path` 是撤销号）·
`index accept --id <建议 / virtual 的 id>` → `{path, line, unclassified}`（写进 索引.md：原子写、备份 reason `accept`；这几篇直接归进新节点，新节点记成已判过，不再花钱）·
`index empty --path P --remove|--keep`（删只删 0 篇的节点那几行，备份 reason `remove`）· `index dismiss --id X`。

## 2026-10-11（二）细分标签（标签属于帖子）与原地更新

她定（看过 Obsidian 之后）：**标签属于帖子**——一篇有哪些标签是事实；**树的节点只来自 `索引.md`**（加上她点过「加进索引」的建议），最多 3 级，
只是把标签排成几级、从不改哪篇有哪个标签。10-11 上午那版「她写了 `...` 的节点下 AI 直接建子类（virtual）」撤掉；写了 `...` 的节点不再做「建议新增」细分。
数据结构按「以后树的节点 = 一个标签查询」留好：每篇的标签全库一份，节点那一行只是查询结果。

```jsonc
// _archive/post-tags.json（link_brain/posttags.py；锁 post-tags）
{"version": 1,
 "vocab": {"空气炸锅": {"aliases": ["空气炸锅菜"]}},                    // 全库词表：规范名 + 别名（同义的并成一个）
 "posts": {"xhs-…": {"sig": "<标题 + 标签 + 概要的签名>", "ai": ["空气炸锅", "牛排"], "human_add": ["东北菜"], "human_remove": ["快手菜"],
                     "at": "…", "model": "qwen3.7-flash" | "tags"}},
 "merged_names": [...]}                                                // 已经和词表对过同义的名字（只给新名字花钱）
// 一篇最后的标签 = ai + human_add − human_remove（她的永远赢）
// _archive/post-tags-history.jsonl：一行一次改动，只追加——{"id", "ts", "who": "ai|human", "item", "before": [...], "after": [...], "op"?: "add|remove|merge|restore", "tag"?, "from"?}
// index-data.json：nodes[].facets = 这个节点的帖子身上出现的标签 [{"name", "count", "items"}]（≥2 篇、篇多的前 12 个，不列和节点 / 子类 / 第 4 级关键词同名的）；
//                  item_tags = {"xhs-…": [最后的标签]}（卡片小字、「归类…」打勾用）
```
- 打标签：只看标题 + 自带标签 + 概要（不读全文），一篇 3–6 个、宽一点打；40 篇一批，附全库篇数多的 300 个已有标签让它复用写法；
  新收的 / 内容变了的才打（入库后的后台归类顺手就打了）；模型漏掉的那篇先用它自带的标签，不反复花钱。用**归档摘要模型**（便宜），没 key 用文本 AI，都没有 = 自带标签。
- 同义合并：每次打完，把新名字和篇数多的老名字一起给**文本 AI**（更稳）看，只并完全同义的；程序再核一道（得有共同汉字或 3 个以上相同字母），
  一组最多并 5 个；`docs/tag-vocab.yaml` 的别名也算。帖子上的旧名字跟着换成规范名，每篇记一行 `op=merge`。
- 她手动：`index facet --item X [--item Y] --path <节点，可空> --op add|remove --name <标签>` = 改这几篇的标签（`who=human`）→ `{undo: "t:<历史 id>"}`；
  撤销 = `index assign --op undo --path t:<id>`；任何一行历史都能按 `posttags.restore(<id>)` 恢复成那一步之前（恢复本身也记一行）。
- 估价 / 后台拉起同归类（`classify.work` 含要打标签的篇数，`tag_pending`）；用量里 `facet_usage` 单列打标签那个模型。

页面（目录页「索引」）：选中节点时网格上面一行「细分」chips（数字 = 和已选的同时有的篇数），多选 = 同时有（越选越窄），「清除」回到这一类全部；
卡片上一行淡字 = 这篇帖子的标签（这一行里有的排前面）；「归类…」菜单里列这一类那一行的标签 + 这几篇自己的标签（打勾 = 都有，点一下加 / 去掉）+「加一个标签…」。
**原地更新**（她：按 AI 建议刷新目录会闪一下）：`index-data.json` 内容没变（同一次改动的第二个通知）什么都不做；选中这一类的篇目和已选细分标签没变 →
结果集的键不变，网格不重摆；变了 → 列复用、卡片只在位置不对时挪（不再整批摘下再挂回）；树的形状没变只改数字（行元素不换、左栏滚动不动），
形状变了重画也还原左栏滚动；上面一行按内容变了才重画。

## 2026-10-16 用量账本 `vault/_archive/usage/YYYY-MM.jsonl`

append-only，一次模型接口调用一行（`link_brain/usage.py`，CONVENTIONS §4.9）。不存金额、key、提问或回答内容。

```json
{"ts": "2026-10-16T15:02:11+11:00", "f": "ask", "p": "deepseek", "m": "deepseek-flash", "in": 5210, "out": 380, "ok": true, "item": "可选：这篇的 id", "sec": "可选：语音秒数"}
```

- `f` 功能：vision 识图 · refine 精细识图 · summary 概要 · ask 问收藏 · expand 扩词 · embed 向量 · asr 语音转写 · rerank 精排 · other 索引 / wiki 整理。
- `p` 提供商：deepseek / aliyun / openai / google / cli（本机命令行，不花钱）/ 其他接口的域名。
- `link_brain usage [--balance]` 输出汇总（today / 7d / 30d × 功能 / 提供商，本月按提供商，近 30 天每日）、`links`（各家控制台网址）、`keys`（ai-health 里还开着的 key 失效 / 欠费），带 `--balance` 再加 `balances`。

