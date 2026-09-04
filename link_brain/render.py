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


def visible_filename(title: str, note_id: str) -> str:
    return f"{sanitize_title(title)}__{note_id[-8:]}.md"


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
    return "\n".join([CONTENT_START, f'<div class="{cls}">', media, detail, "</div>", CONTENT_END])


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
    filename = visible_filename(source_doc["note"].get("title") or meta.get("title") or "", source_id)
    visible_path = visible_dir / filename

    existing_text = None
    old_visible = meta.get("visible_note")
    if old_visible:
        old_path = storage.vault_root() / old_visible
        if old_path.exists():
            existing_text = old_path.read_text(encoding="utf-8")
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
