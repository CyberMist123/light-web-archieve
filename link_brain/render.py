"""把 source.json 渲染成 Obsidian 可见 md + derived/agent.md。纯模板拼接，不经过模型。

规格见 docs/FORMAT.md §6/§7。rerender 只重写可见 md 的 content 层，comments 层原样保留。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import index as index_mod, storage
from . import vision as vision_mod

COMMENTS_START = "<!-- link-brain:comments:start -->"
COMMENTS_END = "<!-- link-brain:comments:end -->"
CONTENT_START = "<!-- link-brain:content:start -->"
CONTENT_END = "<!-- link-brain:content:end -->"

WINDOWS_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_TITLE_LEN = 60
PREVIEW_UNSUPPORTED_SUFFIXES = {".avif", ".heic"}

ACTOR_LABELS = {"human": "人", "gpt": "gpt", "fable": "fable"}


# --------------------------------------------------------------------------
# 文件名 sanitizer
# --------------------------------------------------------------------------


def sanitize_title(title: str) -> str:
    """Windows 非法字符 + 控制字符 → 下划线；截断；保留名加后缀；去掉结尾点/空格。"""
    cleaned = WINDOWS_ILLEGAL_RE.sub("_", title or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "untitled"
    cleaned = cleaned[:MAX_TITLE_LEN]
    cleaned = cleaned.rstrip(". ")
    if not cleaned:
        cleaned = "untitled"
    if cleaned.upper() in RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned


def visible_filename(title: str, note_id: str) -> str:
    return f"{sanitize_title(title)}__{note_id[-8:]}.md"


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def _clean_links_in_text(text: str, links: list[dict[str, Any]]) -> str:
    """把附言里出现的原始 URL 换成 `[标题](url)`（没有对应标题的原样保留）。"""
    if not text:
        return text
    for link in links or []:
        url = link.get("url")
        if url and url in text:
            label = link.get("text") or url
            text = text.replace(url, f"[{label}]({url})")
    return text


def _comment_image_files(comment_id: str, manifest: dict[str, Any]) -> list[str]:
    """从 manifest.json 里按 comment_id 找评论图（source.json 的 comments[].images[] 没有 file 字段）。

    实测（docs/POC-xiaohongshu.md）MCP 结构上不返回评论图，这里恒为空——评论没有图就不输出图片段。
    """
    return [
        m["file"]
        for m in manifest.get("media", [])
        if m.get("role") == "comment_image" and m.get("comment_id") == comment_id and m.get("file")
    ]


def _comment_body_lines(
    comment: dict[str, Any], object_rel: str, manifest: dict[str, Any], *, indent: str = ""
) -> list[str]:
    author = (comment.get("author") or {}).get("nickname") or "匿名"
    text = comment.get("text") or ""
    target = comment.get("target_nickname")
    prefix = f"回复 {target}：" if target else "："
    lines = [f"{indent}- **{author}**{prefix}{text}"]
    for file in _comment_image_files(comment.get("comment_id"), manifest):
        lines.append(f"{indent}  {_img_from_manifest(object_rel, file)}")
    return lines


def _first_n_chars(text: str, n: int) -> str:
    text = (text or "").strip()
    return text[:n]


# --------------------------------------------------------------------------
# comments 层解析（分层保护）
# --------------------------------------------------------------------------


def split_layers(existing_text: str | None) -> tuple[str | None, str | None]:
    """从已有可见 md 里抠出 comments 层块（含标记本身）和标题之外无关内容。

    返回 (comments_block_text_including_markers, None)；找不到就 (None, None)。
    """
    if not existing_text:
        return None, None
    start = existing_text.find(COMMENTS_START)
    end = existing_text.find(COMMENTS_END)
    if start == -1 or end == -1 or end < start:
        return None, None
    end += len(COMMENTS_END)
    return existing_text[start:end], None


# --------------------------------------------------------------------------
# 渲染主体
# --------------------------------------------------------------------------


def render_comments_block(note_text: str | None, note_links: list[dict[str, Any]]) -> str:
    lines = [COMMENTS_START]
    if note_text:
        cleaned = _clean_links_in_text(note_text, note_links)
        today = datetime.now().strftime("%Y%m%d")
        lines.append(f"「{today} 人」{cleaned}")
        lines.append("<!-- link-brain: id=cmt1 actor=human target=none status=open -->")
    lines.append(COMMENTS_END)
    return "\n".join(lines)


def render_content_block(
    *,
    source: dict[str, Any],
    manifest: dict[str, Any],
    meta: dict[str, Any],
    object_rel: str,
) -> str:
    note = source["note"]
    parts: list[str] = [CONTENT_START]

    # 图片
    parts.append("## 图片")
    parts.append("")
    image_entries = [
        m for m in manifest.get("media", [])
        if m.get("role") in ("note_image", "video_cover") and m.get("file")
    ]
    if image_entries:
        for entry in image_entries:
            file_rel = entry["file"]  # 已是 "raw/vNNNN/assets/xxx"
            parts.append(_img_from_manifest(object_rel, file_rel))
    else:
        parts.append("（无）")
    parts.append("")

    # 正文
    parts.append("## 正文")
    parts.append("")
    parts.append(note.get("body") or "（无正文）")
    parts.append("")

    # 评论
    parts.append("## 评论")
    parts.append("")
    comments = source.get("comments") or []
    if comments:
        for comment in comments:
            parts.extend(_comment_body_lines(comment, object_rel, manifest))
            for sub in comment.get("sub_comments") or []:
                parts.extend(_comment_body_lines(sub, object_rel, manifest, indent="  "))
    else:
        parts.append("（无评论）")
    parts.append("")

    # 归档信息
    parts.append("## 归档信息")
    parts.append("")
    parts.append(f"- 原链接：{note.get('canonical_url')}")
    version_name = storage.version_name(meta["current_version"])
    first_archived_date = (meta.get("first_archived_at") or "")[:10]
    parts.append(f"- 首次归档：{first_archived_date} · 版本 {version_name}")
    parts.append(f"- 附件：{meta.get('attachments_status')}" + (
        "（笔记文件 MCP 拿不到，线索见 source.json）" if meta.get("attachments_status") == "unavailable" else ""
    ))
    parts.append(CONTENT_END)
    return "\n".join(parts)


def _img_from_manifest(object_rel: str, file_rel: str) -> str:
    """`file_rel` 是 manifest 里的 `raw/vNNNN/assets/xxx.ext`（相对对象目录）。"""
    suffix = Path(file_rel).suffix.lower()
    if suffix in PREVIEW_UNSUPPORTED_SUFFIXES:
        preview_name = Path(file_rel).stem + ".png"
        preview_target = f"{object_rel}/derived/previews/{preview_name}"
        raw_target = f"{object_rel}/{file_rel}"
        return f"![[{preview_target}]] （原图：[[{raw_target}]]）"
    return f"![[{object_rel}/{file_rel}]]"


def render_visible_md(
    *,
    source: dict[str, Any],
    manifest: dict[str, Any],
    meta: dict[str, Any],
    object_rel: str,
    existing_text: str | None,
) -> str:
    note = source["note"]
    frontmatter_tags = note.get("hashtags") or []
    fm_lines = ["---"]
    fm_lines.append("tags: [" + ", ".join(frontmatter_tags) + "]")
    fm_lines.append("link_brain:")
    fm_lines.append(f"  item_id: {meta['item_id']}")
    fm_lines.append(f"  source: {meta['source']}")
    fm_lines.append(f"  source_id: {meta['source_id']}")
    fm_lines.append(f"  canonical_url: {meta['canonical_url']}")
    fm_lines.append(f"  origin: {meta.get('origin')}")
    fm_lines.append(f"  ingest_kind: {meta.get('ingest_kind')}")
    fm_lines.append(f"  actor: {meta.get('actor')}")
    fm_lines.append(f"  actor_id: null")
    fm_lines.append(f"  first_archived: {meta.get('first_archived_at')}")
    fm_lines.append(f"  current_version: {meta['current_version']}")
    fm_lines.append(f"  images_complete: {str(meta.get('images_complete')).lower()}")
    fm_lines.append(f"  comments_complete: {meta.get('comments_complete')}")
    fm_lines.append("---")

    title = note.get("title") or meta.get("title") or "（无标题）"

    comments_block, _ = split_layers(existing_text)
    if comments_block is None:
        comments_block = render_comments_block(meta.get("note"), note.get("links") or [])

    content_block = render_content_block(source=source, manifest=manifest, meta=meta, object_rel=object_rel)

    body = "\n".join(fm_lines) + "\n\n" + f"# {title}\n\n" + comments_block + "\n\n" + content_block + "\n"
    return body


def render_agent_md(*, source: dict[str, Any], vision: dict[str, Any], meta: dict[str, Any]) -> str:
    note = source["note"]
    title = note.get("title") or meta.get("title") or "（无标题）"
    lines: list[str] = [f"# {title}"]

    lines += ["", "## 概要", ""]  # Lot 3 阶段留空占位

    lines += ["", "## 重要细节", ""]  # Lot 3 阶段留空占位

    lines += ["", "## 数据点", ""]
    engagement = note.get("engagement") or {}
    if engagement:
        for key, value in engagement.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("（未生成）")

    lines += ["", "## 外链", ""]
    links = note.get("links") or []
    if links:
        for link in links:
            lines.append(f"- [{link.get('text') or link.get('url')}]({link.get('url')})（{link.get('where')}）")
    else:
        lines.append("（未生成）")

    lines += ["", "## 原文", ""]
    lines.append(note.get("body") or "（未生成）")

    lines += ["", "## 图片 OCR", ""]
    images = (vision or {}).get("images") or []
    if images:
        for image in images:
            if image.get("status") == "ok":
                ocr_text = (image.get("ocr") or "").strip() or "（无文字）"
                lines.append(f"- {image['asset']}：{ocr_text}")
            else:
                lines.append(f"- {image['asset']}：（识别失败：{image.get('error')}）")
    else:
        lines.append("（未生成）")

    lines += ["", "## 评论", ""]
    comments = source.get("comments") or []
    if comments:
        for comment in comments:
            author = (comment.get("author") or {}).get("nickname") or "匿名"
            lines.append(f"- {author}：{comment.get('text')}")
            for sub in comment.get("sub_comments") or []:
                sub_author = (sub.get("author") or {}).get("nickname") or "匿名"
                lines.append(f"  - {sub_author}：{sub.get('text')}")
    else:
        lines.append("（未生成）")

    lines += ["", "## 元信息", ""]
    lines.append(f"- item_id: {meta['item_id']}")
    lines.append(f"- canonical_url: {meta.get('canonical_url')}")
    lines.append(f"- current_version: {meta['current_version']}")
    lines.append(f"- images_complete: {meta.get('images_complete')}")
    lines.append(f"- comments_complete: {meta.get('comments_complete')}")
    lines.append(f"- attachments_status: {meta.get('attachments_status')}")

    return "\n".join(lines) + "\n"


def brief_summary(source: dict[str, Any]) -> str:
    return _first_n_chars((source.get("note") or {}).get("body"), 120)


# --------------------------------------------------------------------------
# 落盘：单对象渲染
# --------------------------------------------------------------------------


def render_object(source_key: str, source_id: str, *, verbose: bool = False) -> dict[str, Any]:
    object_dir = storage.object_dir(source_key, source_id)
    meta_path = object_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"没有归档过: {source_key}/{source_id}")
    meta = storage.read_json(meta_path)
    version = meta["current_version"]
    raw_dir = storage.raw_dir(source_key, source_id, version)
    source_doc = storage.read_json(raw_dir / "source.json")
    manifest = storage.read_json(raw_dir / "manifest.json")

    derived_dir = storage.derived_dir(source_key, source_id)
    vision_path = derived_dir / "vision.json"
    vision_doc = storage.read_json(vision_path) if vision_path.exists() else {"images": []}

    object_rel = f"_archive/{source_key}/{source_id}"

    visible_dir = storage.visible_dir()
    visible_dir.mkdir(parents=True, exist_ok=True)
    filename = visible_filename(source_doc["note"].get("title") or meta.get("title") or "", source_id)
    visible_path = visible_dir / filename

    # 若标题变了，旧文件名可能不同：找并删掉此对象名下的旧可见文件，只留新的一份
    old_visible = meta.get("visible_note")
    existing_text = None
    if old_visible:
        old_path = storage.vault_root() / old_visible
        if old_path.exists():
            existing_text = old_path.read_text(encoding="utf-8")
            if old_path != visible_path:
                old_path.unlink()

    visible_md = render_visible_md(
        source=source_doc, manifest=manifest, meta=meta, object_rel=object_rel, existing_text=existing_text
    )
    visible_path.write_text(visible_md, encoding="utf-8")

    agent_md = render_agent_md(source=source_doc, vision=vision_doc, meta=meta)
    (derived_dir).mkdir(parents=True, exist_ok=True)
    (derived_dir / "agent.md").write_text(agent_md, encoding="utf-8")

    rel_visible = str(visible_path.relative_to(storage.vault_root())).replace("\\", "/")
    if meta.get("visible_note") != rel_visible:
        meta["visible_note"] = rel_visible
        storage.write_json(meta_path, meta)

    if verbose:
        print(f"[render] {meta['item_id']} -> {rel_visible}")

    return {"item_id": meta["item_id"], "visible_note": rel_visible, "agent_md": str(derived_dir / "agent.md")}


def render_item(source_key: str, source_id: str, *, verbose: bool = False) -> dict[str, Any]:
    """先跑 vision（按 sha256 跳过已识别），再渲染。"""
    vision_mod.build_vision(source_key, source_id, verbose=verbose)
    return render_object(source_key, source_id, verbose=verbose)


def run(args) -> int:
    import sys

    conn = index_mod.connect()
    try:
        if getattr(args, "all", False):
            cur = conn.execute("SELECT source, source_id FROM objects ORDER BY item_id")
            targets = [(row["source"], row["source_id"]) for row in cur.fetchall()]
        elif args.target:
            row = index_mod.get_object(conn, args.target)
            if row:
                targets = [(row["source"], row["source_id"])]
            else:
                print(f"没有归档过: {args.target}", file=sys.stderr)
                return 1
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
            result = render_item(source_key, source_id, verbose=getattr(args, "verbose", False))
        except FileNotFoundError as exc:
            print(f"跳过 {source_key}/{source_id}: {exc}", file=sys.stderr)
            continue
        print(f"{result['item_id']} -> {result['visible_note']}")
    return 0
