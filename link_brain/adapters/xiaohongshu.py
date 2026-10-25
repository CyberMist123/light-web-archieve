"""小红书 adapter。

三件事：
1. 输入（正常 URL / `xhslink.cn` 短链 / 分享文本）→ `note_id` + `xsec_token` + canonical URL
2. 连本机 18060 xiaohongshu-mcp 调 `get_feed_detail` 拿原始响应
3. 把原始响应归一化成 `docs/FORMAT.md` 定的 `source.json`

MCP 返回结构、CDN 档位、楼中楼深度等实测结论见 `docs/POC-xiaohongshu.md`。
"""

from __future__ import annotations
from ..errtext import errtext

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx

SOURCE = "xiaohongshu"
ADAPTER_VERSION = "xiaohongshu/1"
def _default_endpoint() -> str:
    from .. import accounts  # 读取服务地址统一由 accounts 决定（env > accounts.json > 默认 18061）
    return accounts.endpoint()


MCP_ENDPOINT = _default_endpoint()  # 仅作展示/记录；调用时每次重新解析
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

# URL 到**空白 / 中文标点 / 中文字**为止：分享文案常把「…&xsec_source=pc_share增加的内容」
# 这样把中文直接粘在链接尾巴上，不在 CJK 处截断就会把中文吞进 URL、整条识别不出（2026-09-16 Owner 报的）。
URL_RE = re.compile(r"https?://[^\s<>\"'，。、；：！？（）()\[\]【】《》　-〿一-鿿＀-￯]+")
NOTE_ID_RE = re.compile(
    # 从作者主页 / 收藏列表里复制出来的是这种：/user/profile/<user_id>/<note_id>?xsec_token=…
    # 前面那截是**作者 id**，别当成 note_id（2026-09-04 Owner 那批收藏全是这个形状）
    r"/user/profile/[0-9a-fA-F]{16,32}/([0-9a-fA-F]{16,32})"
    r"|/(?:explore|discovery/item|item)/([0-9a-fA-F]{16,32})"
)
HASHTAG_RE = re.compile(r"#([^#\[\]]{1,30})\[话题\]#")
# 「文件 / 附件」线索：小红书笔记可以挂文件，但 MCP 完全不返回附件字段
ATTACHMENT_HINT_RE = re.compile(r"[^\n。！？]{0,40}(?:附件|在文件|文件里|笔记文件)[^\n。！？]{0,40}")


from .. import sources

AdapterError = sources.SourceError
NeedsHumanError = sources.NeedsHuman
AccountBlockedError = sources.AccountBlocked
NoteRestrictedError = sources.ItemRestricted
ServiceDownError = sources.ServiceDown


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


# 1001：读取服务的风险码（MCP 报错文本里带方括号标记）+ 被跳到 /website-login/ 的页面
RISK_MARKERS = ("CAPTCHA_REQUIRED", "ACCOUNT_RISK", "NOT_LOGGED_IN", "RISK_HOLD")
# 1011：只是这一篇（网页版限制）——读取组件 MCP 报错文本里的标记；风险码优先于它
RESTRICTED_MARKER = "[NOTE_RESTRICTED]"


def risk_code(text: str | None) -> str:
    """文本里的风险码：`[ACCOUNT_RISK]` 这类标记优先；只看到 website-login 字样算 ACCOUNT_RISK。"""
    raw = text or ""
    # 1015：限频冷却（[XHS_RATE_LIMITED]，或冷却中被拒的 [RISK_HOLD] …（XHS_RATE_LIMITED，…）））优先：
    # 它的说明里带 /website-login/error，不能落到下面「看到 website-login 就算 ACCOUNT_RISK」
    if "XHS_RATE_LIMITED" in raw:
        return "XHS_RATE_LIMITED"
    for code in RISK_MARKERS:
        if f"[{code}]" in raw:
            return code
    return "ACCOUNT_RISK" if "website-login" in raw.lower() else ""


def looks_blocked(text: str | None) -> bool:
    """一段错误文本/页面内容看起来像不像"号出事了"。"""
    if risk_code(text):
        return True
    low = (text or "").lower()
    return any(hint.lower() in low for hint in BLOCKED_HINTS)


def _blocked_error(message: str, text: str) -> "AccountBlockedError":
    err = AccountBlockedError(message)
    err.code = risk_code(text)
    return err


def _find_in_group(exc: BaseException, kind: type) -> BaseException | None:
    """在（嵌套的）ExceptionGroup 里深度优先找第一个 `kind` 的子异常。"""
    if isinstance(exc, kind) and not getattr(exc, "exceptions", None):
        return exc
    for sub in getattr(exc, "exceptions", ()) or ():
        found = _find_in_group(sub, kind)
        if found is not None:
            return found
    return None


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


# 清洗白名单（注册域）：只认这四个主机及其子域，别的一律不当小红书链接
WHITELIST_RE = re.compile(r"(^|\.)(xiaohongshu\.com|rednote\.com|xhslink\.com|xhslink\.cn)$", re.I)
# 分享垃圾参数只保留这两个（读笔记要 token；xsec_source 影响可达性）
KEEP_PARAMS = ("xsec_token", "xsec_source")


def clean_url(url: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """按 Owner 的清洗规范把一个链接洗干净。

    - `xhslink.cn/.com` 短链**跟随 redirect** 换成最终长链（不把短链写进 Obsidian）；
    - 保留最终 host + path 原样（不改 /explore/、/discovery/item/）；
    - query 只留 `xsec_token` / `xsec_source`，其余（source/xhsshare/app_platform/share_id/
      track_code/apptime/author_share/shareRedId …）全删；`xsec_token` 完整保留不截断；
    - **没有 xsec_token 就如实标 `has_token=False`，绝不擅自拼裸 note_id 声称有效。**
    返回 `{clean, has_token, resolved_from_shortlink, error?}`。
    """
    resolved_short = False
    final = url
    error = None
    if any(host in url.lower() for host in SHORTLINK_HOSTS):
        try:
            final = resolve_shortlink(url, client=client)
            resolved_short = True
        except AdapterError as exc:
            return {"clean": url, "has_token": False, "resolved_from_shortlink": False, "error": str(exc)}
    parts = urllib.parse.urlsplit(final)
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=False) if k in KEEP_PARAMS]
    # xsec_token 在前，稳定顺序
    kept.sort(key=lambda kv: KEEP_PARAMS.index(kv[0]))
    query = urllib.parse.urlencode(kept, safe="=")
    clean = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    return {
        "clean": clean,
        "has_token": any(k == "xsec_token" for k, _ in kept),
        "resolved_from_shortlink": resolved_short,
        "error": error,
    }


def clean_share_text(text: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """从一整段分享文案里抠出所有小红书链接、逐条清洗、去重（保序）。"""
    owned = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for match in URL_RE.finditer(text or ""):
            raw = match.group(0).rstrip("，。、)）]")
            host = urllib.parse.urlsplit(raw).netloc.lower()
            if not WHITELIST_RE.search(host):
                continue
            result = clean_url(raw, client=client)
            key = result["clean"]
            if key in seen:
                continue
            seen.add(key)
            out.append({**result, "original": raw})
    finally:
        if owned:
            client.close()
    return out


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


def tool_error(tool: str, joined: str) -> AdapterError:
    """MCP 工具报错文本 → 该抛哪种异常（风险码 > 1011 网页版限制 > 宽泛的「号出事」词 > 服务出事 > 普通失败）。"""
    if RESTRICTED_MARKER in joined and not risk_code(joined):
        # 1011：只是这一篇（网页版要验证才给看），先于宽泛词判断——别把它当成号出事整批停车
        return NoteRestrictedError(f"这篇在小红书网页版要验证才能看（读取组件：{joined[:200]}）")
    if looks_blocked(joined):
        return _blocked_error(f"读取账号需要处理：请在 Link Brain 设置页检查并重新扫码。详情：{joined}", joined)
    if looks_service_down(joined):
        return ServiceDownError(
            f"读取服务暂不可用：请在 Link Brain 设置页检查状态，或运行 link-brain login。MCP {tool} 说「{joined}」")
    return AdapterError(f"MCP {tool} 报错: {joined}")


async def _call_mcp(tool: str, arguments: dict[str, Any], *, endpoint: str, timeout: float) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    # sse_read_timeout 才是绑响应读取的那个（默认 300s）：get_feed_detail 的结果走 SSE 流回来，
    # 只设 timeout 不设它，热门笔记滚评论超 300s 仍会 httpx.ReadTimeout。两个都给到 timeout。
    async with streamablehttp_client(
        endpoint, timeout=timeout, sse_read_timeout=timeout
    ) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            if result.isError:
                texts = [getattr(c, "text", "") for c in result.content]
                raise tool_error(tool, " ".join(texts)[:400])
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
    parts = [f"{type(exc).__name__}: {exc}"]  # errtext-ok
    for sub in getattr(exc, "exceptions", ()) or ():
        parts.append(flatten_exc(sub))
    if exc.__cause__ is not None:
        parts.append(flatten_exc(exc.__cause__))
    return " | ".join(parts)


def call_tool(tool: str, arguments: dict[str, Any], *, endpoint: str | None = None,
              timeout: float = 300) -> Any:
    """同步调一个 MCP 工具，并记一行用号行为日志（1016，actionlog）。见 _call_tool。"""
    import time as _time
    from .. import actionlog
    t0 = _time.monotonic()
    item = str(arguments.get("feed_id") or "")
    try:
        out = _call_tool(tool, arguments, endpoint=endpoint, timeout=timeout)
    except Exception as exc:
        actionlog.record(actionlog.action_for_tool(tool, arguments), ok=False, item=item,
                         code=str(getattr(exc, "code", "") or ""), detail=str(exc), secs=_time.monotonic() - t0)
        raise
    extra = {}
    if isinstance(out, dict):
        data = out.get("data") if isinstance(out.get("data"), dict) else {}
        cl = out.get("comment_load") or data.get("comment_load")
        if isinstance(cl, dict):
            extra = {"sub_clicks": cl.get("clicks"), "stop": cl.get("stop_reason"), "missing": cl.get("replies_missing")}
    actionlog.record(actionlog.action_for_tool(tool, arguments), ok=True, item=item, secs=_time.monotonic() - t0, **extra)
    return out


def _call_tool(tool: str, arguments: dict[str, Any], *, endpoint: str | None = None,
               timeout: float = 300) -> Any:
    """同步调一个 MCP 工具；连不上/服务内部错一律升级成 `ServiceDownError`。

    默认地址的服务没起时先在本机拉起再调（只拉一次，不循环重试）。
    """
    if endpoint is None:
        from .. import accounts
        endpoint = accounts.endpoint()
        try:
            accounts.ensure_reader()
        except accounts.ReaderError as exc:
            err = (AccountBlockedError if exc.needs_human else ServiceDownError)(
                f"{exc}：{accounts.SOLUTIONS.get(exc.code, ('', '', '请打开 Link Brain 设置页查看', ''))[2]}")
            err.code = exc.code
            raise err from exc
    try:
        return asyncio.run(_call_mcp(tool, arguments, endpoint=endpoint, timeout=timeout))
    except NeedsHumanError:
        raise
    except Exception as exc:  # noqa: BLE001 - 连不上 18060 是"服务出事了"，不是这条链接的问题
        # 1001（B-1）：_call_mcp 在 streamablehttp_client 里面抛的异常会被 anyio 包进 ExceptionGroup，
        # `except NeedsHumanError` 接不住 → 撞了验证码还被当普通错误、整批接着抓。先拆开，原样抛出里面那个。
        for kind in (NeedsHumanError, AdapterError):
            inner = _find_in_group(exc, kind)
            if inner is not None and inner is not exc:
                raise inner from None
        text = flatten_exc(exc)
        # 这里是任意异常（连接断了、超时、解析错……）的展开文本：只认读取服务明确给的风险码（方括号标记 /
        # website-login），不套 BLOCKED_HINTS 那种宽泛词——「429」「登录后」撞上笔记 id 或 URL 就会误停整晚、
        # 还会让插件把空码当掉登录去弹扫码。宽泛词只用在 _call_mcp 里 MCP 工具自己报的 isError 文本上。
        if risk_code(text):
            raise _blocked_error(f"读取账号需要处理：请在 Link Brain 设置页检查并重新扫码。详情：{text[:300]}",
                                 text) from exc
        if looks_service_down(text) or isinstance(exc, (OSError, ConnectionError)):
            raise ServiceDownError(
                f"读取服务未连接：请在 Link Brain 设置页点击登录，或运行 link-brain login。详情：{text[:300]}"
            ) from exc
        # 1012：别的异常原样抛 ExceptionGroup 的话，上层 `str(exc)` 只剩「unhandled errors in a TaskGroup
        # (1 sub-exception)」，同步记录里看不出真因（1011 全量测试 3 篇就是这样）。拆开：只有一个就抛它本身，
        # 多个就带上摊开的全文。
        if getattr(exc, "exceptions", None):
            leaves = _leaves(exc)
            if len(leaves) == 1:
                raise leaves[0] from exc
            raise AdapterError(text[:600]) from exc
        raise


def _leaves(exc: BaseException) -> list[BaseException]:
    subs = getattr(exc, "exceptions", None)
    if not subs:
        return [exc]
    return [leaf for sub in subs for leaf in _leaves(sub)]


def check_login_status(*, endpoint: str | None = None, timeout: float = 60) -> Any:
    """确认 MCP 登录态还在（浏览器补抓之后必须跑一次）。"""
    return call_tool("check_login_status", {}, endpoint=endpoint, timeout=timeout)


def fetch_detail(
    note_id: str,
    xsec_token: str,
    *,
    endpoint: str | None = None,
    comment_limit: int = 200,
    reply_limit: int = 100,
    full_comments: bool = False,
    timeout: float = 600,
    comment_budget_s: int | None = None,
    expand_floors: list[str] | None = None,
    expand_resume: list[str] | None = None,
    click_more_replies: bool = True,
    floors_resume: str | None = None,
) -> dict[str, Any]:
    """调 `get_feed_detail`，返回**原始**响应（原样落 `mcp_raw.json`）。

    默认 `full_comments=False`（Owner 2026-09-07 拍板）：只取**前 10 楼一级评论 + 它们的楼中楼**
    （`load_all_comments=false` 的默认返回，秒回）。热门笔记（评论几十上百、要滚完整评论区 +
    逐条展开楼中楼）在本机高负载下滚不完、常 httpx.ReadTimeout——评论主体够了就不为深层回复卡死。
    需要全量评论时显式 `full_comments=True`（会滚完整评论区，慢，只适合机器空闲时）。
    """
    if not xsec_token:
        raise AdapterError("缺 xsec_token，MCP 无法抓取（短链没带 token？）")
    if full_comments:
        arguments = {
            "feed_id": note_id,
            "xsec_token": xsec_token,
            "load_all_comments": True,
            "limit": comment_limit,
            "click_more_replies": bool(click_more_replies),
            "reply_limit": reply_limit,
            "scroll_speed": "normal",
        }
        if floors_resume:
            arguments["floors_resume"] = floors_resume  # 1017：读取组件 >= reader-11 才认，老组件忽略即从第 1 楼滚起
        if comment_budget_s:
            arguments["comment_budget_s"] = int(comment_budget_s)  # 读取组件：评论在预算前 30 秒收手并如实报 comment_load
        if expand_floors:
            # 1008 续读：只展开这些楼（上次预算用完没读全的），其它楼不点；读取组件 ≥ r03 才认，老组件忽略即退回整读
            arguments["expand_floors"] = list(expand_floors)
            if expand_resume:
                # 1017 断点续展："comment_id:cursor:have"——读取组件 ≥ reader-10 才认，老组件忽略即从头展开
                arguments["expand_resume"] = list(expand_resume)
    else:
        # 默认：前 10 楼 + 楼中楼，不滚全评论区。
        arguments = {
            "feed_id": note_id,
            "xsec_token": xsec_token,
            "load_all_comments": False,
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
    candidates = [entry for group in streams.values() for entry in (group or [])
                  if isinstance(entry, dict) and entry.get('masterUrl')]
    def codec_rank(entry):
        codec = str(entry.get('codec') or entry.get('videoCodec') or '').lower()
        return {'h264': 0, 'avc': 0, 'avc1': 0, 'av1': 1, 'h265': 2, 'hevc': 2}.get(codec, 3)
    best = min(candidates, key=codec_rank) if candidates else {}
    return {
        "video_url": (best or {}).get("masterUrl"),
        "backup_urls": best.get('backupUrls') or [],
        "codec": best.get('codec') or best.get('videoCodec'),
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


# 1008（L6·B3）：游客补查的保险丝只认这些「验证专用词」（不用笼统的「登录」——游客页本来就到处是登录按钮）
CAPTCHA_HINTS = ("验证码", "captcha", "滑块", "安全验证", "访问频繁", "website-login")


def captcha_page(text: str | None) -> bool:
    low = (text or "").lower()
    return any(h.lower() in low for h in CAPTCHA_HINTS)


# 风控状态码（461 / 471）：服务器直接拒了这次访问，和「这篇没了」不是一回事
CAPTCHA_STATUS = (461, 471)


def _guest_captcha_response(resp: Any) -> bool:
    """游客这次响应是不是落到了验证 / 风控：跳到 website-login / captcha、风控状态码、或页面上有验证专用词。"""
    if getattr(resp, "status_code", 200) in CAPTCHA_STATUS:
        return True
    final = str(getattr(resp, "url", "") or "").lower()
    if "website-login" in final or "captcha" in final:
        return True
    text = getattr(resp, "text", "") or ""
    if INITIAL_STATE_RE.search(text):
        # 有 SSR 状态的正常页：只有没这条笔记时才看验证词（交给下面的分支），避免正文里提到「验证码」误停
        return False
    return captcha_page(text[:8000])


def fetch_related_file(note_id: str, xsec_token: str | None, *, timeout: int = 30,
                       stop_on_captcha: bool = False) -> dict[str, Any]:
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
        if stop_on_captcha and _guest_captcha_response(resp):
            # 游客页落到验证 / 风控：不管状态码、有没有 __INITIAL_STATE__，都立刻停，
            # 不再起游客浏览器兜底（附件补查的保险丝，见 attachments.recheck_guest）
            result["captcha"] = True
            result["blocked"] = True
            result["error"] = "游客打开笔记页时出现了安全验证 / 访问频繁的页面"
            return result
        resp.raise_for_status()
        match = INITIAL_STATE_RE.search(resp.text)
        if not match:
            result["error"] = "笔记页里没有 __INITIAL_STATE__"
        else:
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
                if stop_on_captcha and captcha_page(resp.text[:8000]):
                    # 游客页上出现了验证专用词：立刻停，不再起游客浏览器兜底（附件补查的保险丝，见 attachments.recheck_guest）
                    result["captcha"] = True
                    result["error"] = "游客打开笔记页时出现了安全验证 / 访问频繁的页面"
                    return result
            else:
                result["ok"] = True
                result["related_file"] = note.get("relatedFile") or None
    except Exception as exc:  # noqa: BLE001 - 探测失败退回正文启发式，不阻断
        result["error"] = errtext(exc)

    # 裸 httpx 被反爬喂占位页（拿不到笔记）时，回落到干净游客浏览器读 relatedFile。
    # doc_id 只对游客可见（登录态会藏掉），所以兜底一律用一次性空 profile。
    if not result["ok"]:
        fb = _probe_related_file_via_browser(note_id, xsec_token, timeout=100)
        if fb.get("ok"):
            result["ok"] = True
            result["related_file"] = fb["related_file"]
            result["error"] = None
            result["via"] = "guest-browser"
            result["blocked"] = False
        else:
            result["error"] = (result.get("error") or "") + f"；游客浏览器兜底：{fb.get('error')}"
            # 游客浏览器自己出错（没装 / 起不来 / 超时），区别于「打开了但没这条笔记」
            result["browser_error"] = not str(fb.get("error") or "").startswith("游客浏览器也没读到")
    return result


# 游客浏览器兜底：doc_id 只对游客可见，用一次性空 profile 保证不带登录态。
# 第 5 批：位置可配置。环境变量 LINK_BRAIN_RELATEDFILE_EXE 指定就只用它；否则按 accounts.tool_roots() 找
# （`reader install` 装的 ~/.link-brain/bin → 程序目录 tools/ → 组件目录，默认 ~/.xiaohongshu-mcp，老用户不受影响）。
RELATEDFILE_EXE = os.environ.get("LINK_BRAIN_RELATEDFILE_EXE", "")
RELATEDFILE_NAMES = ("relatedfile.exe", "relatedfile")


def relatedfile_exe() -> str:
    """relatedfile 的路径；哪里都没有时返回组件目录下的默认位置（报错信息里给人看）。"""
    if RELATEDFILE_EXE:
        return RELATEDFILE_EXE
    from .. import accounts
    for root in accounts.tool_roots():
        for name in RELATEDFILE_NAMES:
            if (root / name).is_file():
                return str(root / name)
    return str(accounts.tool_dir() / RELATEDFILE_NAMES[0 if os.name == "nt" else 1])


def _probe_related_file_via_browser(
    note_id: str, xsec_token: str | None, *, timeout: int = 100
) -> dict[str, Any]:
    """开一个干净游客浏览器读 `relatedFile`（裸 httpx 被反爬挡住时的兜底）。

    XHS_PROFILE_DIR 指向一次性空目录 = 游客（绝不复用 momo/6A 登录 profile，
    登录态会把 relatedFile 藏掉）。返回 `{"ok", "related_file", "error"}`。
    """
    exe = relatedfile_exe()
    if not os.path.exists(exe):
        return {"ok": False, "related_file": None,
                "error": f"缺 relatedfile.exe（{exe}）：用 `python -m link_brain reader install` 装读取组件，或自己编译后放进组件目录"}
    tmp = tempfile.mkdtemp(prefix="xhs-guest-")
    # 关键：预置 "Local State" 让浏览器把这个 profile 当"非首次"，从而走 headless——
    # 否则 browser.go 对全新 profile 强制 headed，会在 Owner 屏幕上弹窗（每晚同步都弹）。
    try:
        (__import__("pathlib").Path(tmp) / "Local State").write_text("{}", encoding="utf-8")
    except OSError:
        pass
    env = dict(os.environ)
    env["XHS_PROFILE_DIR"] = tmp
    args = [exe, "-note", note_id]
    if xsec_token:
        args += ["-token", xsec_token]
    try:
        proc = subprocess.run(args, capture_output=True, env=env, timeout=timeout)
        out = (proc.stdout or b"").decode("utf-8", "replace").strip()
        line = next((l for l in reversed(out.splitlines()) if l.startswith("{")), "")
        data = json.loads(line) if line else {}
        rf = data.get("relatedFile")
        # 0926：页面读到了这条笔记（hasNote）但没有 relatedFile = 确实没附件，算查清；读不到笔记才算失败
        seen = bool(rf) or bool(data.get("hasNote"))
        return {"ok": seen, "related_file": rf,
                "error": None if seen else "游客浏览器也没读到这条笔记（已删 / 被拦）"}
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        return {"ok": False, "related_file": None,
                "error": f"游客浏览器探测失败: {type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
        # 0926 起读取组件透传 pictures / audioInfo（之前组件把这两个字段丢了，才一直是空）。
        "images": _images(raw.get("pictures") if isinstance(raw.get("pictures"), list) else None),
    }
    audio = raw.get("audioInfo") if isinstance(raw.get("audioInfo"), dict) else None
    if audio and (audio.get("playInfo") or {}).get("url"):
        # 站点自带转写 asrText；tagText 形如「·在讲广东话」「·识别到在唱歌」
        entry["audio"] = {
            "audio_id": str(audio.get("audioId") or ""),
            "url": audio["playInfo"]["url"],
            "duration_ms": _int_or_none(audio.get("duration")),
            "asr_text": audio.get("asrText") or "",
            "tag": (audio.get("tagText") or "").lstrip("·").strip(),
        }
    if floor == 1:
        entry["sub_comment_count"] = declared
        entry["sub_comments"] = [_comment(s, 2) for s in subs_raw]
        entry["sub_comments_complete"] = len(subs_raw) >= declared
    else:
        entry["target_nickname"] = None
    return entry


# 读取组件说这楼没读全的原因 → 人话（可见页 / 机读版 / 同步记录用）
REPLY_GAP_CN = {
    "not_reached": "评论区太长，这次时间用完", "budget": "评论区太长，这次时间用完", "cancelled": "评论区太长，这次时间用完",
    "cap": "回复太多，这次先到这", "no_growth": "点了展开但没加载出来", "click_failed": "展开按钮点不动",
    "no_button": "页面说还有回复但没有展开按钮", "not_expanded": "这楼没要求展开", "count_mismatch": "原站显示的条数比能看到的多（删除 / 折叠）",
    "risk": "撞到风控先停", "throttled": "被限频先停", "stuck": "评论区滚不动",
    "sub_paused": "楼中楼这会儿暂停（每小时额度 / 限频后放慢），下次接着读",
}
# 这些原因下次还能接着读（续读 comments --fill）；count_mismatch / no_button / not_expanded 读多少次都一样，不续
RESUMABLE_GAPS = ("not_reached", "budget", "cancelled", "cap", "no_growth", "click_failed", "throttled", "stuck", "risk",
                  "sub_paused")


def compact_comment_load(raw: Any) -> dict[str, Any] | None:
    """读取组件的 `comment_load` 压成归档里存的那份：判停原因、读到几楼、展开几楼、缺多少条、哪几楼缺（只留真缺口）。
    老读取组件没有这个字段 → None。gaps 只收 missing>0 的楼：旧组件会把「已展开完但页面状态陈旧 hasMore=true」的楼也列进来，
    那不是缺口（r03 组件已修，这里再挡一道）。"""
    if not isinstance(raw, dict):
        return None
    gaps = []
    for g in raw.get("replies_partial") or []:
        if not isinstance(g, dict):
            continue
        try:
            missing = int(g.get("missing") or 0)
        except (TypeError, ValueError):
            missing = 0
        if missing <= 0:
            continue
        gaps.append({"floor": _int_or_none(g.get("floor")), "comment_id": str(g.get("comment_id") or ""),
                     "shown": _int_or_none(g.get("shown")), "loaded": _int_or_none(g.get("loaded")), "missing": missing,
                     "reason": str(g.get("reason") or "")})
    out = {
        "floor_limit": _int_or_none(raw.get("floor_limit")),
        "floors_loaded": _int_or_none(raw.get("floors_loaded")),
        "floors_expanded": _int_or_none(raw.get("floors_expanded")),
        "has_more": raw.get("comments_has_more") if isinstance(raw.get("comments_has_more"), bool) else None,
        "stop_reason": str(raw.get("stop_reason") or ""),
        "partial": bool(raw.get("partial")) and bool(gaps),
        "replies_missing": sum(g["missing"] for g in gaps),
        "seconds": raw.get("seconds"),
        "gaps": gaps,
    }
    if raw.get("floors_not_found"):
        out["floors_not_found"] = [str(x) for x in raw["floors_not_found"]]
    return out


def _reply_key(s: dict[str, Any]) -> str:
    cid = str(s.get("comment_id") or "")
    if cid:
        return cid
    return "|".join(str(x) for x in ((s.get("author") or {}).get("user_id"), s.get("created_at"), s.get("text")))


def _union_replies(prev: list[dict[str, Any]], cur: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """楼中楼并集，归档不丢：旧版有、这次没有的（删了 / 折叠了 / 这次没展开到）留着。
    顺序（1017 起）：以旧版为底，这次新冒出来的插到「这次响应里它后面第一条旧版已有的」前面，后面没有旧的就接在末尾——
    断点续展时这次只有「首条 + 接着拉的」，新的接在旧的末尾，不会把存过的一百多条挤到后面；从头读时和这次读到的顺序一致。"""
    out = list(prev)
    pos = {_reply_key(s): i for i, s in enumerate(out)}
    if len(pos) != len(out):  # 旧版自己有重复：去重后再合
        out, pos = [], {}
        for s in prev:
            if _reply_key(s) not in pos:
                pos[_reply_key(s)] = len(out)
                out.append(s)
    keys = [_reply_key(s) for s in cur]
    for j, s in enumerate(cur):
        k = keys[j]
        if k in pos:
            out[pos[k]] = s  # 同一条以这次的为准（点赞数等会变）
            continue
        nxt = next((pos[x] for x in keys[j + 1:] if x in pos), None)
        out.insert(len(out) if nxt is None else nxt, s)
        pos = {_reply_key(x): i for i, x in enumerate(out)}
    return out


def merge_comments(old: list[dict[str, Any]], new: list[dict[str, Any]], expanded: set[str],
                   *, keep_old_order: bool = False) -> list[dict[str, Any]]:
    """续读合并（1009 起一律并集，「调小不删已抓的」）：每楼的楼中楼 = 新旧并集；原站显示数以这次页面上的为准
    （1017：以前取较大的——回复被删以后原站显示 3→1，存档却一直记 3，缺口永远补不上、续读次次白跑）。
    一级评论默认以新响应的顺序为准，老版本有、新响应没滚到的楼接在后面（删除的评论留着：归档不丢）；
    keep_old_order=True（只展开几楼的续读，新响应里只有那几楼）：保持老顺序，新冒出来的楼接在后面。"""
    by_id_old = {str(c.get("comment_id") or ""): c for c in old}
    by_id_new = {str(c.get("comment_id") or ""): c for c in new}

    def merged(c: dict[str, Any], prev: dict[str, Any] | None) -> dict[str, Any]:
        if not prev:
            return c
        subs = _union_replies(prev.get("sub_comments") or [], c.get("sub_comments") or [])
        count = int(c.get("sub_comment_count") or 0)  # 这次页面上原站显示的条数（删了的回复照旧留在存档里）
        return {**c, "sub_comments": subs, "sub_comment_count": count, "sub_comments_complete": len(subs) >= count}

    out = []
    if keep_old_order:
        for c in old:
            cid = str(c.get("comment_id") or "")
            out.append(merged(by_id_new[cid], c) if cid in by_id_new else c)
        for c in new:
            if str(c.get("comment_id") or "") not in by_id_old:
                out.append(c)
    else:
        seen = set()
        for c in new:
            cid = str(c.get("comment_id") or "")
            seen.add(cid)
            out.append(merged(c, by_id_old.get(cid)))
        for c in old:
            if str(c.get("comment_id") or "") not in seen:
                out.append(c)
    for c in out:
        c["floor"] = 1  # 一级评论的层级字段（不是楼序）
    return out


def comments_signature(comments: list[dict[str, Any]]) -> list[tuple[str, int, tuple[str, ...]]]:
    """评论区「有没有多拿到东西」的指纹：每楼 id、原站显示数、楼中楼 id 集合（续读没多拿到就不写新 RAW 版本）。"""
    return sorted((str(c.get("comment_id") or ""), int(c.get("sub_comment_count") or 0),
                   tuple(sorted(_reply_key(s) for s in c.get("sub_comments") or []))) for c in comments)


def merge_comment_load(old: dict[str, Any] | None, new: dict[str, Any] | None, expanded: set[str],
                       comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """续读后的 comment_load：这次要的楼以新结果为准，其它楼沿用老缺口；缺口按合并后的评论重算 missing。"""
    if new is None and old is None:
        return None
    base = dict(new or old or {})
    old_gaps = {g.get("comment_id"): g for g in ((old or {}).get("gaps") or []) if g.get("comment_id")}
    new_gaps = {g.get("comment_id"): g for g in ((new or {}).get("gaps") or []) if g.get("comment_id")}
    gaps: dict[str, dict[str, Any]] = {}
    for cid, g in old_gaps.items():
        if cid not in expanded:
            gaps[cid] = dict(g)
    for cid, g in new_gaps.items():
        gaps[cid] = dict(g)
    # 按合并后的评论重算：楼里实际有多少、原站显示多少
    have = {str(c.get("comment_id") or ""): c for c in comments}
    kept = []
    for cid, g in gaps.items():
        c = have.get(cid)
        if c is not None:
            loaded = len(c.get("sub_comments") or [])
            shown = int(c.get("sub_comment_count") or g.get("shown") or 0)
            g["loaded"], g["shown"], g["missing"] = loaded, shown, max(0, shown - loaded)
        if int(g.get("missing") or 0) > 0:
            kept.append(g)
    base["gaps"] = kept
    base["replies_missing"] = sum(int(g["missing"]) for g in kept)
    base["partial"] = bool(kept) and str(base.get("stop_reason") or "") not in ("end", "no_comments")
    base["fill_attempts"] = int((old or {}).get("fill_attempts") or 0) + (1 if new is not None else 0)
    base["fill_last_at"] = (new or {}).get("fill_last_at") or (old or {}).get("fill_last_at")
    return base


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
    comment_load = compact_comment_load(data.get("comment_load"))

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
            "comment_load": comment_load,
            "web_probe": (
                None
                if web_probe is None
                else {"ok": web_probe.get("ok"), "url": web_probe.get("url"), "error": web_probe.get("error")}
            ),
            "notes": [],
        },
    }
