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


def fetch(parsed: Parsed, opts: FetchOptions) -> Fetched:
    """开页抓详情（服务没起来自己重试）+ 笔记网页版探附件（游客被挡就用登录号补看）。1025 第二波 PR⑤b 从 ingest_url 搬来。

    opts.extra 认这几个小红书自己的键：expand_floors / expand_resume / floors_resume（评论续展，见 comment_fill）。
    raw_files = mcp_raw.json（读取服务原样返回）+ web_raw.json（网页探测原样结果）；context 带 web_probe 给 normalize，
    续展时带上一版 source 给 normalize 合并（只展开了指定的楼，其它楼的楼中楼沿用上一版）。"""
    from ... import problems, storage

    log, ex = opts.log, opts.extra
    expand_floors = ex.get("expand_floors")
    log(f"MCP {adapter.MCP_TOOL} @ {adapter.MCP_ENDPOINT}")
    if opts.progress:
        kw = adapter._detail_kwargs(opts.comment_floors, expand_floors, None)
        cap = int(kw.get("timeout") or 600) // 60
        opts.progress("read", f"打开这篇，把评论一楼一楼展开读下来（热门笔记要几分钟到十几分钟，最多 {cap} 分钟）")
    raw = adapter._fetch_with_retry(parsed, log=log, comment_floors=opts.comment_floors, budget_left=opts.budget_left,
                                    expand_floors=expand_floors, fill_budget_s=None, progress=opts.progress,
                                    expand_resume=ex.get("expand_resume"), floors_resume=ex.get("floors_resume"))
    problems.resolve("ingest", None)  # 抓到了 = 读取服务好着：之前「服务没起来 / 超时」那几条步骤级问题算解决（要在网页探测之前）
    probe = _web_probe(parsed, log)
    context: dict[str, Any] = {"web_probe": probe, "log": log, "log_comment_load": True}
    meta_path = storage.object_dir(name, parsed["note_id"]) / "meta.json"
    if expand_floors and meta_path.is_file():
        prev_meta = storage.read_json(meta_path)
        ver = prev_meta.get("current_version")
        prev_src = storage.raw_dir(name, parsed["note_id"], ver) / "source.json" if ver else None
        if prev_src is not None and prev_src.is_file():  # 上一版不完整（待重建索引）就不合并，照常存
            context["previous_source"] = storage.read_json(prev_src)
            context["expand_floors"] = list(expand_floors)
    return Fetched(raw_files={"mcp_raw.json": raw, "web_raw.json": probe}, context=context)


def _web_probe(parsed: Parsed, log) -> dict[str, Any]:
    """附件元数据只有笔记网页版有（MCP 不返回），游客可见；失败不阻断。"""
    from ... import domain, problems

    sid = parsed["note_id"]
    log(f"网页探测附件 {adapter.CANONICAL_FMT.format(note_id=sid)}")
    web_probe = adapter.fetch_related_file(sid, parsed.get("xsec_token"))
    if not web_probe["ok"]:
        # 0929：游客被登录墙挡住的笔记（附件照样有）当场用登录号再看一次，别等夜里补查
        from ...attachments import _probe_logged_in
        logged = _probe_logged_in(sid, parsed.get("xsec_token"))
        if logged.get("needs_human"):
            # 1001：登录号补看撞到掉登录 / 风控 → 整批停车，别拿这篇的半截结果入库，也别接着开下一篇
            err = adapter.AccountBlockedError(f"读取账号需要处理：{logged.get('error')}")
            err.code = logged.get("code") or ""
            raise err
        if logged.get("ok"):
            log("游客看不到，登录号看到了笔记页（附件元数据取自登录号）")
            web_probe = {**web_probe, **logged}
        else:
            web_probe["error"] = f"{web_probe.get('error')}；登录号：{logged.get('error')}"
    if not web_probe["ok"]:
        log(f"网页探测失败（退回正文线索）: {web_probe['error']}")
        if web_probe.get("blocked"):
            # 游客网页那侧被拦了（验证码 / 登录墙），登录号补看也没拿到、但号本身没事（号出事上面已经整批停车）。
            # MCP 还能抓就不中止：只缺附件元数据，夜里 attachments --recheck 会再补查——TRANSIENT，只记不推。
            problems.report("ingest", "TRANSIENT.WEB_PROBE_BLOCKED",
                            f"网页那侧被拦了，附件信息暂缺：{web_probe['error']}"[:200],
                            item_id=domain.item_id(name, sid))
    else:
        problems.resolve("ingest", domain.item_id(name, sid), "TRANSIENT.WEB_PROBE_BLOCKED")
    return web_probe


def normalize(fetched: Fetched, parsed: Parsed, *, captured_at: str) -> dict[str, Any]:
    ctx = fetched.context
    doc = adapter.normalize(fetched.raw_files["mcp_raw.json"], parsed, captured_at=captured_at,
                            web_probe=ctx.get("web_probe"))
    log = ctx.get("log") or (lambda _m: None)
    if ctx.get("expand_floors") and ctx.get("previous_source") is not None:
        # 1008 续读：这次只展开了指定的楼，其它楼的楼中楼沿用上一版（不然新版本反而少了）
        from .comment_fill import _merge_fill
        doc = _merge_fill(doc, ctx["previous_source"], set(ctx["expand_floors"]), captured_at, log)
    if ctx.get("log_comment_load"):
        from .comment_fill import _log_comment_load
        _log_comment_load(doc, log)
    return doc


def meta_fields(source_doc: dict[str, Any]) -> dict[str, Any]:
    """meta.json 里由来源决定的那几项（kind / 标题 / 作者 / 发布时间 / 评论齐没齐 / 附件状态 / 工具版本）。"""
    note = source_doc["note"]
    attachments = note["attachments"]
    statuses = {a.get("status") for a in attachments}
    if not attachments:
        attachments_status = "none"
    elif "downloaded" in statuses:
        attachments_status = "downloaded"
    elif "metadata_only" in statuses:
        attachments_status = "metadata_only"
    else:
        attachments_status = "unavailable"
    return {
        "kind": note["kind"],
        "title": note["title"],
        "author": {k: note["author"][k] for k in ("user_id", "nickname", "profile_url")},
        "published_at": note["published_at"],
        "comments_complete": source_doc["capture"]["comments_complete"],
        "attachments_status": attachments_status,
        "tool_versions": {"adapter": adapter.ADAPTER_VERSION, "mcp_endpoint": adapter.MCP_ENDPOINT},
    }


def fill(parsed: Parsed, conn, existing: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """能力 comments_fill：评论续读（只为评论开页、和上一版合并、没多拿到就不出新版本）。"""
    from .comment_fill import ingest_fill
    return ingest_fill(parsed, conn, existing, **kw)


def fingerprint(source_doc: dict[str, Any]) -> str:
    from ... import index

    return index.normalized_source_sha256(source_doc)


def media_plan(source_doc: dict[str, Any], opts: dict[str, Any]) -> list[MediaTask]:
    note = source_doc["note"]
    is_video = note["kind"] == "video"
    headers = adapter.DOWNLOAD_HEADERS
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
                                  stem=f"comment-{group['comment_id']}-audio", kind="audio"))   # 语音 / 视频历来不带头（10-26 复审核对）
    if opts["downloadVideo"] and is_video and (note.get("video") or {}).get("video_url"):
        tasks.append(dict(role="video", index=1, url=note["video"]["video_url"],
                          stem="video", kind="video", payload=note["video"]))
    return tasks


def attachment_backend():
    """按需加载取件能力，普通来源识别不加载附件队列及转换模块。"""
    import importlib
    return importlib.import_module(__name__ + ".attachments")
