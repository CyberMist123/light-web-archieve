"""Obsidian human view + agent view renderer.

Human view is a responsive Xiaohongshu-like detail page. RAW/agent/index are unchanged.
Rerender replaces only the managed content layer and preserves the comments layer.
"""
from __future__ import annotations

from functools import lru_cache
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import index as index_mod, storage
from . import attachments as attachments_mod
from . import llm as llm_mod
from . import mdsafe
from . import vision as vision_mod


def dedupe_lines(text: str, seen: str = '') -> str:
    """按句去重：和已出现的内容（正文 + 前面留下的句子）几乎一样的句子丢掉。短句（<6 字）只去完全重复。"""
    from rapidfuzz import fuzz
    norm = lambda x: re.sub(r'[\s，。！？、,.!?；;：:“”"\'（）()]+', '', x)
    pool = norm(seen)
    out = []
    for raw in re.split(r'(?<=[。！？!?])|\n', text or ''):
        line = raw.strip()
        n = norm(line)
        if not n:
            continue
        if n in pool or (len(n) >= 6 and fuzz.partial_ratio(n, pool) >= 92):
            continue
        out.append(line)
        pool += n
    return '\n'.join(out)

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
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    return frontmatter_item_id(text)


def find_visible_by_item_id(item_id: str) -> list[Path]:
    """可见目录（含子目录）里属于这个对象的所有 md，新的在前（1001，审计 render-8：她改了名 / 挪了位置）。

    `_` / `.` 开头的子目录（_media 之类）不看；每个文件只读开头一段，frontmatter 就在那。
    """
    root = storage.visible_dir()
    if not root.is_dir() or not item_id:
        return []
    hits = []
    for p in root.rglob("*.md"):
        if any(part.startswith(("_", ".")) for part in p.relative_to(root).parts[:-1]):
            continue
        try:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(16384)
        except OSError:
            continue
        if item_id in head and frontmatter_item_id(head) == item_id:
            hits.append(p)
    return sorted(hits, key=lambda p: p.stat().st_mtime, reverse=True)


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
    # 批次 D · N9：仍是原帖话题（note.hashtags）；桌面插件开着时点了回目录按 #标签 筛（note-actions.js 接点击）
    chips = "".join(
        f'<span class="lb-tag" title="在目录里看带 #{_safe(x)} 的收藏">#{_safe(x)}</span>' for x in tags or [] if x
    )
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


def _comment_image_files(comment_id: str | None, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """这条评论的图（manifest 条目：file / width / height）。"""
    if not comment_id:
        return []
    return [
        m for m in manifest.get("media", [])
        if m.get("role") == "comment_image"
        and m.get("comment_id") == comment_id
        and m.get("file")
    ]


def _dims_attr(entry: dict[str, Any] | None) -> str:
    """批次 D · N6：manifest 里有正整数宽高就写进 <img>，浏览器按比例先占位（打开一次到位、翻图不跳）。"""
    try:
        w, h = int((entry or {}).get("width") or 0), int((entry or {}).get("height") or 0)
    except (TypeError, ValueError):
        return ""
    return f' width="{w}" height="{h}"' if w > 0 and h > 0 else ""


def _dims(entry: dict[str, Any] | None) -> tuple[int, int] | None:
    try:
        w, h = int((entry or {}).get("width") or 0), int((entry or {}).get("height") or 0)
    except (TypeError, ValueError):
        return None
    return (w, h) if w > 0 and h > 0 else None


@lru_cache(maxsize=64)
def _vision_kinds(vision_path: str, mtime: float) -> dict[str, dict[str, Any]]:
    try:
        doc = json.loads(Path(vision_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for im in doc.get("images", []):
        v = im.get("refined") if (im.get("refined") or {}).get("status") == "ok" else im.get("visual") or {}
        chars = sum(len(l.get("text") or "") for l in im.get("lines") or [])
        out[im.get("asset", "")] = {"kind": v.get("kind") or im.get("layout"), "chars": chars}
    return out


def _comment_image_size(object_rel: str, file: str) -> str:
    """评论图片显示尺寸：sticker（表情包/小图，缩小）/ doc（截图、表格、流程图，放大）/ photo（照片，中等）。

    类型取识图结果；没有识图结果就看像素：边长都不超过 400 当表情包。
    """
    obj = storage.vault_root() / object_rel
    vpath = obj / "derived" / "vision.json"
    info = _vision_kinds(str(vpath), vpath.stat().st_mtime if vpath.exists() else 0.0).get(file) or {}
    kind, chars = info.get("kind"), info.get("chars", 0)
    if kind in ("text", "table", "diagram") and chars >= 40:
        return "doc"
    try:
        from PIL import Image
        with Image.open(obj / file) as im:
            w, h = im.size
    except Exception:  # noqa: BLE001 - 读不了就按普通图
        return "photo"
    if max(w, h) <= 400 or (kind in ("picture", "title") and chars < 40 and max(w, h) <= 600):
        return "sticker"
    return "photo"


def _comment_html(
    comment: dict[str, Any],
    object_rel: str,
    manifest: dict[str, Any],
    *,
    nested: bool = False,
    gap_reasons: dict[str, str] | None = None,
    floor_limit: int | None = None,
    scoped: bool = False,
) -> str:
    """Human comment row: author + text only; no date/location/overall count."""
    author = (comment.get("author") or {}).get("nickname") or "匿名"
    text = _safe(comment.get("text") or "")
    target = comment.get("target_nickname")
    if target:
        text = f'<span class="lb-reply-target">回复 {_safe(target)}：</span>{text}'

    files = _comment_image_files(comment.get("comment_id"), manifest)
    media = "".join(
        f'<img class="lb-comment-image lb-ci-{_comment_image_size(object_rel, f["file"])}" '
        f'src="../../{_safe(_img_srcs(object_rel, f["file"])[0])}"{_dims_attr(f)} loading="lazy" alt="评论图片">'
        for f in files
    )
    # 0928 Owner：表情包小一点、截图/表格/流程图大一点、多张并排
    media = f'<div class="lb-comment-media lb-ci-n{min(len(files), 3)}">{media}</div>' if media else ""
    audio = comment.get("audio") or {}
    if audio:
        file = next((m["file"] for m in manifest.get("media", []) if m.get("role") == "comment_audio"
                     and m.get("comment_id") == comment.get("comment_id") and m.get("file")), None)
        secs = round((audio.get("duration_ms") or 0) / 1000)
        label = "🎤 语音" + (f" {secs} 秒" if secs else "") + (f" · {_safe(audio['tag'])}" if audio.get("tag") else "")
        player = f'<audio controls preload="none" src="../../{_safe(object_rel)}/{_safe(file)}"></audio>' if file else ""
        asr = f'<div class="lb-comment-asr">{_safe(audio.get("asr_text") or "")}</div>' if audio.get("asr_text") else ""
        media += f'<div class="lb-comment-audio"><span class="lb-comment-audio-label">{label}</span>{asr}{player}</div>'

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
                parts.append(f'<div class="lb-more-replies">{_gap_text(comment, declared - len(subs), gap_reasons, floor_limit, scoped)}</div>')
            parts.append("</div>")
        else:
            try:
                declared = int(comment.get("sub_comment_count") or 0)
            except (TypeError, ValueError):
                declared = 0
            if declared > 0:
                parts.append(f'<div class="lb-replies"><div class="lb-more-replies">{_gap_text(comment, declared, gap_reasons, floor_limit, scoped)}</div></div>')
    parts.append("</article>")
    return "".join(parts)


def _gap_text(comment: dict[str, Any], missing: int, gap_reasons: dict[str, str] | None,
              floor_limit: int | None = None, scoped: bool = False) -> str:
    """这楼还有几条回复没拿到、为什么（1008 Owner：缺口如实标，不写假的「展开 N 条回复」）。
    批次 D · N8：楼层上限外没展开的（原因不知道 / not_expanded）说人话：「另有 N 条回复没存（只存了前 10 楼的回复）」。"""
    from .adapters import xiaohongshu as xhs
    reason = (gap_reasons or {}).get(str(comment.get("comment_id") or ""))
    if reason is None or (reason == "not_expanded" and not scoped):
        floors = (("全部楼层" if floor_limit >= 2000 else f"前 {floor_limit} 楼")
                  if isinstance(floor_limit, int) and floor_limit > 0 else "前几楼")
        return f"另有 {missing} 条回复没存（只存了{floors}的回复）"
    # 1009：设置楼数之内的缺口后台会自动补齐；读多少次都一样的（原站多显示 / 楼已删）照实说，不说「接着读」
    if reason == "count_mismatch":
        return f"原站多显示 {missing} 条回复（删了或被折叠，看不到）"
    if reason == "gone":
        return f"还有 {missing} 条回复没拿到（这楼在原帖里已经找不到了，存下的是当时那几条）"
    if reason in ("old_reader", "not_expanded"):  # 只有 scoped（设置楼数之内）才会走到这里
        from .comment_fill import reason_text
        return f"还有 {missing} 条回复没拿到（{reason_text(reason)}，后台在补）"
    why = xhs.REPLY_GAP_CN.get(reason, "没读全")
    tail = "，后台在补" if reason in xhs.RESUMABLE_GAPS else ""
    return f"还有 {missing} 条回复没拿到（{why}{tail}）"


# 批次 D · N8 / N14：评论区里「现在抓全部评论」的入口（点击由插件 note-actions.js 接；body.lb-actions-on 时才显示）
FETCH_COMMENTS_ACT = '<span class="lb-act lb-act-fetch-comments" role="button" tabindex="0">{label}</span>'
# 1011：这篇在小红书网页版要验证才能看——「打开验证」开读取服务的验证窗口到这篇（点击由插件 note-actions.js 接）
NOTE_VERIFY_ACT = '<span class="lb-act lb-act-note-verify" role="button" tabindex="0">打开验证</span>'


def _restricted_note_html(view: dict[str, Any] | None) -> str:
    """评论区顶上一行：「这篇在小红书网页版要验证才能看」+「打开验证」。没标着就不出。"""
    r = (view or {}).get("restricted") if isinstance(view, dict) else None
    if not r:
        return ""
    # 1017 她：「这些帖子是真的不见了」——不再让她去点验证，只如实说一句
    from .restricted import GONE_TEXT
    return f'<div class="lb-comments-note lb-restricted-note">{_safe(GONE_TEXT)}</div>'


def _comments_note_html(capture: dict[str, Any] | None, comments: list[dict[str, Any]],
                        view: dict[str, Any] | None = None) -> str:
    """评论区顶上的一行状态：读到几楼、展开几楼、还缺几条——只在没读全时出现。

    1009：有 view（comment_fill.view_for_render）就按设置楼数现算——设置楼数之内没缺口就不出这一行；
    有缺口写「后台在补」，连着几次补不上写「已记进问题面板」，不再写「下次同步接着读」「不再读」。"""
    if view is not None:
        missing = int(view.get("missing") or 0)
        if missing <= 0:
            return ""
        from .comment_fill import floors_label
        attempts = int(view.get("attempts") or 0)
        why = view.get("why") or "没读全"
        if view.get("stuck"):
            tail = f"，试了 {attempts} 次没补上，已记进问题面板" if attempts else "，已记进问题面板"
        else:
            tail = "，后台在补" + (f"（已续读 {attempts} 次）" if attempts else "")
        text = f"评论读到 {len(comments)} 楼，{floors_label(int(view.get('floors') or 10))}的楼中楼还缺 {missing} 条（{why}{tail}）"
        return f'<div class="lb-comments-note">{_safe(text)}' + FETCH_COMMENTS_ACT.format(label="现在抓全部评论") + "</div>"
    cl = (capture or {}).get("comment_load") or {}
    missing = int(cl.get("replies_missing") or 0)
    if missing <= 0:
        if cl:
            return ""
        # 老读取组件没有 comment_load：按楼算楼中楼还缺几条（不编原因）
        lack = 0
        for c in comments or []:
            try:
                lack += max(0, int(c.get("sub_comment_count") or 0) - len(c.get("sub_comments") or []))
            except (TypeError, ValueError):
                continue
        if lack <= 0:
            return ""
        return (f'<div class="lb-comments-note">{_safe(f"楼中楼还缺 {lack} 条（只存了前几楼的回复）")}'
                + FETCH_COMMENTS_ACT.format(label="现在抓全部评论") + "</div>")
    from .adapters import xiaohongshu as xhs
    bits = [f"评论读到 {cl.get('floors_loaded') or len(comments)} 楼"]
    if cl.get("floor_limit"):
        bits.append(f"前 {cl['floor_limit']} 楼展开回复")
    gaps = cl.get("gaps") or []
    main = max(gaps, key=lambda g: int(g.get("missing") or 0)).get("reason") if gaps else cl.get("stop_reason")
    why = xhs.REPLY_GAP_CN.get(str(main or ""), "没读全")
    attempts = int(cl.get("fill_attempts") or 0)
    if any(g.get("reason") in xhs.RESUMABLE_GAPS for g in gaps) and attempts < 3:
        tail = "，下次同步接着读" + (f"（已续读 {attempts} 次）" if attempts else "")
    elif attempts >= 3:
        tail = f"，已续读 {attempts} 次，剩下的太长不再读"
    else:
        tail = ""
    bits.append(f"楼中楼还缺 {missing} 条（{why}{tail}）")
    return f'<div class="lb-comments-note">{_safe("，".join(bits))}' + FETCH_COMMENTS_ACT.format(label="现在抓全部评论") + "</div>"


def split_layers(existing_text: str | None) -> tuple[str | None, str | None]:
    if not existing_text:
        return None, None
    start = existing_text.find(COMMENTS_START)
    end = existing_text.find(COMMENTS_END)
    if start == -1 or end == -1 or end < start:
        return None, None
    end += len(COMMENTS_END)
    return existing_text[start:end], None


# 批次 D · F1-c：受管块外的行，哪些是机器碎片（残缺的 HTML / 标记 / 围栏），其余算她手写
MACHINE_FRAGMENT = re.compile(
    r'class="lb-|<!--\s*link-brain|\[!(?:link-brain|lb-)|^```|annotate-view\.js|'
    r'^</?(?:div|section|figure|article|img|video|audio|details|summary|span|br|p)\b'
)
_DVJS_RE = re.compile(r"```dataviewjs\r?\n.*?```", re.S)


def stray_human_lines(text: str | None) -> tuple[list[str], list[str]]:
    """受管块之外的行 → (她手写的, 机器碎片)。新渲染的笔记两列都为空。"""
    if not text:
        return [], []
    body = text
    m = FRONTMATTER_RE.match(body)
    if m:
        body = body[m.end():]
    s, e = body.find(COMMENTS_START), body.find(COMMENTS_END)
    if s != -1 and e > s:
        body = body[:s] + "\n" + body[e + len(COMMENTS_END):]
    body = _DVJS_RE.sub(lambda mm: "\n" if "annotate-view.js" in mm.group(0) else mm.group(0), body)
    s, e = body.find(CONTENT_START), body.find(CONTENT_END)
    if s != -1 and e > s:
        body = body[:s] + "\n" + body[e + len(CONTENT_END):]
    elif s != -1:
        # 只剩 START：到下一个已知边界都算机器层
        cands = [x for x in (body.find(COMMENTS_START, s), body.find("```dataviewjs", s)) if x != -1]
        body = body[:s] + "\n" + body[min(cands) if cands else len(body):]
    elif e != -1:
        body = body[e + len(CONTENT_END):]
    human: list[str] = []
    machine: list[str] = []
    in_callout = False
    for line in body.split("\n"):
        stripped = line.strip()
        if re.match(r"^>\s*\[!(?:lb-topbar|link-brain-file)\]", stripped):
            in_callout = True
            continue
        if in_callout and stripped.startswith(">"):
            continue
        in_callout = False
        if not stripped:
            continue
        (machine if MACHINE_FRAGMENT.search(stripped) else human).append(line.rstrip("\r"))
    return human, machine


def append_moved_comment(block: str, lines: list[str]) -> str:
    """把块外手写搬进留言层（COMMENTS_END 前）。搬进去后就在留言层里了，下次不再算块外（幂等）。"""
    if not lines:
        return block
    now = datetime.now()
    # 一行一条留言：留言层的解析只认每条的第一行，几段并成一条会让后几段在留言视图里看不见
    new: list[str] = []
    for n, line in enumerate((x.strip() for x in lines if x.strip()), 1):
        lead = "（重写笔记时从正文外搬来）" if n == 1 else ""
        new += ["> [!link-brain-comment]", f"> 「{now:%Y%m%d} 人」{lead}{line}",
                f"<!-- link-brain: id=moved-{now:%Y%m%d%H%M%S}-{n} actor=human target=none status=open -->"]
    if not new:
        return block
    end = block.rfind(COMMENTS_END)
    if end == -1:
        return block.rstrip("\n") + "\n" + "\n".join(new) + "\n" + COMMENTS_END
    head = block[:end].rstrip("\n")
    return head + "\n" + "\n".join(new) + "\n" + block[end:]


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


def _is_link_only(note_text: str | None) -> bool:
    """附言是不是「只有一条分享链接、没别的话」——是的话就不该在留言层留一条噪音 cmt1。

    去掉所有 URL 后，只剩空白 / 标点 / 小红书那句「先复制这段文字…」类模板 = 视为纯链接。
    """
    if not note_text:
        return True
    from .adapters.xiaohongshu import URL_RE

    residual = URL_RE.sub("", note_text)
    residual = re.sub(r"(先复制这段文字|再进【?小红书】?查看完整笔记|打开【?小红书】?浏览笔记|这段文字复制好)", "", residual)
    residual = re.sub(r"[\s，。、；：！？…·\-—|｜/\\【】\[\]（）()<>「」]+", "", residual)
    return not residual


_AUTO_LINK_CMT_RE = re.compile(
    r"> \[!link-brain-comment\]\n> 「\d+ [^」]+」(?P<text>.*)\n"
    r"<!-- link-brain: id=cmt1 actor=human target=none status=open -->\n?"
)


def tidy_link_comments() -> dict[str, Any]:
    """扫全库可见笔记，去掉纯链接的自动 cmt1。返回 {scanned, cleaned, notes}。"""
    vis = storage.visible_dir()
    cleaned: list[str] = []
    scanned = 0
    if vis.is_dir():
        for path in sorted(vis.glob("*.md")):
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            new_text, changed = strip_auto_link_comment(text)
            if changed:
                storage.atomic_write_text(path, new_text)
                cleaned.append(path.name)
    return {"scanned": scanned, "cleaned": len(cleaned), "notes": cleaned}


def strip_auto_link_comment(note_text: str) -> tuple[str, bool]:
    """去掉自动生成的、纯链接的 cmt1 留言（Owner 2026-09-16：旧笔记顶上那条短链留言噪音）。

    只动**自动生成**的 cmt1（`actor=human target=none`）且它去掉链接后没剩真话的；
    她手写的留言、或带真话的 cmt1 一律不碰。
    """
    block, _ = split_layers(note_text)
    if not block:
        return note_text, False
    m = _AUTO_LINK_CMT_RE.search(block)
    if not m:
        return note_text, False
    without_links = re.sub(r"\[[^\]]*\]\([^)]*\)", "", m.group("text"))
    if not _is_link_only(without_links):  # 去掉 md 链接后还剩真话 → 不是纯链接，不删
        return note_text, False
    new_block = block[: m.start()] + block[m.end():]
    return note_text.replace(block, new_block, 1), True


def render_comments_block(note_text: str | None, note_links: list[dict[str, Any]]) -> str:
    lines = [COMMENTS_START]
    # 附言只是分享链接（投喂时粘的那条）就不留 cmt1——留言层留给真正的话（Owner 2026-09-16）。
    if note_text and not _is_link_only(note_text):
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
    video = next((m for m in manifest.get('media', []) if m.get('role') == 'video' and m.get('file') and m.get('download_status') == 'ok'), None)
    remote = (note.get('video') or {}).get('video_url')
    if not entries and not video and not remote:
        return "", False

    total = len(entries)
    parts = ['<section class="lb-media"><div class="lb-carousel">']
    if video or remote:
        src = '../../' + _img_srcs(object_rel, video['file'])[0] if video else remote
        poster = '../../' + _img_srcs(object_rel, entries[0]['file'])[0] if entries else ''
        # 批次 D · N6：视频一出来就按自己的比例占位（没有就按封面），不再是灰色横条
        dims = _dims(video) or (_dims(entries[0]) if entries else None)
        style = f"width:100%;height:auto;max-height:75vh;aspect-ratio:{dims[0]} / {dims[1]}" if dims else "width:100%;max-height:75vh"
        parts.append(f'<figure class="lb-slide"><video controls preload="metadata" playsinline poster="{_safe(poster)}" src="{_safe(src)}" style="{style}">视频无法播放，请打开原文</video></figure>')
    for i, entry in enumerate(entries, 1):
        src, _ = _img_srcs(object_rel, entry["file"])
        parts += [
            '<figure class="lb-slide">',
            f'<img src="../../{_safe(src)}"{_dims_attr(entry)} loading="lazy" alt="图片 {i} / {total}">',
            f'<figcaption class="lb-counter">{i} / {total}</figcaption>' if total > 1 else "",
            "</figure>",
        ]
    parts.append("</div>")
    if note.get("kind") == "video" and not video:
        parts.append('<div class="lb-video-badge">视频 · '+('在线播放' if remote else '未下载')+'</div>')
    parts.append("</section>")
    return "".join(parts), True


# Markdown 里这些字符出现在行首会变成标题/列表/引用，正文照抄会走样，转义掉。
LEADING_MD_RE = re.compile(r"^(\s*)([#>\-+*=]|\d+[.)])")


def _body_markdown(text: str) -> str:
    """正文渲染成**纯 Markdown**（不再包在 <div> 里）。

    Owner 2026-09-05：包在 HTML 块里的正文，Obsidian 既不给高亮（`==` 在 HTML 块内不解析）
    又一点就掉进源码模式。搬出来之后正文是真 Markdown——能选、能划重点、能被搜索命中。
    左图右文改由 CSS 让 `.lb-media` 浮到左边实现，视觉上和原来一样。
    """
    text = TOPIC_TOKEN_RE.sub("", text or "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return "（无正文）"
    out = []
    for para in re.split(r"\n\s*\n", text):
        lines = [LEADING_MD_RE.sub(r"\1\\\2", ln) for ln in para.split("\n") if ln.strip()]
        if lines:
            out.append("\n".join(lines))  # 段内换行原样留着，Obsidian 会当软换行
    return "\n\n".join(out)


def _body_html(text: str) -> str:
    """正文渲染成 HTML 段落（Owner 2026-09-15：要真·左右两栏、图片作者固定、正文评论右栏可滑，
    就必须把这几块关进真容器；正文一旦是 Markdown，Obsidian 遇空行闭合 HTML 块，容器就散了。
    所以正文改回 HTML `<p>`。代价：原生 `==高亮==` 失效（改走 `<mark>`）；全文搜索不受影响。"""
    text = TOPIC_TOKEN_RE.sub("", text or "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return '<div class="lb-body"><p>（无正文）</p></div>'
    paras = []
    for para in re.split(r"\n\s*\n", text):
        lines = [_safe(ln) for ln in para.split("\n") if ln.strip()]
        if lines:
            paras.append("<p>" + "<br>".join(lines) + "</p>")
    return '<div class="lb-body">' + "".join(paras) + "</div>"


HIGHLIGHT_RE = re.compile(r"==([^=\n]{1,300})==")
MARK_RE = re.compile(r"<mark>(.*?)</mark>", re.S)
# 1015 她：划重点默认黄色，可以换几种颜色——非黄色的写成 <mark class="lb-hl-绿">（默认黄 = 不带 class，和以前的 <mark> 一样）
HL_COLORS = ("yellow", "green", "blue", "pink", "purple")
ANY_MARK_RE = re.compile(r'<mark(?:\s+class="lb-hl-([a-z]+)")?>(.*?)</mark>', re.S)


def mark_open(color: str | None = None) -> str:
    """<mark> 开标签：黄色（默认）不带 class，别的颜色带 class="lb-hl-<颜色>"。"""
    c = (color or "yellow").strip().lower()
    return "<mark>" if c not in HL_COLORS or c == "yellow" else f'<mark class="lb-hl-{c}">'


def collect_highlight_colors(text: str | None) -> dict[str, str]:
    """已划的重点里不是默认黄色的：{原文片段: 颜色}（重渲染时照原色贴回）。"""
    out: dict[str, str] = {}
    for color, esc in ANY_MARK_RE.findall(text or ""):
        raw = html.unescape(esc).strip()
        if raw and color and color in HL_COLORS and color != "yellow":
            out.setdefault(raw, color)
    return out


def existing_content_layer(text: str | None) -> str | None:
    """旧可见 md 里 content 层那一段（重渲染时只有它会被重写）。"""
    if not text:
        return None
    start = text.find(CONTENT_START)
    end = text.find(CONTENT_END)
    if start == -1 or end == -1 or end < start:
        return None
    return text[start:end + len(CONTENT_END)]


def collect_highlights(text: str | None) -> list[str]:
    """把已划的重点收集成**原文片段**（长的排前，避免短的先吃掉长的）。

    Owner 2026-09-15：正文改成 HTML 后，高亮走 `<mark>`（她命令加的、或在源码模式手写的都认）；
    仍兼容旧的 `==重点==`。marks 存在 md 里，每次 render 从上一版收集、贴回去——自持久，不另建存储。
    """
    if not text:
        return []
    seen: list[str] = []
    for _color, esc in ANY_MARK_RE.findall(text):
        raw = html.unescape(esc).strip()
        if raw and raw not in seen:
            seen.append(raw)
    for phrase in HIGHLIGHT_RE.findall(text):
        cleaned = phrase.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return sorted(seen, key=len, reverse=True)


_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")


def _find_in_text(html_text: str, needle: str, start: int = 0, end: int | None = None) -> int:
    """在 html_text[start:end] 里找 needle，只认**标签之外的文字段**（不落进 alt="图片 1 / 3" 这种属性里），
    也不落在已有的 <mark>…</mark> 里面；needle 不跨标签。找不到返回 -1。（批次 D · N10）"""
    if not needle:
        return -1
    end = len(html_text) if end is None else end
    pos, depth = 0, 0
    for part in _TAG_SPLIT_RE.split(html_text):
        seg_start, pos = pos, pos + len(part)
        if part.startswith("<") and part.endswith(">"):
            low = part.lower()
            if low.startswith("<mark"):
                depth += 1
            elif low.startswith("</mark"):
                depth = max(0, depth - 1)
            continue
        if depth or pos <= start or seg_start >= end:
            continue
        lo = max(seg_start, start)
        hi = min(pos, end)
        idx = html_text.find(needle, lo, hi)
        if idx != -1:
            return idx
    return -1


def reapply_highlights(content: str, highlights: list[str], colors: dict[str, str] | None = None) -> str:
    """重渲染后把重点贴回去，包成 `<mark>`。

    正文是转义过的 HTML，所以按**转义后**的片段匹配。只做原样匹配：原文变了（作者编辑过）
    就悄悄丢掉那条，不猜。已经在 `<mark>` 里的不重复包；只在标签外的文字里找（批次 D：以前会包进 alt 属性、把 HTML 写坏）。
    """
    for phrase in highlights:
        if not phrase:
            continue
        esc = _safe(phrase)
        if re.search(r'<mark(?:\s+class="lb-hl-[a-z]+")?>' + re.escape(esc) + "</mark>", content):
            continue
        index = _find_in_text(content, esc)
        if index == -1:
            continue
        content = content[:index] + mark_open((colors or {}).get(phrase)) + esc + "</mark>" + content[index + len(esc):]
    return content


def set_highlights(item_id: str, phrases: list[str], *, remove: bool = False, color: str | None = None) -> dict[str, Any]:
    """给一篇笔记正文加 / 去几处高亮，一次读、全部改完再原子写一次（批次 D · N10）。

    返回 {changed: [...], missing: [...], already: [...], visible: Path}。加 = 只在 content 层的标签外文字里找；
    去 = 拆掉 `<mark>片段</mark>`。下次 render 会从 `<mark>` 收集、原样贴回，所以改动能持久。
    1015：color = 颜色（默认黄）；已经划过的再给一个不同颜色 = 换色（算 changed）。
    """
    from . import storage

    src_id = item_id[4:] if item_id.startswith("xhs-") else item_id
    meta_path = storage.object_dir("xiaohongshu", src_id) / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    visible = storage.vault_root() / meta["visible_note"]
    text = visible.read_text(encoding="utf-8")
    out: dict[str, Any] = {"changed": [], "missing": [], "already": [], "visible": visible}
    new = text
    for raw in phrases:
        phrase = (raw or "").strip()
        if not phrase:
            continue
        esc = _safe(phrase)
        marked = mark_open(color) + esc + "</mark>"
        any_marked = re.compile(r'<mark(?:\s+class="lb-hl-[a-z]+")?>' + re.escape(esc) + "</mark>")
        if remove:
            if not any_marked.search(new):
                out["missing"].append(phrase)
                continue
            new = any_marked.sub(lambda _m: esc, new)
            out["changed"].append(phrase)
            continue
        start, end = new.find(CONTENT_START), new.find(CONTENT_END)
        if start == -1 or end == -1:
            out["missing"].append(phrase)
            continue
        if marked in new[start:end]:
            out["already"].append(phrase)
            continue
        hit = any_marked.search(new, start, end)
        if hit:                                   # 换色
            new = new[:hit.start()] + marked + new[hit.end():]
            out["changed"].append(phrase)
            continue
        idx = _find_in_text(new, esc, start, end)
        if idx == -1:
            out["missing"].append(phrase)
            continue
        new = new[:idx] + marked + new[idx + len(esc):]
        out["changed"].append(phrase)
    if new != text:
        storage.atomic_write_text(visible, new)
    return out


def set_highlight(item_id: str, phrase: str, *, remove: bool = False) -> tuple[Path, bool]:
    """给一篇笔记的正文加/去一处高亮（Owner 2026-09-15）。set_highlights 的单句包装，返回 (可见 md 路径, 是否改动)。"""
    r = set_highlights(item_id, [phrase], remove=remove)
    return r["visible"], bool(r["changed"])


def _author_html(note: dict[str, Any]) -> str:
    """作者那一行（圆点 + 昵称 + 日期）。这块没人要编辑，留在 HTML 里。
    10-04 她定：IP 属地（ip_location）不在可见笔记里显示；RAW（source.json）里照旧留着，重渲染即去掉旧笔记里的。"""
    author = (note.get("author") or {}).get("nickname") or "匿名"
    meta = _date(note.get("published_at")) or ""
    return "".join([
        '<div class="lb-author-row"><div class="lb-author-dot" aria-hidden="true"></div><div class="lb-author-copy">',
        f'<div class="lb-author-name">{_safe(author)}</div>',
        f'<div class="lb-post-meta">{_safe(meta)}</div>' if meta else "",
        "</div></div>",
    ])


def _fill_view(source: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any] | None:
    """1009：评论补齐的现状（设置楼数、缺口、后台在补 / 已放弃）。读不到就退回旧口径（只看 comment_load）。"""
    try:
        from . import comment_fill
        sid = meta.get("source_id") or source.get("source_id")
        state = comment_fill.load_state(meta.get("source") or source.get("source") or "xiaohongshu", sid) if sid else {}
        return comment_fill.view_for_render(source, state)
    except Exception:  # noqa: BLE001 - 渲染不能被这一行带崩
        return None


def _comments_html(
    note: dict[str, Any], comments: list[dict[str, Any]], manifest: dict[str, Any], object_rel: str,
    capture: dict[str, Any] | None = None, view: dict[str, Any] | None = None,
) -> str:
    """标签 + 互动 + 原站评论树。结构复杂又不用编辑，继续走 HTML。"""
    parts = [
        '<section class="lb-detail">',
        _tag_html(note.get("hashtags") or []),
        _engagement_html(note),
        '<div class="lb-comments">',
        _restricted_note_html(view),
        _comments_note_html(capture, comments, view),
    ]
    cl = (capture or {}).get("comment_load") or {}
    gap_reasons = {str(g.get("comment_id") or ""): str(g.get("reason") or "")
                   for g in (cl.get("gaps") or [])}
    try:
        floor_limit = int(cl.get("floor_limit")) if cl.get("floor_limit") is not None else None
    except (TypeError, ValueError):
        floor_limit = None
    if view is not None:
        gap_reasons = dict(view.get("gap_reasons") or {})
        floor_limit = int(view.get("floors") or 10)
    if comments:
        parts.extend(_comment_html(c, object_rel, manifest, gap_reasons=gap_reasons, floor_limit=floor_limit,
                                   scoped=view is not None) for c in comments)
    else:
        # 批次 D · N14：原帖有评论、这次没存下来 ≠ 暂无评论
        n = (note.get("engagement") or {}).get("comment_count")
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            parts.append(f'<div class="lb-empty">原帖有 {n} 条评论，这次没存下来'
                         + FETCH_COMMENTS_ACT.format(label="现在抓") + "</div>")
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
    files = _attachments_md(note.get("attachments") or [], object_rel)
    return ["> [!link-brain-file]", *files] if files else []


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
    cls = "lb-note" if has_media else "lb-note lb-no-media"

    # Owner 2026-09-15：真·左右两栏——左栏（图片+作者）sticky 固定，右栏（正文+评论）随页滚动。
    # 关键：整块 `.lb-note` 必须是**一个连续 HTML 块、内部没有空行**，否则 Obsidian 遇空行闭合它，
    # 左右容器就散了（这正是 09-05 float 版的根因）。所以正文改成 `_body_html`。
    # 顶上灰字（原文/机读版/附件）仍是 Markdown、放在 HTML 块**外面**（内部链接要 Obsidian 解析）。
    author = _author_html(note)
    title = f'<h2 class="lb-note-title">{_safe(note.get("title") or meta.get("title") or "")}</h2>'
    body = _body_html(note.get("body") or "")
    if note.get('transcript'):
        body += '<details class="lb-transcript"><summary>视频文字稿</summary>' + _body_html(note['transcript']) + '</details>'
    if note.get('screen_text'):
        body += '<details class="lb-transcript"><summary>视频画面文字</summary>' + _body_html(note['screen_text']) + '</details>'
    detail = _comments_html(note, comments, manifest, object_rel, source.get("capture"), _fill_view(source, meta))
    # Owner 2026-09-15：头像/作者在**正文上方**（右栏顶部），不跟图片在左栏。
    # 左栏只有图片、sticky 固定；右栏 = 作者 → 正文 → 评论，随页滚动。
    # 批次 D · N15：.lb-note 带 data-lb-item，图片导航按它记住每篇钉没钉 / 第几张 / 正文滚到哪
    item_attr = f' data-lb-item="{_safe(meta.get("item_id") or "")}"' if meta.get("item_id") else ""
    if has_media:
        note_html = (
            f'<div class="{cls}"{item_attr}>'
            f'<div class="lb-side">{media}</div>'
            f'<div class="lb-main">{author}<div class="lb-scroll">{title}{body}{detail}</div></div>'
            f"</div>"
        )
    else:
        note_html = f'<div class="{cls}"{item_attr}><div class="lb-main">{author}<div class="lb-scroll">{title}{body}{detail}</div></div></div>'

    # `.lb-note` 必须是**一整块、内部零换行**的 HTML——任何文本字段（评论/正文/标题）里
    # 带的换行都会被 Obsidian 当成空行、把 <div> 提前闭合，左右两栏就散了（2026-09-17 Owner 报的）。
    # 正文已在 _body_html 里把换行转 <br>，评论等没转——这里统一兜底，保证整块单行。
    note_html = note_html.replace("\r", "").replace("\n", "<br>")

    parts = [CONTENT_START]
    parts.extend(_meta_md(note, meta, object_rel))
    parts.append("")
    parts.append(note_html)
    parts.append(CONTENT_END)
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
    data = _tolerant_yaml(m.group(1))
    return data if isinstance(data, dict) else {}


_TOP_KEY_RE = re.compile(r"([^\s:#-][^:]*?):(?:\s+(.*))?$")


def _tolerant_yaml(block: str) -> dict[str, Any] | None:
    """frontmatter → dict；整段 YAML 解析不了时逐个顶层键再试（1001，审计 ui-5）。

    她在源码模式手写 `comment: 注意: 要回看` 这种（值里带「冒号+空格」）整段 YAML 就失效；
    以前当成没有 frontmatter，接着被当成「别人的文件」改名、手写键全丢。
    这里单行的 `键: 值` 解析不了就把值当原样字符串；还有别的解析不了的返回 None（= 写坏了，调用方原样保留）。
    """
    try:
        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else ({} if data is None else None)
    except yaml.YAMLError:
        pass
    groups: list[list[str]] = []
    for line in block.splitlines():
        if line.strip() and not line[0].isspace() and not line.startswith(("-", "#")):
            groups.append([line])
        elif groups:
            groups[-1].append(line)
        elif line.strip() and not line.lstrip().startswith("#"):
            return None
    out: dict[str, Any] = {}
    for group in groups:
        try:
            part = yaml.safe_load("\n".join(group))
        except yaml.YAMLError:
            part = None
        if isinstance(part, dict):
            out.update(part)
            continue
        m = _TOP_KEY_RE.match(group[0])
        if len([x for x in group if x.strip()]) == 1 and m and m.group(2):
            out[m.group(1).strip()] = m.group(2).strip()
            continue
        return None
    return out


def frontmatter_broken(text: str | None) -> bool:
    """有 frontmatter 块、但连逐键容错都解析不了。"""
    m = FRONTMATTER_RE.match(text or "")
    return bool(m) and _tolerant_yaml(m.group(1)) is None


_ITEM_ID_RE = re.compile(r"(?m)^link_brain:[ \t]*\r?\n(?:[ \t]+.*\r?\n)*?[ \t]+item_id:[ \t]*([^\s#]+)")


def frontmatter_item_id(text: str | None) -> str | None:
    """这份 md 属于哪个对象：先按 YAML 读，YAML 写坏了退回正则找 link_brain 下的 item_id 行。"""
    block = parse_frontmatter(text).get("link_brain")
    if isinstance(block, dict) and block.get("item_id"):
        return str(block["item_id"])
    m = FRONTMATTER_RE.match(text or "")
    hit = _ITEM_ID_RE.search(m.group(1) + "\n") if m else None
    return hit.group(1).strip("'\"") if hit else None


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
    # 已有 tags 是用户可编辑属性；包括主动清空，重渲染不得复活删除的标签。
    if 'tags' in parse_frontmatter(existing_text):
        tags = existing_tags(existing_text)
    fm = [
        "---",
        "cssclasses: [link-brain, xhs-note]",
        "tags: " + json.dumps(tags, ensure_ascii=False),
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
    if frontmatter_broken(existing_text):
        # 1001（审计 ui-5）：她手写的 frontmatter 连逐键容错都解析不了——整段原样保留，别重写成机器版、丢她的键
        fm = FRONTMATTER_RE.match(existing_text).group(0).rstrip("\r\n").split("\n")

    comments_block, _ = split_layers(existing_text)
    if comments_block is None:
        comments_block = render_comments_block(meta.get("note"), note.get("links") or [])
    else:
        comments_block = _upgrade_comments_block(comments_block)
    stray_human, _ = stray_human_lines(existing_text)   # 批次 D · F1-c：块外手写搬进留言层，不再被重写吞掉
    if stray_human:
        comments_block = append_moved_comment(comments_block, stray_human)

    content = render_content_block(source=source, manifest=manifest, meta=meta, object_rel=object_rel)
    # Owner 在正文里划的 ==重点== 要跨重渲染活下来（2026-09-05 定的）
    _layer = existing_content_layer(existing_text)
    content = reapply_highlights(content, collect_highlights(_layer), collect_highlight_colors(_layer))
    # 原文 · 机读版 放**正文之上**（Owner 2026-09-17：这条入口该在顶上，不该沉到底）。
    # 包一层无框 callout [!lb-topbar] 只为能上样式（内部链接在 callout 里照样解析）——
    # 否则纯 markdown 链接吃主题默认色，Owner 反馈"发灰"。
    topbar = " · ".join(x for x in [f"[原文]({source_open_url(note, meta)})" if source_open_url(note, meta) else "", f"[[{object_rel}/derived/agent.md|机读版]]"] if x)
    parts = ["\n".join(fm)]
    if topbar:
        parts.append("> [!lb-topbar]\n> " + topbar)
    parts += [content, comments_block, _annotate_block(meta)]
    return "\n\n".join(parts) + "\n"


def _annotate_block(meta: dict[str, Any]) -> str:
    """正文底部的批注块：一小段 bootstrap，载入共享 annotate-view.js（读写 notes.json）。
    批注/⭐ 全存 sidecar，不进正文；每次重渲染这段模板照样贴回来，数据在 sidecar 不丢。"""
    item_id = json.dumps(meta["item_id"])
    note_path = json.dumps(f"_archive/{meta['source']}/{meta['source_id']}/notes.json")
    return (
        "```dataviewjs\n"
        f"const itemId = {item_id};\n"
        # 仓可能挂在别的库的子目录里（LER Vault/知识库【小红书】/）：往上找第一个带 _archive 的目录当仓根
        "let lbRoot = dv.current()?.file?.folder || \"\";\n"
        "while (lbRoot && !app.vault.getAbstractFileByPath(lbRoot + \"/_archive\")) lbRoot = lbRoot.includes(\"/\") ? lbRoot.slice(0, lbRoot.lastIndexOf(\"/\")) : \"\";\n"
        "const lbPath = p => lbRoot ? lbRoot + \"/\" + p : p;\n"
        f"const notePath = lbPath({note_path});\n"
        "try {\n"
        '  const code = await app.vault.adapter.read(lbPath("_archive/annotate-view.js"));\n'
        "  // 脚本里有顶层 await，必须用 AsyncFunction 构造（普通 Function 会当语法错误抛）\n"
        "  const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;\n"
        '  await new AsyncFunction("dv", "app", "itemId", "notePath", code)(dv, app, itemId, notePath);\n'
        "} catch (e) { dv.paragraph(\"批注块暂不可用：\" + (e.message || e)); }\n"
        "```"
    )


_URL_TAIL = ".,;:!?'\"*_~"


def suggested_link_url(raw: Any) -> str:
    """小模型给的链接 → 干净的 URL：从 http(s) 开头截到第一个空白 / 全角括号 / 中文字符 / 中文标点为止
    （和 adapters.xiaohongshu.URL_RE 同一把尺子），再去掉句末的半角标点。不是 http(s) 开头就返回空串。"""
    from .adapters.xiaohongshu import URL_RE

    m = URL_RE.match(str(raw or "").strip())
    return m.group(0).rstrip(_URL_TAIL) if m else ""


def link_label(url: str, limit: int = 60) -> str:
    """链接的显示文字：去掉 http(s):// 和结尾的 /，太长截断；转义会被当成强调的 * _。"""
    text = re.sub(r"^https?://", "", url, flags=re.I).rstrip("/") or url
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return re.sub(r"([*_])", r"\\\1", text)


AGENT_SOFT_LIMIT = 10000
AGENT_MIN_ROOM = 3000
# 全文超过软上限时依次压：评论 → 图片 → 画面文字（正文、概要不动）。每档 = (评论条数, 评论字数, 图片总字数, 画面文字字数)
_AGENT_BUDGETS = [
    (30, 3000, 3000, 1500),
    (20, 2000, 3000, 1500),
    (12, 1000, 3000, 1500),
    (12, 1000, 1500, 1500),
    (12, 1000, 1500, 800),
    (6, 500, 800, 400),
]


def _url_key(url: str) -> str:
    return re.sub(r"^https?://", "", str(url or "").strip(), flags=re.I).rstrip("/").lower()


def agent_info_line(note: dict[str, Any], meta: dict[str, Any]) -> str:
    """标题下一行：来源 · 作者 · 发布日期 · 点赞/收藏/评论 · 版本（原「数据点」「元信息」两节合并；None 不写）。"""
    parts = []
    if meta.get("canonical_url") or note.get("canonical_url"):
        parts.append(f"来源 {meta.get('canonical_url') or note.get('canonical_url')}")
    nickname = ((note.get("author") or {}).get("nickname") or "").strip()
    if nickname:
        parts.append(f"作者 {nickname}")
    if note.get("published_at") or meta.get("published_at"):
        parts.append(f"发布 {_date(note.get('published_at') or meta.get('published_at'))}")
    engagement = note.get("engagement") or {}
    names = {"liked": "赞", "collected": "藏", "comment_count": "评", "shared": "转"}
    stats = [f"{names.get(k, k)} {v}" for k, v in engagement.items() if v is not None and str(v) != ""]
    if stats:
        parts.append(" / ".join(stats))
    if meta.get("current_version"):
        parts.append(f"v{meta['current_version']}")
    if meta.get("images_complete") is False:
        parts.append("图片没下全")
    if meta.get("comments_complete") is False:
        parts.append("评论没读全")
    return " · ".join(parts)


def render_agent_md(
    *,
    source: dict[str, Any],
    vision: dict[str, Any],
    meta: dict[str, Any],
    extracted: dict[str, Any] | None = None,
) -> str:
    """机读版（给 AI 读）。10-08 批次 B 精简：空节不写、数据点 / 元信息并成标题下一行、图片和评论去噪限额，
    全文软上限约 1 万字（超了依次压评论 → 图片 → 画面文字，正文和概要不动）。规则细节在 agentmd.py。"""
    from rapidfuzz import fuzz

    from . import agentmd

    note = source["note"]
    title = note.get("title") or meta.get("title") or "（无标题）"
    ex = extracted or {}
    comments = source.get("comments") or []
    labeled = llm_mod.comment_labels(comments)
    label_by_cid = {str(c.get("comment_id") or ""): label for label, c in labeled if c.get("comment_id")}

    head = [f"# {title}"]
    info = agent_info_line(note, meta)
    if info:
        head += ["", info]

    fixed: list[tuple[str, list[str]]] = []   # 不参与压缩的节
    summary = str(ex.get("summary") or "").strip()
    if summary:
        fixed.append(("## 概要", [summary]))
    summary_norm = agentmd.norm(summary)
    key_points = [str(x) for x in ex.get("key_points") or [] if str(x).strip()]
    if summary_norm:
        key_points = [x for x in key_points if not (agentmd.norm(x) in summary_norm
                                                    or fuzz.partial_ratio(agentmd.norm(x), summary_norm) >= 90)]
    if key_points:
        fixed.append(("## 重要细节", [f"- {x}" for x in key_points]))

    # 外链：同一个 URL 只写一次；没有 http 链接的「小模型建议」不写
    link_lines: list[str] = []
    seen_urls: dict[str, int] = {}
    for x in note.get("links") or []:
        url = x.get("url")
        key = _url_key(url)
        if not url or key in seen_urls:
            continue
        where = str(x.get("where") or "")
        if where.startswith("comment:"):
            where = f"评论 {label_by_cid.get(where.split(':', 1)[1], '')}".strip()
        elif where == "body":
            where = "正文"
        seen_urls[key] = len(link_lines)
        link_lines.append(f"- [{x.get('text') or link_label(url)}]({url})" + (f"（{where}）" if where else ""))
    for att in note.get("attachments") or []:
        target = att.get("file") or att.get("url") or ""
        doc_id = att.get("doc_id")
        md_path = storage.derived_dir("xiaohongshu", meta["source_id"]) / "attachments" / f"{doc_id}.md" if meta.get("source_id") else None
        from urllib.parse import quote
        links_text = f"[下载文件](../{quote(target, safe='/')})" if att.get("file") else (f"[来源]({target})" if target else "")
        if md_path and md_path.is_file():
            links_text += f" · [附件正文 Markdown](attachments/{doc_id}.md)"
        link_lines.append(f"- 附件：{attachment_label(att)} {links_text}")
    for x in ex.get("links_worth_opening") or []:
        why = x.get("why") or ""
        url = suggested_link_url(x.get("url"))
        if not url:
            continue
        key = _url_key(url)
        if key in seen_urls:
            if why and seen_urls[key] >= 0:
                link_lines[seen_urls[key]] += f" — 小模型建议：{why}"
                seen_urls[key] = -1
            continue
        seen_urls[key] = -1
        # 第 6 批：链接只包 URL 本身，建议文字放链接后面当普通文本（以前 URL 和全角括号粘一起，Obsidian 认成一整条链接、点不开）
        link_lines.append(f"- [{link_label(url)}]({url}) — 小模型建议" + (f"：{why}" if why else ""))
    if link_lines:
        fixed.append(("## 外链", link_lines))

    body = note.get("body") or ""
    if body.strip():
        fixed.append(("## 原文", [body]))

    all_images = (vision or {}).get("images") or []
    # 0927 Owner：评论区图片的识别结果挂到它所在的那条评论下面，不混在正文图片里
    comment_images: dict[str, list[dict[str, Any]]] = {}
    images = []
    for image in all_images:
        m = re.search(r"comment-([0-9a-f]+)-\d+\.", image.get("asset") or "")
        if m:
            comment_images.setdefault(m.group(1), []).append(image)
        else:
            images.append(image)

    def origin(asset: str) -> str:
        # 10-03：写收藏库内的相对路径，不写本机绝对路径（远程阅读会把机读版原样发给远端，远端用 read_asset 按它看原图）
        if not meta.get("source_id"):
            return asset
        pic = storage.object_dir("xiaohongshu", meta["source_id"]) / asset
        try:
            return pic.relative_to(storage.vault_root()).as_posix()
        except ValueError:
            return asset

    # 0926 Owner：机读版查重——文字稿 / 画面文字里跟正文或前面重复的句子只留一次
    transcript = dedupe_lines(agentmd.merge_stutter(note.get("transcript") or ""), body)
    if len(transcript) > agentmd.TRANSCRIPT_PARAGRAPH:
        transcript = agentmd.paragraphs(transcript)
    screen = agentmd.screen_units(note.get("screen_text") or "", body + "\n" + transcript,
                                  legacy=not note.get("screen_v"))

    # 评论：先算出每楼要写的行，再按预算挑
    valuable = {x.get("id"): x.get("why") or "" for x in ex.get("valuable_comments") or []}
    noise = set(ex.get("ads_or_noise") or [])
    author_id = str((note.get("author") or {}).get("user_id") or "")
    comment_rows: dict[str, list[str]] = {}
    with_text: set[str] = set()
    for label, c in labeled:
        indent = "  " if "." in label else ""
        mark = f"（值得看：{valuable[label]}）" if label in valuable else ""
        nickname = (c.get("author") or {}).get("nickname") or "匿名"
        if author_id and str((c.get("author") or {}).get("user_id") or "") == author_id:
            nickname += "（作者）"
        gap = ""
        if "." not in label:
            try:
                short = int(c.get("sub_comment_count") or 0) - len(c.get("sub_comments") or [])
            except (TypeError, ValueError):
                short = 0
            if short > 0:
                gap = f"（还缺 {short} 条回复）"
        text = re.sub(r"\s*\n\s*", " ", str(c.get("text") or "")).strip()
        rows = [f"{indent}- [{label}] {nickname}：{text}{mark}{gap}"]
        for image in comment_images.get(str(c.get("comment_id") or ""), []):
            asset = str(image.get("asset") or "")
            got = agentmd.comment_image_text(image)
            m = re.search(r"-(\d+)\.\w+$", asset)
            name = f"评论图{int(m.group(1))} {agentmd.asset_name(asset)}" if m else agentmd.asset_name(asset)
            note = agentmd.doubt_note(image, origin(asset))
            if got:
                with_text.add(label)
                rows.append(f"{indent}  - {name}：{got}")
            if note and (got or image.get("status") != "ok"):
                rows.append(f"{indent}  - {name} " + (note if got else "识别没成，" + note))
        comment_rows[label] = rows

    cl = (source.get("capture") or {}).get("comment_load") or {}
    gap_line: list[str] = []
    view = _fill_view(source, meta)
    if view is not None:
        if int(view.get("missing") or 0) > 0:
            from .comment_fill import floors_label
            gap_line = [f"（评论读到 {len(comments)} 楼，{floors_label(int(view.get('floors') or 10))}的楼中楼还缺 "
                        f"{view['missing']} 条：{view.get('why') or '没读全'}；下面标「还缺」的楼不全）", ""]
    elif int(cl.get("replies_missing") or 0) > 0:
        from .adapters import xiaohongshu as xhs
        gaps = cl.get("gaps") or []
        main = max(gaps, key=lambda g: int(g.get("missing") or 0)).get("reason") if gaps else cl.get("stop_reason")
        gap_line = [f"（评论读到 {cl.get('floors_loaded') or len(comments)} 楼，楼中楼还缺 {cl['replies_missing']} 条："
                    f"{xhs.REPLY_GAP_CN.get(str(main or ''), '没读全')}；下面标「还缺」的楼不全）", ""]

    def build(budget: tuple[int, int, int, int]) -> tuple[str, int]:
        n_comments, n_chars, image_total, screen_total = budget
        sections = list(fixed)
        image_rows = agentmd.image_section(images, origin, image_total)
        if image_rows:
            sections.append(("## 图片 OCR", image_rows))
        if transcript:
            sections.append(("## 视频文字稿", [transcript]))
        if screen:
            sections.append(("## 视频画面文字", agentmd.cap_units(screen, screen_total)))
        if labeled:
            chosen, why = agentmd.select_comments(labeled, author_id=author_id, valuable=set(valuable), noise=noise,
                                                  with_text=with_text, max_count=n_comments, max_chars=n_chars)
            rows = list(gap_line)
            for label, _ in labeled:
                if label in chosen:
                    rows += comment_rows[label]
            skipped = len(labeled) - len(chosen)
            if skipped:
                detail = "，".join(x for x in [f"水话 / 噪音 {why['chatter']} 条" if why["chatter"] else "",
                                                 f"超出上限 {skipped - why['chatter']} 条" if skipped > why["chatter"] else ""] if x)
                rows.append(f"（另有 {skipped} 条评论略去：{detail}）")
            sections.append(("## 评论", rows))
        elif gap_line:
            sections.append(("## 评论", gap_line[:1]))
        lines = list(head)
        squeezable = 0
        for heading, rows in sections:
            lines += ["", heading, ""] + rows
            if heading in ("## 图片 OCR", "## 视频画面文字", "## 评论"):
                squeezable += sum(len(r) + 1 for r in rows)
        return "\n".join(lines), squeezable

    text = ""
    for budget in _AGENT_BUDGETS:
        text, squeezable = build(budget)
        # 正文 / 概要 / 文字稿本身就超了上限时，可压的三节仍给 AGENT_MIN_ROOM 字（不为长口播把评论压到没有）
        if len(text) <= AGENT_SOFT_LIMIT or squeezable <= max(AGENT_SOFT_LIMIT - (len(text) - squeezable), AGENT_MIN_ROOM):
            break
    # 1001 审计 C-2：正文/评论/识图都是别人写的，机读版整份过清洗，别让 Dataview 当代码执行
    return mdsafe.neutralize(text) + "\n"


def brief_summary(source: dict[str, Any], extracted: dict[str, Any] | None = None) -> str:
    """有小模型概要就用它，没有就退回正文前 120 字（Lot 3 行为）。"""
    summary = (extracted or {}).get("summary")
    if summary:
        return summary
    return _first_n_chars((source.get("note") or {}).get("body"), 120)


def snippet_targets() -> list[Path]:
    """CSS 片段该写到哪些 Obsidian 配置目录（批次 D · N2）。

    ① 插件传来的 LINK_BRAIN_OBSIDIAN_DIR（Obsidian 真正的 configDir）；② 收藏库里已经有的 .obsidian；
    ③ 前两样都没有时，往上最多 3 层找带 .obsidian/app.json 的库（收藏库被挂进别的库的子目录）。
    按 resolve() 去重；不再在收藏子目录里凭空建 .obsidian。
    """
    out: list[Path] = []
    seen: set[str] = set()

    def add(d: Path) -> None:
        try:
            key = str(d.resolve()).lower()
        except OSError:
            key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d / "snippets" / "link-brain.css")

    env = os.environ.get("LINK_BRAIN_OBSIDIAN_DIR")
    if env:
        add(Path(env))
    own = storage.vault_root() / ".obsidian"
    if own.is_dir():
        add(own)
    if not out:
        cur = storage.vault_root()
        for _ in range(3):
            cur = cur.parent
            if (cur / ".obsidian" / "app.json").is_file():
                add(cur / ".obsidian")
                break
    return out


def ensure_css_snippet() -> None:
    """Sync managed CSS into the vault so UI changes actually reach existing vaults.（写失败只打 stderr，不挡渲染）"""
    template = Path(__file__).resolve().parent / "assets" / "link-brain.css"
    content = template.read_text(encoding="utf-8")
    for target in snippet_targets():
        try:
            if target.exists() and target.read_text(encoding="utf-8") == content:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            storage.atomic_write_text(target, content)
        except OSError as exc:
            print(f"CSS 片段没写上：{target}（{exc}）", file=sys.stderr)


def render_object(
    source_key: str,
    source_id: str,
    *,
    verbose: bool = False,
    llm: bool = False,
    re_extract: bool = False,
    target: Path | None = None,
    existing_override: str | None = None,
) -> dict[str, Any]:
    """拼可见 md + agent.md。

    批次 D · F1：target = 钉死写回这个路径（restore 用：不改名、不合并、不删原文件）；
    existing_override = 拿这段文本当「旧可见 md」（restore 的 seed）。两者默认 None = 原来的行为。

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
    # 1001（审计 raw-1）：事后解析 / 补查到的附件声明住对象级 attachments-resolved.json，这里只在内存里合并
    source_doc["note"]["attachments"] = attachments_mod.declared_attachments(object_dir, source_doc)
    for att in source_doc["note"].get("attachments") or []:
        got = downloaded.get(att.get("doc_id")) or next((r for r in downloaded.values() if r.get("name") == (att.get("name") or att.get("hint"))), None)
        if got and (object_dir / "attachments" / got["file"]).exists():
            att["doc_id"] = got["doc_id"]
            att["file"] = f"attachments/{got['file']}"
            att["status"] = "downloaded"
            att["bytes"] = got.get("bytes")
            att["sha256"] = got.get("sha256")
    represented = {att.get("doc_id") for att in source_doc["note"].get("attachments") or []}
    for doc_id, got in downloaded.items():
        if doc_id not in represented and (object_dir / "attachments" / got["file"]).is_file():
            source_doc["note"].setdefault("attachments", []).append({"doc_id": doc_id, "name": got.get("name") or got["file"], "file": f"attachments/{got['file']}", "status": "downloaded"})
    report = attachments_mod.update_status(source_key, source_id)
    meta["attachments_status"] = report["status"]

    extracted_doc = llm_mod.load_extracted(source_key, source_id)
    if llm or re_extract:
        stale = re_extract or not extracted_doc or extracted_doc.get("status") != "ok"
        if stale:
            try:
                extracted_doc = llm_mod.extract(source_key, source_id, force=re_extract, verbose=verbose)
            except Exception as exc:  # noqa: BLE001 - 10-04 入档不被阻断：概要出意外，笔记照样写出来，问题记下来当场 / 夜里补
                _soft_fail("enrich.summary", "概要", exc, meta.get("item_id"), meta.get("title"))
    extracted = llm_mod.extracted_data(extracted_doc)

    transcript_path = derived_dir / 'transcript.json'
    transcript_doc = storage.read_json(transcript_path) if transcript_path.exists() else {}
    transcript = transcript_doc.get('text', '')
    source_doc['note']['transcript'] = transcript
    source_doc['note']['screen_text'] = (transcript_doc.get('screen') or {}).get('text', '')
    source_doc['note']['screen_v'] = (transcript_doc.get('screen') or {}).get('v')  # 10-08：v2 起画面文字按 OCR 行存，旧的是一帧一行
    if not (source_doc['note'].get('title') or meta.get('title')):
        fallback = (extracted or {}).get('title') or transcript.split('。')[0] or source_doc['note'].get('body') or next((x.get('ocr') for x in vision_doc.get('images', []) if x.get('ocr')), '')
        title = re.sub(r'\s+', ' ', str(fallback)).strip()[:30] or '视频收藏'
        meta['title'] = title
        source_doc['note']['title'] = title
        storage.write_json(meta_path, meta)
        conn = index_mod.connect()
        conn.execute('UPDATE objects SET title=? WHERE item_id=?', (title, meta['item_id']))
        conn.commit(); conn.close()

    visible_dir = storage.visible_dir()
    visible_dir.mkdir(parents=True, exist_ok=True)
    clean_path = resolve_visible_path(
        visible_dir,
        source_doc["note"].get("title") or meta.get("title") or "",
        source_id,
        meta["item_id"],
    )
    visible_path = Path(target) if target else clean_path

    old_visible = None if target else meta.get("visible_note")
    old_path = storage.vault_root() / old_visible if old_visible else None
    if not target and (old_path is None or not old_path.exists()):
        # 1001（审计 render-8）：meta 记的路径没文件了 = 她在 Obsidian 里改了名或挪了位置。
        # 先按 frontmatter 的 item_id 在可见目录（含子目录）里找回那份，沿用她的名字和位置，别另写一份干净的
        found = find_visible_by_item_id(meta["item_id"])
        if found:
            old_path = found[0]
            if old_path != visible_path:
                meta["visible_note_pinned"] = True  # 她自己定的名字 / 位置：之后标题变了也不挪回去
            if len(found) > 1:
                print(f"[render] {meta['item_id']} 可见目录里有 {len(found)} 份同一篇，沿用最新改动的 "
                      f"{old_path.name}", file=sys.stderr)
    if old_path is not None and old_path.exists() and old_path != visible_path:
        old_text = old_path.read_text(encoding="utf-8")
        if frontmatter_broken(old_text):
            # 1001（审计 ui-5）：YAML 写坏了不等于「别人的文件」——原地保留、不改名，记一笔让人去修
            print(f"[render] 警告：{old_path.name} 的属性（frontmatter）写坏了，原样保留、不改名；"
                  "在 Obsidian 里修好那几行即可", file=sys.stderr)
            visible_path = old_path
        elif meta.get("visible_note_pinned") and frontmatter_item_id(old_text) == meta["item_id"]:
            visible_path = old_path
    elif old_path is not None and old_path.exists() and frontmatter_broken(old_path.read_text(encoding="utf-8")):
        print(f"[render] 警告：{old_path.name} 的属性（frontmatter）写坏了，原样保留；"
              "在 Obsidian 里修好那几行即可", file=sys.stderr)

    # 目标文件上可能已经躺着同一个对象的另一份（改名前后各一份）——先并、再删旧的，别盖掉手写内容
    target_text = None
    if visible_path.exists() and owner_item_id(visible_path) == meta["item_id"]:
        target_text = visible_path.read_text(encoding="utf-8")

    existing_text = target_text
    if old_path is not None:
        if old_path.exists() and old_path != visible_path:
            # 改名的情况：两份文件都在，手写内容取并集再删旧的
            old_text = old_path.read_text(encoding="utf-8")
            existing_text = (
                merge_existing(target_text, old_text) if target_text is not None else old_text
            )
            old_path.unlink()
        elif old_path.exists():
            # 同一个文件：**原文照用**。merge_existing 只留 frontmatter + 留言层，
            # 拿它当 existing_text 会把 content 层（连带 Owner 划的 ==重点==）洗掉。
            existing_text = old_path.read_text(encoding="utf-8")
    if target and visible_path.exists():
        existing_text = visible_path.read_text(encoding="utf-8")
    if existing_override is not None:
        existing_text = existing_override
    elif existing_text:
        # 批次 D · F1-c：块外有手写 / 机器碎片 → 重写前先存一份快照（丢掉的碎片在快照里有原样）
        human, machine = stray_human_lines(existing_text)
        if human or machine:
            from . import history as history_mod
            try:
                history_mod.snapshot(object_dir, existing_text, "render")
            except OSError as exc:
                print(f"[render] 快照没存上：{exc}", file=sys.stderr)
    if target and visible_path.resolve() != clean_path.resolve():
        meta["visible_note_pinned"] = True

    storage.atomic_write_text(
        visible_path,
        render_visible_md(
            source=source_doc,
            manifest=manifest,
            meta=meta,
            object_rel=object_rel,
            existing_text=existing_text,
            extracted=extracted,
        ),
    )

    derived_dir.mkdir(parents=True, exist_ok=True)
    storage.atomic_write_text(
        derived_dir / "agent.md",
        render_agent_md(
            source=source_doc, vision=vision_doc, meta=meta, extracted=extracted
        ),
    )

    rel_visible = str(visible_path.relative_to(storage.vault_root())).replace("\\", "/")
    if meta.get("visible_note") != rel_visible:
        meta["visible_note"] = rel_visible
        storage.write_json(meta_path, meta)

    if verbose:
        print(f"[render] {meta['item_id']} -> {rel_visible}")
    return {"item_id": meta["item_id"], "visible_note": rel_visible, "agent_md": str(derived_dir / "agent.md")}


def _soft_fail(step: str, what: str, exc: Exception, item_id: str | None, title: str | None = None) -> None:
    """识图 / 概要这类「锦上添花」的步骤出了意外：不阻断这篇入档，登记一条（自愈轮 / 「现在修」会重跑这篇）。"""
    print(f"[render] {what}出错（不影响入档）：{type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        from . import problems
        problems.report(step, "TRANSIENT.STEP_CRASHED", f"{what}出错（正文已入档）：{type(exc).__name__}: {exc}",
                        item_id=item_id, title=title)
    except Exception as err:  # noqa: BLE001
        print(f"[render] 问题记录没写上：{err}", file=sys.stderr)


def render_item(
    source_key: str,
    source_id: str,
    *,
    verbose: bool = False,
    llm: bool = False,
    re_extract: bool = False,
    vision: bool = True,
) -> dict[str, Any]:
    # vision=False：只用已有的识图结果重写笔记，不调识图模型（部署时批量更新笔记格式用，不花钱、不联网）
    if vision:
        try:
            vision_mod.build_vision(source_key, source_id, verbose=verbose)
        except FileNotFoundError:
            raise  # 根本没归档过：照旧报给调用方
        except Exception as exc:  # noqa: BLE001 - 10-04 入档不被阻断：识图出意外，用已有结果照样把笔记写出来
            _soft_fail("vision.layer1", "识图", exc, vision_mod._item_id(source_key, source_id))
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
                vision=not getattr(args, "no_vision", False),
            )
        except FileNotFoundError as exc:
            print(f"跳过 {source_key}/{source_id}: {exc}", file=sys.stderr)
            continue
        print(f"{result['item_id']} -> {result['visible_note']}")
    return 0
