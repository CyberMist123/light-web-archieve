"""小红书来源接口，暂时转接现有实现。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from . import adapter
from .presentation import (comment_gap_text, comment_status_text, is_link_only,
                           source_open_url, suggested_link_url)
from .. import Fetched, FetchOptions, MediaTask, Parsed

name = adapter.SOURCE
version = adapter.ADAPTER_VERSION
capabilities = frozenset({"account", "favorites_sync", "comments_fill", "attachments", "albums"})


def comment_view(source, meta):
    from . import comment_fill
    sid = meta.get("source_id") or source.get("source_id")
    state = comment_fill.load_state(meta.get("source") or source.get("source") or name, sid) if sid else {}
    return comment_fill.view_for_render(source, state)


def comment_gap_lines(source, view):
    from .comment_fill import floors_label
    comments = source.get("comments") or []
    cl = (source.get("capture") or {}).get("comment_load") or {}
    if view is not None:
        if int(view.get("missing") or 0) > 0:
            return [f"（评论读到 {len(comments)} 楼，{floors_label(int(view.get('floors') or 10))}的楼中楼还缺 "
                    f"{view['missing']} 条：{view.get('why') or '没读全'}；下面标「还缺」的楼不全）", ""]
    elif int(cl.get("replies_missing") or 0) > 0:
        gaps = cl.get("gaps") or []
        main = max(gaps, key=lambda g: int(g.get("missing") or 0)).get("reason") if gaps else cl.get("stop_reason")
        return [f"（评论读到 {cl.get('floors_loaded') or len(comments)} 楼，楼中楼还缺 {cl['replies_missing']} 条："
                f"{adapter.REPLY_GAP_CN.get(str(main or ''), '没读全')}；下面标「还缺」的楼不全）", ""]
    return []


def restricted_text(view):
    from .restricted import GONE_TEXT
    r = (view or {}).get("restricted") if isinstance(view, dict) else None
    return GONE_TEXT if r else ""


def note_albums():
    from . import albums
    return albums.note_albums()


def item_flags(obj_dir):
    from ... import storage
    from .restricted import confirmed
    def load(path):
        try:
            return storage.read_json(path)
        except (OSError, ValueError):
            return {}
    mark = load(obj_dir / "derived" / "web_recheck.json") or {}
    if isinstance(mark, dict) and mark.get("gone"):
        return [{"code": "PERMANENT.NOTE_GONE", "detail": "原帖打不开（可能已删或仅作者可见），本地存档还在"}]
    restricted = load(obj_dir / "derived" / "restricted.json") or {}
    if isinstance(restricted, dict) and confirmed(restricted):
        return [{"code": "PERMANENT.NOTE_GONE", "detail": "原帖打不开了（多半删了或仅作者可见），本地存档还在"}]
    return []


def action_home():
    from . import accounts
    return accounts.home()


def action_lock_holder():
    from . import accounts
    return accounts.lock_holder()


def action_for_route(route):
    r = route.split("?", 1)[0]
    return {"/api/v1/favorites": "favorites", "/api/v1/attachments/download": "attachments",
            "/api/v1/notes/related-file": "attachments", "/api/v1/login/status": "login_check",
            "/api/v1/notes/search-token": "search_token", "/api/v1/risk/probe": "probe",
            "/api/v1/boards": "boards", "/api/v1/boards/notes": "board_notes"}.get(r, "")

# PR③ 删掉 catch 中的副本；这里暂时逐字保留它的链接提取逻辑。
XHS_HOSTS = ("xiaohongshu.com", "rednote.com", "xhslink.cn", "xhslink.com")
TRAILING = "，。、；：！？）)]】》>\"'“”‘’"


def _is_xhs(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in XHS_HOSTS)


def find_urls(message: str) -> list[str]:
    """从任意消息全文里抠出小红书链接，按出现顺序去重。"""
    found: list[str] = []
    for match in adapter.URL_RE.finditer(message or ""):
        url = match.group(0).rstrip(TRAILING)
        if _is_xhs(url) and url not in found:
            found.append(url)
    return found


def matches(url: str) -> bool:
    return bool(adapter.WHITELIST_RE.search(urlsplit(url).hostname or ""))


def parse(text: str) -> Parsed:
    parsed = adapter.parse_input(text)
    return {**parsed, "source": name, "source_id": parsed["note_id"]}


# PR⑤ 把这段搬进来后去掉函数内的 ingest import。
def fetch(parsed: Parsed, opts: FetchOptions) -> Fetched:
    from ... import ingest

    raw = ingest._fetch_with_retry(
        parsed, log=opts.log, comment_floors=opts.comment_floors,
        budget_left=opts.budget_left, progress=opts.progress,
        expand_floors=opts.extra.get("expand_floors"),
    )
    return Fetched(raw_files={"mcp_raw.json": raw}, context={})


def normalize(fetched: Fetched, parsed: Parsed, *, captured_at: str) -> dict[str, Any]:
    return adapter.normalize(fetched.raw_files["mcp_raw.json"], parsed, captured_at=captured_at,
                             web_probe=fetched.context.get("web_probe"))


def fingerprint(source_doc: dict[str, Any]) -> str:
    from ... import index

    return index.normalized_source_sha256(source_doc)


def media_plan(source_doc: dict[str, Any], opts: dict[str, Any]) -> list[MediaTask]:
    from ... import ingest

    note = source_doc["note"]
    is_video = note["kind"] == "video"
    headers = ingest.DOWNLOAD_HEADERS
    tasks: list[MediaTask] = []
    for image in (note["images"] if opts["downloadImages"] else []):
        tasks.append(dict(role="video_cover" if is_video else "note_image", index=image["index"],
                          url=image["url"], stem=f"cover-{image['index']:03d}" if is_video else f"image-{image['index']:03d}",
                          kind="image", headers=headers))
    for comment in source_doc["comments"]:
        for group in [comment, *(comment.get("sub_comments") or [])]:
            for i, image in enumerate(group.get("images") or [], start=1):
                tasks.append(dict(role="comment_image", index=i, comment_id=group["comment_id"],
                                  url=image["url"], stem=f"comment-{group['comment_id']}-{i:03d}",
                                  kind="image", headers=headers))
            audio = group.get("audio")
            if audio and audio.get("url"):
                tasks.append(dict(role="comment_audio", comment_id=group["comment_id"], url=audio["url"],
                                  stem=f"comment-{group['comment_id']}-audio", kind="audio", headers=headers))
    if opts["downloadVideo"] and is_video and (note.get("video") or {}).get("video_url"):
        tasks.append(dict(role="video", index=1, url=note["video"]["video_url"],
                          stem="video", kind="video", headers=headers))
    return tasks
