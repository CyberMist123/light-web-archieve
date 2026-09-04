"""Obsidian human view + agent view renderer.

Human view is a responsive Xiaohongshu-like detail page. RAW/agent/index are unchanged.
Rerender replaces only the managed content layer and preserves the comments layer.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import index as index_mod, storage
from . import attachments as attachments_mod
from . import llm as llm_mod
from . import vision as vision_mod

COMMENTS_START = "<!-- link-brain:comments:start -->"
COMMENTS_END = "<!-- link-brain:comments:end -->"
CONTENT_START = "<!-- link-brain:content:start -->"
CONTENT_END = "<!-- link-brain:content:end -->"

WINDOWS_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TOPIC_TOKEN_RE = re.compile(r"#([^#\[\]]{1,30})\[话题\]#")
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_TITLE_LEN = 60
PREVIEW_UNSUPPORTED_SUFFIXES = {".avif", ".heic"}
ACTOR_LABELS = {"human": "人", "gpt": "gpt", "fable": "fable"}


def sanitize_title(title: str) -> str:
    cleaned = WINDOWS_ILLEGAL_RE.sub("_", title or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip() or "untitled"
    cleaned = cleaned[:MAX_TITLE_LEN].rstrip(". ") or "untitled"
    return f"{cleaned}_" if cleaned.upper() in RESERVED_NAMES else cleaned


def visible_filename(title: str, note_id: str | None = None) -> str:
    """可见笔记的文件名。

    Owner 2026-09-04：文件名里那截 `__080119fe` 别写，就要干净的标题。
    `note_id` 只在**撞名**时才拿来当后缀（见 `resolve_visible_path`），保证不会覆盖别人的文件。
    """
    stem = sanitize_title(title)
    return f"{stem}__{note_id[-8:]}.md" if note_id else f"{stem}.md"


def owner_item_id(path: Path) -> str | None:
    """一个已存在的可见 md 属于哪个对象；Owner 手写的老文件没有这个键，返回 None。"""
    try:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    block = fm.get("link_brain")
    return block.get("item_id") if isinstance(block, dict) else None


def resolve_visible_path(visible_dir: Path, title: str, source_id: str, item_id: str) -> Path:
    """干净标题优先；那个名字已经被**别的**笔记（或 Owner 手写的老文件）占了才退回带 id8 后缀。"""
    clean = visible_dir / visible_filename(title)
    if not clean.exists() or owner_item_id(clean) == item_id:
        return clean
    return visible_dir / visible_filename(title, source_id)


def _clean_links_in_text(text: str, links: list[dict[str, Any]]) -> str:
    if not text:
        return text
    for link in links or []:
        url = link.get("url")
        if url and url in text:
            text = text.replace(url, f"[{link.get('text') or url}]({url})")
    return text


def _first_n_chars(text: str, n: int) -> str:
    return (text or "").strip()[:n]


def _safe(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _date(value: Any) -> str:
    return str(value or "")[:10]


def _body_html(text: str) -> str:
    text = TOPIC_TOKEN_RE.sub("", text or "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return '<p class="lb-empty">（无正文）</p>'
    return "".join(
        f"<p>{_safe(p).replace(chr(10), '<br>')}</p>"
        for p in re.split(r"\n\s*\n", text)
        if p.strip()
    )


def _tag_html(tags: list[str]) -> str:
    chips = "".join(f'<span class="lb-tag">#{_safe(x)}</span>' for x in tags or [] if x)
    return f'<div class="lb-tags">{chips}</div>' if chips else ""


def attachment_label(att: dict[str, Any]) -> str:
    """附件的一行人话：名字 + 页数 + 拿没拿到字节。"""
    name = att.get("name") or att.get("hint") or "笔记附件"
    bits = []
    if att.get("page_num"):
        bits.append(f"{att['page_num']} 页")
    status = att.get("status")
    if status == "downloaded":
        bits.append("已存本地")
    elif status == "metadata_only":
        bits.append("未下载（小红书要登录才给文件）")
    else:
        bits.append("拿不到")
    return f"{name}（{' · '.join(bits)}）"


def _attachments_md(attachments: list[dict[str, Any]], object_rel: str) -> list[str]:
    """附件卡片：**Markdown callout，放在 HTML 块外面**，样式靠 CSS 还原成原来那张小卡片。

    2026-09-04 Owner 报的回归：附件字节下下来之后点不开了。原因是 `<a href="../../_archive/…">`
    ——Obsidian 把裸 HTML 里的 href 一律当外部 URL，本地相对路径打不开（之前指小红书网页
    是 http 链接，所以能点）。跟 Lot 3b 第 2 条「原图链接放 HTML 块外面」同一个坑。
    所以链接必须是 Obsidian 自己的：本地文件 `[[vault相对路径|说明]]`，只有元数据的指原站。

    用 callout 是为了还能有边框卡片的样子（和留言层同一套路），CSS 见
    `assets/link-brain.css` 的 `data-callout="link-brain-file"`；不放 📎 字符，图标交给 CSS。
    """
    if not attachments:
        return []
    rows = []
    for att in attachments:
        label = attachment_label(att).replace("[", "（").replace("]", "）").replace("|", "·")
        local = att.get("file")
        if local:
            target = f"{object_rel}/{local}"
            # wikilink 里出现这些字符会被当成别名/块引用分隔符，退回纯文本免得链接歪掉
            if any(ch in target for ch in "[]|#^"):
                rows.append(f"> {label} — `{target}`")
            else:
                row = f"> [[{target}|{label}]]"
                # PDF 转出来的全文（pdf2md）在的话给个入口，人和 AI 都能直接读
                doc_id = att.get("doc_id")
                text_rel = f"{object_rel}/derived/attachments/{doc_id}.md" if doc_id else None
                if text_rel and (storage.vault_root() / text_rel).exists():
                    row += f" · [[{text_rel}|全文]]"
                rows.append(row)
            continue
        url = att.get("url")
        rows.append(f"> [{label}]({url})" if url else f"> {label}")
    return rows


def _engagement_html(note: dict[str, Any]) -> str:
    """Human view keeps only like/collect counts; comment count is visual noise here."""
    e = note.get("engagement") or {}
    bits = []
    for key, label in (("liked", "♡"), ("collected", "☆")):
        value = e.get(key)
        if value not in (None, "", 0, "0"):
            bits.append(f"<span>{label} {_safe(value)}</span>")
    return '<div class="lb-engagement">' + "".join(bits) + "</div>" if bits else ""


def _img_srcs(object_rel: str, file_rel: str) -> tuple[str, str]:
    raw = f"{object_rel}/{file_rel}"
    if Path(file_rel).suffix.lower() in PREVIEW_UNSUPPORTED_SUFFIXES:
        preview = f"{object_rel}/derived/previews/{Path(file_rel).stem}.png"
        return preview, raw
    return raw, raw


def _img_from_manifest(object_rel: str, file_rel: str) -> str:
    src, raw = _img_srcs(object_rel, file_rel)
    return f"![[{src}]]" if src == raw else f"![[{src}]] （原图：[[{raw}]]）"


def _comment_image_files(comment_id: str | None, manifest: dict[str, Any]) -> list[str]:
    if not comment_id:
        return []
    return [
        m["file"] for m in manifest.get("media", [])
        if m.get("role") == "comment_image"
        and m.get("comment_id") == comment_id
        and m.get("file")
    ]


def _comment_html(
    comment: dict[str, Any],
    object_rel: str,
    manifest: dict[str, Any],
    *,
    nested: bool = False,
) -> str:
    """Human comment row: author + text only; no date/location/overall count."""
    author = (comment.get("author") or {}).get("nickname") or "匿名"
    text = _safe(comment.get("text") or "")
    target = comment.get("target_nickname")
    if target:
        text = f'<span class="lb-reply-target">回复 {_safe(target)}：</span>{text}'

    media = "".join(
        f'<img class="lb-comment-image" src="../../{_safe(_img_srcs(object_rel, f)[0])}" '
        'loading="lazy" alt="评论图片">'
        for f in _comment_image_files(comment.get("comment_id"), manifest)
    )
    media = f'<div class="lb-comment-media">{media}</div>' if media else ""

    likes = comment.get("like_count")
    actions = ""
    if likes not in (None, "", 0, "0"):
        actions = f'<div class="lb-comment-actions">♡ {_safe(likes)}</div>'

    cls = "lb-comment lb-reply" if nested else "lb-comment"
    parts = [
        f'<article class="{cls}">',
        f'<div class="lb-comment-author">{_safe(author)}</div>',
        f'<div class="lb-comment-text">{text}</div>{media}{actions}',
    ]

    if not nested:
        subs = comment.get("sub_comments") or []
        if subs:
            parts.append('<div class="lb-replies">')
            parts.extend(_comment_html(s, object_rel, manifest, nested=True) for s in subs)
            try:
                declared = int(comment.get("sub_comment_count") or 0)
            except (TypeError, ValueError):
                declared = 0
            if declared > len(subs):
                parts.append(f'<div class="lb-more-replies">展开 {declared} 条回复</div>')
            parts.append("</div>")
    parts.append("</article>")
    return "".join(parts)


def split_layers(existing_text: str | None) -> tuple[str | None, str | None]:
    if not existing_text:
        return None, None
    start = existing_text.find(COMMENTS_START)
    end = existing_text.find(COMMENTS_END)
    if start == -1 or end == -1 or end < start:
        return None, None
    end += len(COMMENTS_END)
    return existing_text[start:end], None


def merge_existing(primary: str | None, secondary: str | None) -> str | None:
    """同一个对象有两份可见 md 时（改名前后各一份），把**手写的部分**并成一份再渲染。

    2026-09-04 去掉文件名的 `__<id8>` 后缀时踩到：`家克…` 那篇的干净名字上已经躺着一份旧文件，
    里面有 Owner 手写的 `time/finder/from/comment`。直接改名会把她的东西盖掉，所以这里做并集：
    tag 取并、Owner 自己加的 frontmatter 键 primary 优先、留言层把 secondary 里多出来的行接上。
    机器生成的 content 层不用管，本来就要重写。
    """
    if not secondary or not primary:
        return primary or secondary

    tags = existing_tags(primary) + [t for t in existing_tags(secondary) if t not in existing_tags(primary)]
    extras = {k: v for k, v in parse_frontmatter(secondary).items() if k not in MANAGED_FM_KEYS}
    extras.update({k: v for k, v in parse_frontmatter(primary).items() if k not in MANAGED_FM_KEYS})

    block, _ = split_layers(primary)
    other, _ = split_layers(secondary)
    lines = (block or f"{COMMENTS_START}\n{COMMENTS_END}").split("\n")
    if other:
        seen = set(lines)
        tail = [x for x in other.split("\n") if x not in seen and x not in (COMMENTS_START, COMMENTS_END)]
        if tail:
            lines = lines[:-1] + tail + [lines[-1]]

    fm = ["---", "tags: [" + ", ".join(tags) + "]"]
    if extras:
        dumped = yaml.safe_dump(extras, allow_unicode=True, sort_keys=False, default_flow_style=False)
        fm += dumped.rstrip("\n").split("\n")
    fm += ["---", ""]
    return "\n".join(fm + lines)


def render_comments_block(note_text: str | None, note_links: list[dict[str, Any]]) -> str:
    lines = [COMMENTS_START]
    if note_text:
        cleaned = _clean_links_in_text(note_text, note_links)
        lines += [
            "> [!link-brain-comment]",
            f"> 「{datetime.now().strftime('%Y%m%d')} 人」{cleaned}",
            "<!-- link-brain: id=cmt1 actor=human target=none status=open -->",
        ]
    lines.append(COMMENTS_END)
    return "\n".join(lines)


def _upgrade_comments_block(block: str) -> str:
    return block.replace("> [!quote] 留言", "> [!link-brain-comment]", 1)


def _media_html(note: dict[str, Any], manifest: dict[str, Any], object_rel: str) -> tuple[str, bool]:
    entries = [
        m for m in manifest.get("media", [])
        if m.get("role") in ("note_image", "video_cover")
        and m.get("file")
        and m.get("download_status", "ok") == "ok"
    ]
    if not entries:
        return "", False

    total = len(entries)
    parts = ['<section class="lb-media"><div class="lb-carousel">']
    for i, entry in enumerate(entries, 1):
        src, _ = _img_srcs(object_rel, entry["file"])
        parts += [
            '<figure class="lb-slide">',
            f'<img src="../../{_safe(src)}" loading="lazy" alt="图片 {i} / {total}">',
            f'<figcaption class="lb-counter">{i} / {total}</figcaption>' if total > 1 else "",
            "</figure>",
        ]
    parts.append("</div>")
    if note.get("kind") == "video":
        parts.append('<div class="lb-video-badge">视频 · 未下载</div>')
    parts.append("</section>")
    return "".join(parts), True


def _detail_html(note: dict[str, Any], comments: list[dict[str, Any]], manifest: dict[str, Any], object_rel: str) -> str:
    author = (note.get("author") or {}).get("nickname") or "匿名"
    meta = " · ".join(x for x in (_date(note.get("published_at")), note.get("ip_location")) if x)

    parts = [
        '<section class="lb-detail">',
        '<div class="lb-author-row"><div class="lb-author-dot" aria-hidden="true"></div><div class="lb-author-copy">',
        f'<div class="lb-author-name">{_safe(author)}</div>',
        f'<div class="lb-post-meta">{_safe(meta)}</div>' if meta else "",
        "</div></div>",
        f'<div class="lb-post-body">{_body_html(note.get("body") or "")}</div>',
        _tag_html(note.get("hashtags") or []),
        _engagement_html(note),
        '<div class="lb-comments">',
    ]
    if comments:
        parts.extend(_comment_html(c, object_rel, manifest) for c in comments)
    else:
        parts.append('<div class="lb-empty">暂无评论</div>')
    parts += ["</div>", "</section>"]
    return "".join(parts)


def source_open_url(note: dict[str, Any], meta: dict[str, Any]) -> str | None:
    """给人点的原文链接。

    光有 `canonical_url`（`/explore/<id>`）现在**会 404**——小红书要求带 `xsec_token`
    （2026-09-05 Owner 实机报的）。所以显示用的链接把抓取时那个 token 带上；
    `canonical_url` 仍然只当去重键用（硬约束 7），不动它。
    """
    canonical = meta.get("canonical_url") or note.get("canonical_url")
    if not canonical:
        return None
    token = note.get("xsec_token")
    if not token:
        # 老对象的 source.json 可能没存 token，从当初那条 input_url 里捞
        raw_input = meta.get("input_url") or ""
        match = re.search(r"[?&]xsec_token=([^&\s]+)", raw_input)
        token = match.group(1) if match else None
    if not token:
        return canonical
    return f"{canonical}?xsec_token={token}&xsec_source=pc_feed"


def _meta_md(note: dict[str, Any], meta: dict[str, Any], object_rel: str) -> list[str]:
    """笔记顶上那条灰色小字：原文链接 · 机读版 · 附件。

    全是 Obsidian 自己的链接（`[…](http)` / `[[vault 路径]]`），所以必须在 HTML 块外面。
    机读版就是 `derived/agent.md`——Owner 说她在 Obsidian 里看不到机读视角，这条就是入口。
    """
    first = []
    url = source_open_url(note, meta)
    if url:
        first.append(f"[原文]({url})")
    agent_rel = f"{object_rel}/derived/agent.md"
    if not any(ch in agent_rel for ch in "[]|#^"):
        first.append(f"[[{agent_rel}|机读版]]")
    rows = ["> [!link-brain-file]"]
    if first:
        rows.append("> " + " · ".join(first))
    files = _attachments_md(note.get("attachments") or [], object_rel)
    if files:
        if first:
            rows.append(">")  # 空行才会被拆成两段，不然会黏成一行
        rows.extend(files)
    return rows if len(rows) > 1 else []


def render_content_block(
    *,
    source: dict[str, Any],
    manifest: dict[str, Any],
    meta: dict[str, Any],
    object_rel: str,
) -> str:
    note = source["note"]
    comments = source.get("comments") or []
    media, has_media = _media_html(note, manifest, object_rel)
    detail = _detail_html(note, comments, manifest, object_rel)
    cls = "lb-cols" if has_media else "lb-cols lb-no-media"
    # 这一条灰色小字必须落在 HTML 块**外面**，Obsidian 才认得那是本仓库里的文件/笔记
    # （见 _attachments_md）；放在正文两栏之前——原文链接、机读版、附件都是她要点的东西。
    parts = [CONTENT_START]
    parts.extend(_meta_md(note, meta, object_rel))
    parts.append("")
    parts += [f'<div class="{cls}">', media, detail, "</div>", CONTENT_END]
    return "\n".join(parts)


FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
# 这几个键由 render 生成，每次重写；其余键都当成 Owner 手写的，原样搬过去
MANAGED_FM_KEYS = {"cssclasses", "tags", "link_brain"}


def parse_frontmatter(text: str | None) -> dict[str, Any]:
    """读回已有可见 md 的 frontmatter。

    用 YAML 解析而不是正则：Obsidian 会把 `tags: [a, b]` 改写成块状列表，
    正则版本会读不到、于是把 Owner 手写的 tag 弄丢。
    """
    if not text:
        return {}
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def existing_tags(text: str | None) -> list[str]:
    """从已有可见 md 的 frontmatter 里读回 tags（含 Owner 手写的）。"""
    tags = parse_frontmatter(text).get("tags")
    if isinstance(tags, str):
        tags = tags.split(",")
    if not isinstance(tags, list):
        return []
    return [str(x).strip() for x in tags if str(x).strip()]


def extra_frontmatter_lines(text: str | None) -> list[str]:
    """Owner 自己加的 frontmatter 键（time / finder / from / comment …）原样保留。"""
    extras = {k: v for k, v in parse_frontmatter(text).items() if k not in MANAGED_FM_KEYS}
    if not extras:
        return []
    dumped = yaml.safe_dump(extras, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return dumped.rstrip("\n").split("\n")


def suggested_tags(extracted: dict[str, Any] | None) -> list[str]:
    """小模型建议的 tag：Obsidian 的 tag 不能带空格，这里兜底再清一次。"""
    out = []
    for tag in (extracted or {}).get("tags") or []:
        cleaned = llm_mod.sanitize_tag(tag)
        if cleaned:
            out.append(cleaned)
    return out


def merge_tags(
    hashtags: list[str], prior: list[str], suggested: list[str], *, limit: int = 20
) -> list[str]:
    """小红书原 hashtag 在前，其次是已存在的（含手写）tag，最后才是小模型建议。

    只做并集：Owner 手写的 tag 永不被覆盖或删除。
    """
    merged: list[str] = []
    seen: set[str] = set()
    for group in (hashtags, prior, suggested):
        for tag in group or []:
            tag = str(tag).strip()
            # 大小写不敏感去重：原帖 hashtag 是 `claude`，小模型给 `Claude`，只留前者
            if tag and tag.casefold() not in seen:
                seen.add(tag.casefold())
                merged.append(tag)
    return merged[:limit]


def render_visible_md(
    *,
    source: dict[str, Any],
    manifest: dict[str, Any],
    meta: dict[str, Any],
    object_rel: str,
    existing_text: str | None,
    extracted: dict[str, Any] | None = None,
) -> str:
    note = source["note"]
    tags = merge_tags(
        note.get("hashtags") or [],
        existing_tags(existing_text),
        suggested_tags(extracted),
    )
    fm = [
        "---",
        "cssclasses: [link-brain, xhs-note]",
        "tags: [" + ", ".join(tags) + "]",
        "link_brain:",
        f"  item_id: {meta['item_id']}",
        f"  source: {meta['source']}",
        f"  source_id: {meta['source_id']}",
        f"  canonical_url: {meta['canonical_url']}",
        f"  origin: {meta.get('origin')}",
        f"  ingest_kind: {meta.get('ingest_kind')}",
        f"  actor: {meta.get('actor')}",
        "  actor_id: null",
        f"  first_archived: {meta.get('first_archived_at')}",
        f"  current_version: {meta['current_version']}",
        f"  images_complete: {str(meta.get('images_complete')).lower()}",
    ]
    cc = meta.get("comments_complete")
    if isinstance(cc, bool):
        cc = str(cc).lower()
    fm += [f"  comments_complete: {cc}"]
    fm += extra_frontmatter_lines(existing_text)
    fm += ["---"]

    comments_block, _ = split_layers(existing_text)
    if comments_block is None:
        comments_block = render_comments_block(meta.get("note"), note.get("links") or [])
    else:
        comments_block = _upgrade_comments_block(comments_block)

    content = render_content_block(source=source, manifest=manifest, meta=meta, object_rel=object_rel)
    return "\n".join(fm) + "\n\n" + comments_block + "\n\n" + content + "\n"


def render_agent_md(
    *,
    source: dict[str, Any],
    vision: dict[str, Any],
    meta: dict[str, Any],
    extracted: dict[str, Any] | None = None,
) -> str:
    note = source["note"]
    title = note.get("title") or meta.get("title") or "（无标题）"
    ex = extracted or {}

    lines = [f"# {title}", "", "## 概要", ""]
    lines.append(ex.get("summary") or "（未生成）")

    lines += ["", "## 重要细节", ""]
    key_points = ex.get("key_points") or []
    if key_points:
        lines.extend(f"- {x}" for x in key_points)
    else:
        lines.append("（未生成）")

    lines += ["", "## 数据点", ""]
    engagement = note.get("engagement") or {}
    if engagement:
        lines.extend(f"- {k}: {v}" for k, v in engagement.items())
    else:
        lines.append("（未生成）")

    lines += ["", "## 外链", ""]
    links = note.get("links") or []
    link_lines = [
        f"- [{x.get('text') or x.get('url')}]({x.get('url')})（{x.get('where')}）" for x in links
    ]
    for att in note.get("attachments") or []:
        target = att.get("file") or att.get("url") or ""
        link_lines.append(f"- 📎 附件：{attachment_label(att)}{(' ' + target) if target else ''}")
    for x in ex.get("links_worth_opening") or []:
        why = x.get("why") or ""
        if x.get("url"):
            link_lines.append(f"- {x['url']}（小模型建议：{why}）")
        elif x.get("hint"):
            link_lines.append(f"- {x['hint']}（小模型建议，原帖没给链接：{why}）")
    if link_lines:
        lines.extend(link_lines)
    else:
        lines.append("（未生成）")

    lines += ["", "## 原文", "", note.get("body") or "（未生成）", "", "## 图片 OCR", ""]
    images = (vision or {}).get("images") or []
    if images:
        for image in images:
            if image.get("status") == "ok":
                lines.append(f"- {image['asset']}：{(image.get('ocr') or '').strip() or '（无文字）'}")
            else:
                lines.append(f"- {image['asset']}：（识别失败：{image.get('error')}）")
    else:
        lines.append("（未生成）")

    lines += ["", "## 评论", ""]
    comments = source.get("comments") or []
    if comments:
        valuable = {x.get("id"): x.get("why") or "" for x in ex.get("valuable_comments") or []}
        noise = set(ex.get("ads_or_noise") or [])
        for label, c in llm_mod.comment_labels(comments):
            indent = "  " if "." in label else ""
            mark = ""
            if label in valuable:
                mark = f"（值得看：{valuable[label]}）"
            elif label in noise:
                mark = "（广告/噪音）"
            nickname = (c.get("author") or {}).get("nickname") or "匿名"
            lines.append(f"{indent}- [{label}] {nickname}：{c.get('text')}{mark}")
    else:
        lines.append("（未生成）")

    lines += [
        "", "## 元信息", "",
        f"- item_id: {meta['item_id']}",
        f"- canonical_url: {meta.get('canonical_url')}",
        f"- current_version: {meta['current_version']}",
        f"- images_complete: {meta.get('images_complete')}",
        f"- comments_complete: {meta.get('comments_complete')}",
        f"- attachments_status: {meta.get('attachments_status')}",
        f"- extracted: {'ok' if extracted else '未生成'}",
    ]
    return "\n".join(lines) + "\n"


def brief_summary(source: dict[str, Any], extracted: dict[str, Any] | None = None) -> str:
    """有小模型概要就用它，没有就退回正文前 120 字（Lot 3 行为）。"""
    summary = (extracted or {}).get("summary")
    if summary:
        return summary
    return _first_n_chars((source.get("note") or {}).get("body"), 120)


def ensure_css_snippet() -> None:
    """Sync managed CSS into the vault so UI changes actually reach existing vaults."""
    target = storage.vault_root() / ".obsidian" / "snippets" / "link-brain.css"
    template = Path(__file__).resolve().parent / "assets" / "link-brain.css"
    content = template.read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") == content:
        return
    target.write_text(content, encoding="utf-8")


def render_object(
    source_key: str,
    source_id: str,
    *,
    verbose: bool = False,
    llm: bool = False,
    re_extract: bool = False,
) -> dict[str, Any]:
    """拼可见 md + agent.md。

    `llm=True` 时才会调小模型生成 `derived/extracted.json`（缺了或上次失败才调，
    `re_extract=True` 强制重调）。不管调没调，已有的 `extracted.json` 都会被读进来用。
    """
    ensure_css_snippet()
    object_dir = storage.object_dir(source_key, source_id)
    meta_path = object_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"没有归档过: {source_key}/{source_id}")

    meta = storage.read_json(meta_path)
    raw_dir = storage.raw_dir(source_key, source_id, meta["current_version"])
    source_doc = storage.read_json(raw_dir / "source.json")
    manifest = storage.read_json(raw_dir / "manifest.json")

    derived_dir = storage.derived_dir(source_key, source_id)
    vision_path = derived_dir / "vision.json"
    vision_doc = storage.read_json(vision_path) if vision_path.exists() else {"images": []}
    object_rel = f"_archive/{source_key}/{source_id}"

    # 附件字节是事后补下来的（对象级 attachments/），这里回填到 source 的附件条目上
    downloaded = attachments_mod.load_downloaded(source_key, source_id)
    for att in source_doc["note"].get("attachments") or []:
        got = downloaded.get(att.get("doc_id"))
        if got and (object_dir / "attachments" / got["file"]).exists():
            att["file"] = f"attachments/{got['file']}"
            att["status"] = "downloaded"
            att["bytes"] = got.get("bytes")
            att["sha256"] = got.get("sha256")
            # meta 里那个总状态也要跟上：ingest 写完 v0002 之后它会退回 metadata_only，
            # 而字节其实早就在盘上了（catch / search 的 JSON 都读这个字段）
            if meta.get("attachments_status") != "downloaded":
                meta["attachments_status"] = "downloaded"
                storage.write_json(meta_path, meta)

    extracted_doc = llm_mod.load_extracted(source_key, source_id)
    if llm or re_extract:
        stale = re_extract or not extracted_doc or extracted_doc.get("status") != "ok"
        if stale:
            extracted_doc = llm_mod.extract(
                source_key, source_id, force=re_extract, verbose=verbose
            )
    extracted = llm_mod.extracted_data(extracted_doc)

    visible_dir = storage.visible_dir()
    visible_dir.mkdir(parents=True, exist_ok=True)
    visible_path = resolve_visible_path(
        visible_dir,
        source_doc["note"].get("title") or meta.get("title") or "",
        source_id,
        meta["item_id"],
    )

    # 目标文件上可能已经躺着同一个对象的另一份（改名前后各一份）——先并、再删旧的，别盖掉手写内容
    target_text = None
    if visible_path.exists() and owner_item_id(visible_path) == meta["item_id"]:
        target_text = visible_path.read_text(encoding="utf-8")

    existing_text = target_text
    old_visible = meta.get("visible_note")
    if old_visible:
        old_path = storage.vault_root() / old_visible
        if old_path.exists():
            old_text = old_path.read_text(encoding="utf-8")
            existing_text = (
                merge_existing(target_text, old_text) if target_text is not None else old_text
            )
            if old_path != visible_path:
                old_path.unlink()

    visible_path.write_text(
        render_visible_md(
            source=source_doc,
            manifest=manifest,
            meta=meta,
            object_rel=object_rel,
            existing_text=existing_text,
            extracted=extracted,
        ),
        encoding="utf-8",
    )

    derived_dir.mkdir(parents=True, exist_ok=True)
    (derived_dir / "agent.md").write_text(
        render_agent_md(
            source=source_doc, vision=vision_doc, meta=meta, extracted=extracted
        ),
        encoding="utf-8",
    )

    rel_visible = str(visible_path.relative_to(storage.vault_root())).replace("\\", "/")
    if meta.get("visible_note") != rel_visible:
        meta["visible_note"] = rel_visible
        storage.write_json(meta_path, meta)

    if verbose:
        print(f"[render] {meta['item_id']} -> {rel_visible}")
    return {"item_id": meta["item_id"], "visible_note": rel_visible, "agent_md": str(derived_dir / "agent.md")}


def render_item(
    source_key: str,
    source_id: str,
    *,
    verbose: bool = False,
    llm: bool = False,
    re_extract: bool = False,
) -> dict[str, Any]:
    vision_mod.build_vision(source_key, source_id, verbose=verbose)
    return render_object(
        source_key, source_id, verbose=verbose, llm=llm, re_extract=re_extract
    )


def run(args) -> int:
    import sys

    conn = index_mod.connect()
    try:
        if getattr(args, "all", False):
            rows = conn.execute("SELECT source, source_id FROM objects ORDER BY item_id").fetchall()
            targets = [(r["source"], r["source_id"]) for r in rows]
        elif args.target:
            row = index_mod.get_object(conn, args.target)
            if not row:
                print(f"没有归档过: {args.target}", file=sys.stderr)
                return 1
            targets = [(row["source"], row["source_id"])]
        else:
            print("需要 target 或 --all", file=sys.stderr)
            return 1
    finally:
        conn.close()

    if not targets:
        print("索引里没有对象可渲染")
        return 0

    for source_key, source_id in targets:
        try:
            result = render_item(
                source_key,
                source_id,
                verbose=getattr(args, "verbose", False),
                llm=getattr(args, "extract", False) or getattr(args, "re_extract", False),
                re_extract=getattr(args, "re_extract", False),
            )
        except FileNotFoundError as exc:
            print(f"跳过 {source_key}/{source_id}: {exc}", file=sys.stderr)
            continue
        print(f"{result['item_id']} -> {result['visible_note']}")
    return 0
