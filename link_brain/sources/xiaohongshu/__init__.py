"""小红书来源接口，暂时转接现有实现。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ...adapters import xiaohongshu as adapter
from .. import Fetched, FetchOptions, MediaTask, Parsed

name = adapter.SOURCE
version = adapter.ADAPTER_VERSION
capabilities = frozenset({"account", "favorites_sync", "comments_fill", "attachments", "albums"})

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
