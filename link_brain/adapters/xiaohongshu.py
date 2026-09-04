"""小红书 adapter。

三件事：
1. 输入（正常 URL / `xhslink.cn` 短链 / 分享文本）→ `note_id` + `xsec_token` + canonical URL
2. 连本机 18060 xiaohongshu-mcp 调 `get_feed_detail` 拿原始响应
3. 把原始响应归一化成 `docs/FORMAT.md` 定的 `source.json`

MCP 返回结构、CDN 档位、楼中楼深度等实测结论见 `docs/POC-xiaohongshu.md`。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

SOURCE = "xiaohongshu"
ADAPTER_VERSION = "xiaohongshu/1"
MCP_ENDPOINT = "http://127.0.0.1:18060/mcp"
MCP_TOOL = "get_feed_detail"

SHORTLINK_HOSTS = ("xhslink.cn", "xhslink.com")
CANONICAL_FMT = "https://www.xiaohongshu.com/explore/{note_id}"

# 移动端 UA：短链服务端按 UA 决定跳到哪个域名，桌面 UA 会拿到不带 xsec_token 的页面
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

URL_RE = re.compile(r"https?://[^\s<>\"'，。、）)\]]+")
NOTE_ID_RE = re.compile(r"/(?:explore|discovery/item|item)/([0-9a-fA-F]{16,32})")
HASHTAG_RE = re.compile(r"#([^#\[\]]{1,30})\[话题\]#")
# 「文件 / 附件」线索：小红书笔记可以挂文件，但 MCP 完全不返回附件字段
ATTACHMENT_HINT_RE = re.compile(r"[^\n。！？]{0,40}(?:附件|在文件|文件里|笔记文件)[^\n。！？]{0,40}")


class AdapterError(RuntimeError):
    """输入解析或抓取失败。"""


# --------------------------------------------------------------------------
# 1. 输入解析
# --------------------------------------------------------------------------


def extract_url(text: str) -> str:
    """从分享文本里抠出第一个 URL；本身就是 URL 就原样返回。"""
    match = URL_RE.search(text or "")
    if not match:
        raise AdapterError(f"输入里找不到 URL: {text!r:.120}")
    return match.group(0).rstrip("，。、)）]")


def classify_input(text: str) -> str:
    """`url` / `shortlink` / `share_text`。"""
    stripped = (text or "").strip()
    url = extract_url(stripped)
    if any(host in url for host in SHORTLINK_HOSTS):
        return "shortlink"
    return "url" if stripped == url else "share_text"


def _parse_note_url(url: str) -> tuple[str, str | None]:
    match = NOTE_ID_RE.search(url)
    if not match:
        raise AdapterError(f"URL 里没有 note_id: {url}")
    token = None
    query = url.partition("?")[2]
    for pair in query.split("&"):
        key, _, value = pair.partition("=")
        if key == "xsec_token" and value:
            token = value
            break
    return match.group(1), token


def resolve_shortlink(url: str, *, client: httpx.Client | None = None) -> str:
    """GET 短链但**不跟随重定向**，从 `Location` 头读出真实笔记 URL。"""
    owned = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False)
    try:
        current = url
        for _ in range(6):
            response = client.get(current, headers={"User-Agent": MOBILE_UA})
            location = response.headers.get("location")
            if not location:
                break
            current = location
            if NOTE_ID_RE.search(current):
                break
        if not NOTE_ID_RE.search(current):
            raise AdapterError(f"短链解不出笔记 URL: {url} -> {current[:160]}")
        return current
    finally:
        if owned:
            client.close()


def parse_input(text: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """任意输入 → `{note_id, xsec_token, canonical_url, input_url, input_kind, resolved_url}`。"""
    input_kind = classify_input(text)
    url = extract_url(text)
    resolved = resolve_shortlink(url, client=client) if input_kind == "shortlink" else url
    note_id, token = _parse_note_url(resolved)
    return {
        "note_id": note_id,
        "xsec_token": token,
        "canonical_url": CANONICAL_FMT.format(note_id=note_id),
        "input_url": url,
        "input_kind": input_kind,
        "resolved_url": resolved,
    }


# --------------------------------------------------------------------------
# 2. MCP 抓取
# --------------------------------------------------------------------------


async def _call_mcp(tool: str, arguments: dict[str, Any], *, endpoint: str, timeout: float) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(endpoint, timeout=timeout) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            if result.isError:
                texts = [getattr(c, "text", "") for c in result.content]
                raise AdapterError(f"MCP {tool} 报错: {' '.join(texts)[:400]}")
            for chunk in result.content:
                text = getattr(chunk, "text", None)
                if text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        # 有些工具（check_login_status）返回的是人话不是 JSON
                        return text
            raise AdapterError(f"MCP {tool} 返回空内容")


def check_login_status(*, endpoint: str = MCP_ENDPOINT, timeout: float = 60) -> Any:
    """确认 MCP 登录态还在（浏览器补抓之后必须跑一次）。"""
    return asyncio.run(_call_mcp("check_login_status", {}, endpoint=endpoint, timeout=timeout))


def fetch_detail(
    note_id: str,
    xsec_token: str,
    *,
    endpoint: str = MCP_ENDPOINT,
    comment_limit: int = 200,
    reply_limit: int = 100,
    timeout: float = 300,
) -> dict[str, Any]:
    """调 `get_feed_detail`，返回**原始**响应（原样落 `mcp_raw.json`）。"""
    if not xsec_token:
        raise AdapterError("缺 xsec_token，MCP 无法抓取（短链没带 token？）")
    arguments = {
        "feed_id": note_id,
        "xsec_token": xsec_token,
        "load_all_comments": True,
        "limit": comment_limit,
        "click_more_replies": True,
        "reply_limit": reply_limit,
        "scroll_speed": "normal",
    }
    return asyncio.run(_call_mcp(MCP_TOOL, arguments, endpoint=endpoint, timeout=timeout))


# --------------------------------------------------------------------------
# 3. 归一化
# --------------------------------------------------------------------------


def _ms_to_iso(value: Any) -> str | None:
    if not value:
        return None
    try:
        return (
            datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )
    except (TypeError, ValueError, OSError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _user(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    user_id = raw.get("userId") or raw.get("user_id")
    return {
        "user_id": user_id,
        "nickname": raw.get("nickname") or raw.get("nickName") or None,
        "avatar_url": raw.get("avatar") or None,
        "profile_url": (
            f"https://www.xiaohongshu.com/user/profile/{user_id}" if user_id else None
        ),
    }


def _images(image_list: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for i, item in enumerate(image_list or [], start=1):
        # urlDefault 是能拿到的最高画质档；路径带签名，改后缀/去后缀一律 403（见 POC）
        url = item.get("urlDefault") or item.get("urlPre")
        out.append(
            {
                "index": i,
                "url": url,
                "original_url": url,
                "preview_url": item.get("urlPre"),
                "width": _int_or_none(item.get("width")),
                "height": _int_or_none(item.get("height")),
            }
        )
    return out


def _video(note: dict[str, Any]) -> dict[str, Any] | None:
    video = note.get("video")
    if not video:
        return None
    streams = ((video.get("media") or {}).get("stream") or {})
    best = None
    for codec in ("h265", "h264", "av1"):
        items = streams.get(codec) or []
        if items:
            best = items[0]
            break
    return {
        "video_url": (best or {}).get("masterUrl"),
        # 封面就是 imageList[0]（落盘时 role=video_cover）
        "cover_url": ((note.get("imageList") or [{}])[0].get("urlDefault")),
        "duration_sec": _int_or_none((video.get("capa") or {}).get("duration")),
        "width": _int_or_none((best or {}).get("width")),
        "height": _int_or_none((best or {}).get("height")),
        "downloaded": False,
    }


def _links(body: str, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for url in URL_RE.findall(body or ""):
        url = url.rstrip("，。、)）]")
        if ("body", url) not in seen:
            seen.add(("body", url))
            out.append({"url": url, "text": None, "where": "body"})
    for comment in comments:
        for entry in [comment, *(comment.get("sub_comments") or [])]:
            where = f"comment:{entry['comment_id']}"
            for url in URL_RE.findall(entry.get("text") or ""):
                url = url.rstrip("，。、)）]")
                if (where, url) not in seen:
                    seen.add((where, url))
                    out.append({"url": url, "text": None, "where": where})
    return out


def _attachments(body: str) -> list[dict[str, Any]]:
    """MCP 完全不返回附件字段，只能从正文里找线索并标 unavailable（见 POC 第 5 条）。"""
    out = []
    for hint in ATTACHMENT_HINT_RE.findall(body or ""):
        out.append(
            {
                "name": None,
                "hint": hint.strip(),
                "url": None,
                "status": "unavailable",
                "reason": "xiaohongshu-mcp 的 get_feed_detail 不返回笔记文件附件",
            }
        )
    return out


def _comment(raw: dict[str, Any], floor: int) -> dict[str, Any]:
    subs_raw = raw.get("subComments") or []
    declared = _int_or_none(raw.get("subCommentCount")) or 0
    entry = {
        "comment_id": raw.get("id"),
        "floor": floor,
        "author": _user(raw.get("userInfo")),
        "text": raw.get("content") or "",
        "created_at": _ms_to_iso(raw.get("createTime")),
        "like_count": _int_or_none(raw.get("likeCount")),
        "ip_location": raw.get("ipLocation") or None,
        "tags": raw.get("showTags") or [],
        # MCP 的评论对象里根本没有图片字段（见 POC 第 3 条），恒为空
        "images": [],
    }
    if floor == 1:
        entry["sub_comment_count"] = declared
        entry["sub_comments"] = [_comment(s, 2) for s in subs_raw]
        entry["sub_comments_complete"] = len(subs_raw) >= declared
    else:
        entry["target_nickname"] = None
    return entry


def normalize(raw: dict[str, Any], parsed: dict[str, Any], *, captured_at: str) -> dict[str, Any]:
    """MCP 原始响应 → `source.json`（docs/FORMAT.md §3）。"""
    data = raw.get("data") or {}
    note = data.get("note") or {}
    if not note:
        raise AdapterError("MCP 响应里没有 data.note")

    comments_block = data.get("comments") or {}
    comment_list = comments_block.get("list") or []
    comments = [_comment(c, 1) for c in comment_list]
    # hasMore 是 MCP 明确给出的信号：False 就是真的抓完了，不必写 "unknown"
    has_more = comments_block.get("hasMore")
    comments_complete = "unknown" if has_more is None else (not has_more)

    body = note.get("desc") or ""
    interact = note.get("interactInfo") or {}
    kind = "video" if note.get("type") == "video" else ("image" if note.get("imageList") else "text")

    return {
        "schema_version": 1,
        "source": SOURCE,
        "source_id": parsed["note_id"],
        "note": {
            "note_id": parsed["note_id"],
            "xsec_token": parsed.get("xsec_token"),
            "canonical_url": parsed["canonical_url"],
            "kind": kind,
            "title": note.get("title") or None,
            "body": body,
            "hashtags": HASHTAG_RE.findall(body),
            "links": _links(body, comments),
            "author": _user(note.get("user")),
            "published_at": _ms_to_iso(note.get("time")),
            "ip_location": note.get("ipLocation") or None,
            "engagement": {
                "liked": _int_or_none(interact.get("likedCount")),
                "collected": _int_or_none(interact.get("collectedCount")),
                "comment_count": _int_or_none(interact.get("commentCount")),
                "shared": _int_or_none(interact.get("sharedCount")),
            },
            "images": _images(note.get("imageList")),
            "video": _video(note),
            "attachments": _attachments(body),
        },
        "comments": comments,
        "capture": {
            "captured_at": captured_at,
            "input_url": parsed["input_url"],
            "input_kind": parsed["input_kind"],
            "adapter": ADAPTER_VERSION,
            "mcp_endpoint": MCP_ENDPOINT,
            "mcp_tool": MCP_TOOL,
            "comments_complete": comments_complete,
            "comments_cursor": comments_block.get("cursor"),
            "notes": [],
        },
    }
