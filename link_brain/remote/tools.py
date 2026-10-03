"""四个只读工具：search / read / list / read_asset。全部经 policy 过白名单；没有任何写入、执行、调模型回答的工具。

- search：开放了小红书收藏库（@xhs）时，复用问答的检索（`retrieval.rank_query`：词法 BM25 + 语义 RRF，
  语义层缺 key / 缺索引时自动退回纯词法），结果只留白名单内的路径；用户加的文件夹另做逐文件文本匹配。
- read：读白名单内的文本文件，按字符分页（offset / max_chars → next_offset）。
- read 读到收藏对象里的文本（机读版 / 附件全文 / 批注 / 可见笔记）时，带上这篇的图片清单 `images`；
  `include_images=true` 时顺带附前 N 张图（图片块，同 read_asset 的大小上限）。
- read_asset：读收藏对象里的一张原图，返回 MCP 图片块 + 一段说明。OCR / 识图文字用来找，原图用来判。
- list：不给 path 列开放的根；给了列那个目录（只露出白名单内的文件和通往它们的目录），分页。

返回值都是可 JSON 化的 dict；拒绝时抛 policy.Denied（服务层翻成 isError 结果）。
带图的结果另有一个私有键 `_images: [{"data": bytes, "mime": str}]`，服务层把它摘出来翻成 ImageContent 块。
"""

from __future__ import annotations

import io
import json
import os
import re
import time
from typing import Any

from .policy import XHS_ARCHIVE, XHS_VISIBLE, Denied, Policy, MAX_READ_BYTES, _is_reparse

READ_DEFAULT = 20000
READ_MAX = 100000
LIST_DEFAULT = 200
LIST_MAX = 1000
SEARCH_DEFAULT = 10
SEARCH_MAX = 30
SCAN_FILES_MAX = 5000
SCAN_FILE_BYTES = 2 * 1024 * 1024
SCAN_SECONDS = 6.0
IMAGE_MAX_BYTES = 4 * 1024 * 1024       # 超过就缩
IMAGE_MAX_EDGE = 2048                   # 长边超过就缩
IMAGE_SOURCE_MAX = 40 * 1024 * 1024     # 原图本身大过这个不打开
INCLUDE_DEFAULT = 4
INCLUDE_MAX = 8
INCLUDE_TOTAL_BYTES = 12 * 1024 * 1024  # 一次 read 附图的总字节
_PIL_FORMATS = {"WEBP": "image/webp", "JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif"}
_OBJ = re.compile(r"^_archive/xiaohongshu/([A-Za-z0-9_-]{1,64})/")

TOOLS = [
    {
        "name": "search",
        "description": ("搜索开放给你的收藏和文件夹（只读）。小红书收藏库用关键词 + 语义检索，返回标题、命中摘录和可读路径："
                        "path 是给人看的笔记，agent_md 是机读版全文（含图片文字、评论、附件线索），attachments 是附件全文。"
                        "拿到路径后用 read 读全文。"),
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要找什么：关键词或一句话"},
            "limit": {"type": "integer", "description": f"最多返回几条，默认 {SEARCH_DEFAULT}，最多 {SEARCH_MAX}"}},
            "required": ["query"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "read",
        "description": ("读一个开放的文本文件（.md / .txt；收藏的机读版 agent.md、附件全文、批注 notes.json）。"
                        "大文件分页：返回 next_offset 不为 null 就带上它再读下一页。路径照 search / list 给出的原样写。"
                        "读收藏里的一篇时结果带 images（这篇的图片清单：n、path、宽高），要看哪张就用 read_asset 读那个 path；"
                        f"也可以 include_images=true 顺带附前几张（默认 {INCLUDE_DEFAULT} 张，最多 {INCLUDE_MAX}）。"
                        "图片文字（OCR / 识图）只用来找，细节以原图为准。"),
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "vault 内的相对路径，/ 分隔"},
            "offset": {"type": "integer", "description": "从第几个字符开始，默认 0"},
            "max_chars": {"type": "integer", "description": f"这一页最多多少字符，默认 {READ_DEFAULT}，最多 {READ_MAX}"},
            "include_images": {"type": "boolean", "description": "true = 顺带附上这篇的前几张图片（图片块），默认 false"},
            "max_images": {"type": "integer", "description": f"include_images 时附几张，默认 {INCLUDE_DEFAULT}，最多 {INCLUDE_MAX}"}},
            "required": ["path"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "list",
        "description": "列出开放的文件夹和文件。不给 path 时列出所有开放的根；给 path 列那个文件夹（分页）。",
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件夹的相对路径；留空 = 列开放的根"},
            "offset": {"type": "integer", "description": "分页起点，默认 0"},
            "limit": {"type": "integer", "description": f"这一页最多几项，默认 {LIST_DEFAULT}，最多 {LIST_MAX}"}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "read_asset",
        "description": ("看收藏里的一张原图（返回图片本身 + 路径 / 尺寸 / 字节数）。agent.md 里的图片文字（OCR / 识图）"
                        "可能有错字，只用来找；搜到以后用 read_asset 看原图核对，以原图为准。path 用 read 结果 images 里给出的原样路径"
                        "（形如 _archive/xiaohongshu/<id>/raw/v0001/assets/image-001.webp）。一次一张；超过 "
                        f"{IMAGE_MAX_BYTES // 1024 // 1024} MB 或长边超过 {IMAGE_MAX_EDGE} 的图会等比缩到长边 {IMAGE_MAX_EDGE}（JPEG）再给。"),
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "图片在 vault 内的相对路径，/ 分隔"}},
            "required": ["path"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]
NAMES = {t["name"] for t in TOOLS}


def _is_link(entry: os.DirEntry) -> bool:
    """符号链接或联接点：列目录和搜索时都不跟进去（读的时候 policy 第三道还会再拦一次）。"""
    if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
        return True
    try:
        return _is_reparse(entry.stat(follow_symlinks=False))
    except OSError:
        return True


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _item_titles() -> dict[str, str]:
    try:
        from ..ask import load_items
        return {str(it.get("id", "")).removeprefix("xhs-"): str(it.get("title") or "") for it in load_items()}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- read

def read(policy: Policy, args: dict[str, Any]) -> dict[str, Any]:
    path = args.get("path")
    target = policy.resolve_file(path)
    size = os.path.getsize(target)
    if size > MAX_READ_BYTES:
        raise Denied("TOO_LARGE", f"文件太大（{size // 1024 // 1024} MB），不提供")
    raw = target.read_bytes()
    if b"\x00" in raw[:8192]:
        raise Denied("NOT_TEXT", "不是文本文件")
    text = raw.decode("utf-8", errors="replace")
    offset = _int(args.get("offset"), 0, 0, len(text))
    limit = _int(args.get("max_chars"), READ_DEFAULT, 1, READ_MAX)
    chunk = text[offset:offset + limit]
    end = offset + len(chunk)
    out: dict[str, Any] = {"path": path, "total_chars": len(text), "offset": offset,
                           "next_offset": end if end < len(text) else None, "text": chunk}
    images = image_list(policy, path)
    if images is not None:
        out["images"] = images
        if args.get("include_images") is True:
            want = _int(args.get("max_images"), INCLUDE_DEFAULT, 1, INCLUDE_MAX)
            blobs: list[dict[str, Any]] = []
            attached: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            total = 0
            for img in images[:want]:
                try:
                    data, mime, info = load_image(policy, img["path"])
                except Denied as d:
                    skipped.append({"n": img["n"], "path": img["path"], "error": d.code})
                    continue
                if total + len(data) > INCLUDE_TOTAL_BYTES:
                    skipped.append({"n": img["n"], "path": img["path"], "error": "BUDGET"})
                    continue
                total += len(data)
                blobs.append({"data": data, "mime": mime})
                attached.append({"n": img["n"], "path": img["path"], **info})
            out["attached_images"] = attached
            if skipped:
                out["skipped_images"] = skipped
            out["_images"] = blobs
    return out


# ---------------------------------------------------------------- 图片

def _object_id(policy: Policy, path: str) -> str | None:
    """这段文本属于哪篇收藏：_archive/xiaohongshu/<id>/… 直接取；可见笔记从目录数据里对。"""
    if not policy.xhs:
        return None
    m = _OBJ.match(path)
    if m:
        return m.group(1)
    if not path.startswith(XHS_VISIBLE + "/"):
        return None
    try:
        from ..ask import load_items
        for it in load_items():
            if it.get("note") == path and isinstance(it.get("agent_md"), str):
                m = _OBJ.match(it["agent_md"])
                return m.group(1) if m else None
    except Exception:  # noqa: BLE001 - 对不上就不给清单
        return None
    return None


def _load_json(p) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def image_list(policy: Policy, path: str) -> list[dict[str, Any]] | None:
    """一篇收藏的图片清单（同 manifest 顺序：正文图在前、评论图在后）。不是收藏里的文本 → None。
    只列 read_asset 读得到的路径：规则过、文件真在。meta.json / manifest.json 是服务自己读，不对外开放。"""
    oid = _object_id(policy, path)
    if not oid:
        return None
    obj_rel = f"{XHS_ARCHIVE}/{oid}"
    obj = policy.root.joinpath(*obj_rel.split("/"))
    meta = _load_json(obj / "meta.json") or {}
    try:
        version = int(meta.get("current_version") or 0) if isinstance(meta, dict) else 0
    except (TypeError, ValueError):
        version = 0
    rows: list[tuple[str, Any, Any, Any]] = []
    if version > 0:
        manifest = _load_json(obj / "raw" / f"v{version:04d}" / "manifest.json") or {}
        for m in (manifest.get("media") if isinstance(manifest, dict) else None) or []:
            if isinstance(m, dict) and isinstance(m.get("file"), str):
                rows.append((m["file"], m.get("width"), m.get("height"), m.get("role")))
    if not rows:   # 没有 manifest：退回识图记录里的图片
        vision = _load_json(obj / "derived" / "vision.json") or {}
        for v in (vision.get("images") if isinstance(vision, dict) else None) or []:
            if isinstance(v, dict) and isinstance(v.get("asset"), str):
                rows.append((v["asset"], None, None, None))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for file, w, h, role in rows:
        rel = f"{obj_rel}/{file}"
        if rel in seen or not policy.allowed_asset(rel):
            continue
        seen.add(rel)
        if not policy.root.joinpath(*rel.split("/")).is_file():
            continue
        row: dict[str, Any] = {"n": len(out) + 1, "path": rel,
                               "width": w if isinstance(w, int) else None, "height": h if isinstance(h, int) else None}
        if role in ("note_image", "comment_image"):
            row["role"] = "正文图" if role == "note_image" else "评论图"
        out.append(row)
    return out


def load_image(policy: Policy, path: object) -> tuple[bytes, str, dict[str, Any]]:
    """过白名单读一张图；超上限就等比缩到长边 IMAGE_MAX_EDGE 转 JPEG。返回 (字节, mime, 说明)。"""
    target = policy.resolve_asset(path)
    size = os.path.getsize(target)
    if size > IMAGE_SOURCE_MAX:
        raise Denied("TOO_LARGE", f"图片太大（{size // 1024 // 1024} MB），不提供")
    raw = target.read_bytes()
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            if fmt not in _PIL_FORMATS:
                raise Denied("NOT_IMAGE", "不是能识别的图片")
            w, h = im.size
            info: dict[str, Any] = {"width": w, "height": h, "bytes": size, "mime": _PIL_FORMATS[fmt], "resized": False}
            if size <= IMAGE_MAX_BYTES and max(w, h) <= IMAGE_MAX_EDGE:
                return raw, _PIL_FORMATS[fmt], info
            im.seek(0)
            frame = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P", "PA") else im.convert("RGB")
    except Denied:
        raise
    except Exception:  # noqa: BLE001 - 坏图 / 解码炸弹
        raise Denied("NOT_IMAGE", "图片打不开（损坏或格式不支持）") from None
    if frame.mode == "RGBA":
        bg = Image.new("RGB", frame.size, (255, 255, 255))
        bg.paste(frame, mask=frame.getchannel("A"))
        frame = bg
    frame.thumbnail((IMAGE_MAX_EDGE, IMAGE_MAX_EDGE), Image.LANCZOS)
    data = b""
    for quality in (85, 70, 55):
        buf = io.BytesIO()
        frame.save(buf, "JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= IMAGE_MAX_BYTES:
            break
    if len(data) > IMAGE_MAX_BYTES:
        raise Denied("TOO_LARGE", "图片缩过还是太大，不提供")
    info.update(resized=True, sent_width=frame.size[0], sent_height=frame.size[1], sent_bytes=len(data),
                sent_mime="image/jpeg")
    return data, "image/jpeg", info


def read_asset(policy: Policy, args: dict[str, Any]) -> dict[str, Any]:
    path = args.get("path")
    data, mime, info = load_image(policy, path)
    note = "这是原图，用来核对 OCR / 识图文字" if not info["resized"] else (
        f"原图 {info['width']}×{info['height']}、{info['bytes']} 字节，超上限已等比缩到 "
        f"{info['sent_width']}×{info['sent_height']}（JPEG）再给")
    return {"path": path, **info, "note": note, "_images": [{"data": data, "mime": mime}]}


# ---------------------------------------------------------------- list

def list_dir(policy: Policy, args: dict[str, Any]) -> dict[str, Any]:
    path = args.get("path") or ""
    offset = _int(args.get("offset"), 0, 0, 10 ** 9)
    limit = _int(args.get("limit"), LIST_DEFAULT, 1, LIST_MAX)
    if path == "":
        roots = []
        for r in policy.roots():
            label = {XHS_VISIBLE: "小红书收藏：每篇一个笔记（给人看的版本）",
                     XHS_ARCHIVE: "小红书收藏：每篇一个文件夹，里面是机读版 derived/agent.md、附件全文 derived/attachments/*.md、批注 notes.json"}.get(r, "你开放的文件夹")
            roots.append({"path": r, "type": "dir", "label": label})
        return {"path": "", "entries": roots, "total": len(roots), "offset": 0, "next_offset": None}
    rel, base = policy.resolve_dir(path)
    titles = _item_titles() if rel == XHS_ARCHIVE else {}
    entries: list[dict[str, Any]] = []
    try:
        scanned = sorted(os.scandir(base), key=lambda e: e.name)
    except OSError:
        raise Denied("NOT_FOUND", "读不了这个文件夹") from None
    for e in scanned:
        child = f"{rel}/{e.name}"
        try:
            if _is_link(e):
                continue
            if e.is_dir(follow_symlinks=False):
                if policy.dir_rule(child):
                    row = {"path": child, "type": "dir"}
                    if titles.get(e.name):
                        row["title"] = titles[e.name]
                    entries.append(row)
            elif e.is_file(follow_symlinks=False) and policy.allowed_file(child):
                st = e.stat(follow_symlinks=False)
                entries.append({"path": child, "type": "file", "bytes": st.st_size,
                                "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime))})
        except OSError:
            continue
    page = entries[offset:offset + limit]
    nxt = offset + len(page)
    return {"path": rel, "entries": page, "total": len(entries), "offset": offset,
            "next_offset": nxt if nxt < len(entries) else None}


# ---------------------------------------------------------------- search

def _archive_paths(item: dict[str, Any]) -> tuple[str | None, list[str]]:
    """一篇收藏的机读版和附件全文的相对路径（存在才给）。"""
    from .. import storage
    agent = item.get("agent_md")
    agent = agent if isinstance(agent, str) and agent else None
    atts: list[str] = []
    if agent:
        base = agent.rsplit("/derived/", 1)[0]
        d = storage.vault_root().joinpath(*base.split("/"), "derived", "attachments")
        try:
            atts = sorted(f"{base}/derived/attachments/{p.name}" for p in d.glob("*.md") if p.is_file())
        except OSError:
            atts = []
        if not storage.vault_root().joinpath(*agent.split("/")).is_file():
            agent = None
    return agent, atts


def _search_library(policy: Policy, query: str, limit: int) -> list[dict[str, Any]]:
    from .. import retrieval
    from ..ask import load_items, query_terms
    items = load_items()
    if not items:
        return []
    terms = query_terms(query)
    sem = retrieval.semantic_hits(query)
    hits = retrieval.rank_query(items, query, terms, sem=sem)
    out: list[dict[str, Any]] = []
    for value, it in hits:
        if len(out) >= limit:
            break
        note = it.get("note") if isinstance(it.get("note"), str) else None
        agent, atts = _archive_paths(it)
        note = note if note and policy.allowed_file(note) else None
        agent = agent if agent and policy.allowed_file(agent) else None
        atts = [a for a in atts if policy.allowed_file(a)]
        if not (note or agent or atts):
            continue
        try:
            parts = retrieval.evidence(it, terms, 900, sem)
        except Exception:  # noqa: BLE001
            parts = []
        out.append({"title": it.get("title"), "item_id": it.get("id"), "score": round(float(value), 4),
                    "path": note, "agent_md": agent, "attachments": atts,
                    "summary": it.get("summary") or "", "tags": it.get("tags") or [],
                    "source_url": it.get("url"), "first_archived": it.get("date") or "",
                    "excerpts": [{"field": p.get("field"), "text": p.get("text")} for p in parts if isinstance(p, dict)]})
    return out


def _search_folders(policy: Policy, query: str, limit: int, skip_prefixes: tuple[str, ...]) -> list[dict[str, Any]]:
    terms = [t.casefold() for t in re.split(r"\s+", query.strip()) if t]
    if not terms or not policy.user_folders:
        return []
    deadline = time.monotonic() + SCAN_SECONDS
    scanned = 0
    found: list[tuple[int, str, str]] = []
    for folder in policy.user_folders:
        if any(folder == p or folder.startswith(p + "/") for p in skip_prefixes):
            continue
        try:
            _, base = policy.resolve_dir(folder)
        except Denied:
            continue
        stack = [(folder, base)]
        while stack and scanned < SCAN_FILES_MAX and time.monotonic() < deadline:
            rel, d = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                child = f"{rel}/{e.name}"
                try:
                    if _is_link(e):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if policy.dir_rule(child):
                            stack.append((child, e.path))
                        continue
                    if not e.is_file(follow_symlinks=False) or not policy.allowed_file(child):
                        continue
                    if e.stat(follow_symlinks=False).st_size > SCAN_FILE_BYTES:
                        continue
                    scanned += 1
                    text = open(e.path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                hay = (child + "\n" + text).casefold()
                if not all(t in hay for t in terms):
                    continue
                score = sum(hay.count(t) for t in terms)
                pos = text.casefold().find(terms[0])
                snippet = text[max(0, pos - 120): pos + 240] if pos >= 0 else text[:240]
                found.append((score, child, snippet.strip()))
    found.sort(key=lambda x: (-x[0], x[1]))
    return [{"title": os.path.splitext(p.rsplit("/", 1)[-1])[0], "path": p, "score": s,
             "excerpts": [{"field": "text", "text": snip}]} for s, p, snip in found[:limit]]


def search(policy: Policy, args: dict[str, Any]) -> dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise Denied("INVALID_ARGUMENT", "query 不能为空")
    query = query.strip()[:500]
    limit = _int(args.get("limit"), SEARCH_DEFAULT, 1, SEARCH_MAX)
    results: list[dict[str, Any]] = []
    if policy.xhs:
        results += _search_library(policy, query, limit)
    skip = (XHS_VISIBLE,) if policy.xhs else ()   # 收藏的可见笔记已经由上面的检索覆盖
    if limit - len(results) > 0:
        results += _search_folders(policy, query, limit - len(results), skip)
    return {"query": query, "found": len(results), "results": results,
            "note": "只含开放给你的内容；用 read 读 path / agent_md / attachments 的全文"}


HANDLERS = {"search": search, "read": read, "list": list_dir, "read_asset": read_asset}
