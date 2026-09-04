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

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
# 笔记网页版的 SSR 状态；MCP 不返回的 relatedFile（笔记附件）在这里面
INITIAL_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(.+?)</script>", re.S)
FILE_PREVIEW_FMT = "https://www.xiaohongshu.com/file/{doc_id}"

URL_RE = re.compile(r"https?://[^\s<>\"'，。、）)\]]+")
NOTE_ID_RE = re.compile(
    # 从作者主页 / 收藏列表里复制出来的是这种：/user/profile/<user_id>/<note_id>?xsec_token=…
    # 前面那截是**作者 id**，别当成 note_id（2026-09-04 Owner 那批收藏全是这个形状）
    r"/user/profile/[0-9a-fA-F]{16,32}/([0-9a-fA-F]{16,32})"
    r"|/(?:explore|discovery/item|item)/([0-9a-fA-F]{16,32})"
)
HASHTAG_RE = re.compile(r"#([^#\[\]]{1,30})\[话题\]#")
# 「文件 / 附件」线索：小红书笔记可以挂文件，但 MCP 完全不返回附件字段
ATTACHMENT_HINT_RE = re.compile(r"[^\n。！？]{0,40}(?:附件|在文件|文件里|笔记文件)[^\n。！？]{0,40}")


class AdapterError(RuntimeError):
    """输入解析或抓取失败。"""


class NeedsHumanError(AdapterError):
    """要停车叫人的那一类失败（和"这篇笔记没了"必须分开）。

    后者只是这一条抓不到，批量可以接着跑；这一类接着跑只会把剩下的全刷成失败。
    """


class AccountBlockedError(NeedsHumanError):
    """**号出事了**：登录态失效 / 撞风控验证码 / 被限流。"""


class ServiceDownError(NeedsHumanError):
    """**服务出事了**：18060 没在听、MCP 内部错、它那个浏览器起不来。

    2026-09-04 实际发生过：批量跑到第 19 条，MCP 回
    「[launcher] Failed to get the debug url」，后面 7 条全 3 秒失败——
    这种必须当场停车报警，不然就是 Owner 说的"不知不觉挂了"。
    """


# 号出事的迹象（MCP 报错文本 / 网页返回里出现这些词）。宁可多报一次，也别不知不觉挂着跑
BLOCKED_HINTS = (
    "未登录", "请登录", "登录后", "登录态", "重新登录", "cookie 失效", "cookie失效",
    "not logged in", "login required", "unauthorized", "登录即可",
    "验证码", "captcha", "滑块", "安全验证", "行为异常", "账号异常", "风控",
    "访问频繁", "操作频繁", "too many requests", "rate limit", "429",
)


# 服务本身出事的迹象：18060 没在听、MCP 内部错、它那个 headless 浏览器起不来
SERVICE_DOWN_HINTS = (
    "launcher", "debug url", "内部错误", "internal error", "服务端日志",
    "connection refused", "connectionrefused", "econnrefused",
    "all connection attempts failed", "connecterror", "connecttimeout",
    "远程主机强迫关闭", "actively refused",
)


def looks_blocked(text: str | None) -> bool:
    """一段错误文本/页面内容看起来像不像"号出事了"。"""
    low = (text or "").lower()
    return any(hint.lower() in low for hint in BLOCKED_HINTS)


def looks_service_down(text: str | None) -> bool:
    """看起来像不像"18060 那个服务/它的浏览器出事了"。"""
    low = (text or "").lower()
    return any(hint.lower() in low for hint in SERVICE_DOWN_HINTS)


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
    note_id = match.group(1) or match.group(2)
    token = None
    query = url.partition("?")[2]
    for pair in query.split("&"):
        key, _, value = pair.partition("=")
        if key == "xsec_token" and value:
            token = value
            break
    return note_id, token


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
                joined = " ".join(texts)[:400]
                if looks_blocked(joined):
                    raise AccountBlockedError(
                        f"小红书那侧要人处理（登录态失效 / 风控验证码）：MCP {tool} 说「{joined}」"
                    )
                if looks_service_down(joined):
                    raise ServiceDownError(
                        f"18060 那个服务出事了（先 Start-ScheduledTask XiaohongshuMCP 再重试）："
                        f"MCP {tool} 说「{joined}」"
                    )
                raise AdapterError(f"MCP {tool} 报错: {joined}")
            for chunk in result.content:
                text = getattr(chunk, "text", None)
                if text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        # 有些工具（check_login_status）返回的是人话不是 JSON
                        return text
            raise AdapterError(f"MCP {tool} 返回空内容")


def flatten_exc(exc: BaseException) -> str:
    """把异常（含 ExceptionGroup 的子异常）摊成一行文本，用来判是不是"服务挂了"。

    anyio 会把 ConnectError 包进 ExceptionGroup，`str(exc)` 只剩
    「unhandled errors in a TaskGroup」——不摊开就永远认不出连不上 18060。
    """
    parts = [f"{type(exc).__name__}: {exc}"]
    for sub in getattr(exc, "exceptions", ()) or ():
        parts.append(flatten_exc(sub))
    if exc.__cause__ is not None:
        parts.append(flatten_exc(exc.__cause__))
    return " | ".join(parts)


def call_tool(tool: str, arguments: dict[str, Any], *, endpoint: str = MCP_ENDPOINT,
              timeout: float = 300) -> Any:
    """同步调一个 MCP 工具；连不上/服务内部错一律升级成 `ServiceDownError`。"""
    try:
        return asyncio.run(_call_mcp(tool, arguments, endpoint=endpoint, timeout=timeout))
    except NeedsHumanError:
        raise
    except Exception as exc:  # noqa: BLE001 - 连不上 18060 是"服务出事了"，不是这条链接的问题
        text = flatten_exc(exc)
        if looks_service_down(text) or isinstance(exc, (OSError, ConnectionError)):
            raise ServiceDownError(
                f"连不上 18060 的 MCP（先 Start-ScheduledTask XiaohongshuMCP 再重试）：{text[:300]}"
            ) from exc
        raise


def check_login_status(*, endpoint: str = MCP_ENDPOINT, timeout: float = 60) -> Any:
    """确认 MCP 登录态还在（浏览器补抓之后必须跑一次）。"""
    return call_tool("check_login_status", {}, endpoint=endpoint, timeout=timeout)


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
    return call_tool(MCP_TOOL, arguments, endpoint=endpoint, timeout=timeout)


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


def fetch_related_file(note_id: str, xsec_token: str | None, *, timeout: int = 30) -> dict[str, Any]:
    """去笔记网页版拿附件元数据（MCP 的 `get_feed_detail` 不返回它）。

    网页 SSR 的 `__INITIAL_STATE__.note.noteDetailMap[<id>].note.relatedFile` **游客可见**，
    带 `docId` / `name` / `bizExtra`（页数、下载数、浏览数）。字节要登录才给
    （`/file/<docId>` 页面对游客显示"登录即可下载该文件"），所以这里只取元数据。

    返回 `{"ok": bool, "related_file": dict|None, "url": str, "error": str|None}`；
    抓不到不抛异常——附件是附加信息，不该阻断主体归档。
    """
    url = CANONICAL_FMT.format(note_id=note_id)
    if xsec_token:
        url = f"{url}?xsec_token={xsec_token}&xsec_source=pc_feed"
    result: dict[str, Any] = {"ok": False, "related_file": None, "url": url, "error": None}
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": DESKTOP_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        match = INITIAL_STATE_RE.search(resp.text)
        if not match:
            result["error"] = "笔记页里没有 __INITIAL_STATE__"
            return result
        # SSR 状态里会出现裸 undefined，不是合法 JSON
        state = json.loads(match.group(1).strip().rstrip(";").replace("undefined", "null"))
        detail = ((state.get("note") or {}).get("noteDetailMap") or {}).get(note_id) or {}
        note = detail.get("note") or {}
        if not note:
            # 页面回了 200 但没有这条笔记（登录墙 / 已删 / 反爬占位页）——
            # 这种情况**不能**当作"这篇没有附件"，否则会把正文线索一起吞掉
            result["error"] = "笔记页里没有这条笔记（登录墙 / 已删 / 反爬占位页？）"
            # 页面上直接写着"验证码/请登录"这类词 = 被拦了，调用方要报警，不是"这篇没附件"
            result["blocked"] = looks_blocked(resp.text[:8000])
            return result
        result["ok"] = True
        result["related_file"] = note.get("relatedFile") or None
    except Exception as exc:  # noqa: BLE001 - 探测失败退回正文启发式，不阻断
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _attachments(body: str, probe: dict[str, Any] | None) -> list[dict[str, Any]]:
    """附件条目。

    网页探测成功时它就是**权威**：`relatedFile` 有就出一条带真名字/docId 的记录，
    没有就说明这篇根本没挂文件——正文里提到"文件"也不再误报。
    探测失败才退回正文正则线索（会漏也会误报，见 `docs/POC-xiaohongshu.md`）。
    """
    hints = [h.strip() for h in ATTACHMENT_HINT_RE.findall(body or "")]

    if probe and probe.get("ok"):
        related = probe.get("related_file")
        if not related:
            return []
        extra = {}
        try:
            extra = json.loads(related.get("bizExtra") or "{}")
        except (TypeError, ValueError):
            extra = {}
        doc_id = related.get("docId")
        return [
            {
                "name": related.get("name"),
                "doc_id": doc_id,
                "hint": hints[0] if hints else None,
                "url": FILE_PREVIEW_FMT.format(doc_id=doc_id) if doc_id else None,
                "icon_url": related.get("icon"),
                "page_num": _int_or_none(extra.get("page_num")),
                "download_num": _int_or_none(extra.get("download_num")),
                "view_num": _int_or_none(extra.get("view_num")),
                "file": None,
                "status": "metadata_only",
                "reason": "小红书网页版要登录才给附件字节；元数据取自笔记页 relatedFile",
            }
        ]

    return [
        {
            "name": None,
            "doc_id": None,
            "hint": hint,
            "url": None,
            "icon_url": None,
            "page_num": None,
            "download_num": None,
            "view_num": None,
            "file": None,
            "status": "unavailable",
            "reason": "MCP 不返回附件字段，网页探测也失败："
            + ((probe or {}).get("error") or "没探测"),
        }
        for hint in hints
    ]


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


def normalize(
    raw: dict[str, Any],
    parsed: dict[str, Any],
    *,
    captured_at: str,
    web_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
            "attachments": _attachments(body, web_probe),
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
            "web_probe": (
                None
                if web_probe is None
                else {"ok": web_probe.get("ok"), "url": web_probe.get("url"), "error": web_probe.get("error")}
            ),
            "notes": [],
        },
    }
