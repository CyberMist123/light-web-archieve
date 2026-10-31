"""B 站来源（阶段一，1029）：一条 BV 链接 → yt-dlp 下载到独立临时目录 → 视频 / 字幕 / 弹幕 / 封面进不可变 RAW。

身份：`source=bilibili`，`source_id=BV…`（带 `?p=N`、N>1 时 `BV…_pN`；本轮只验单 P）。
登录态见 login.py，下载引擎见 ytdlp.py。本模块只实现 `link_brain.sources.Source` 协议，不碰渲染 / 目录 / AI。
这一轮不做：收藏夹、多 P 批量、弹幕可视化、评论区、ASR。
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from ... import storage
from ...errtext import errtext
from .. import Fetched, FetchOptions, MediaTask, Parsed, SourceError
from . import login, ytdlp

name = "bilibili"
version = "bilibili/1"
capabilities: frozenset[str] = frozenset({"albums"})   # albums：收藏夹名当目录里的「专辑」（note_albums，读关系表）
visible_subdir = ("Web", "Bilibili")

CANONICAL_FMT = "https://www.bilibili.com/video/{bvid}"
HOSTS = ("bilibili.com", "b23.tv")
TRAILING = "，。、；：！？）)]】》>\"'“”‘’"
URL_RE = re.compile(r"https?://[^\s<>\"'，。、；：！？（）()\[\]【】《》　-〿一-鿿＀-￯]+")
BV_RE = re.compile(r"\bBV1[0-9A-Za-z]{9}\b")
VIDEO_PATH_RE = re.compile(r"/video/(BV1[0-9A-Za-z]{9})", re.I)

# 一次导入里下载好的本地文件：normalize 登记、media_plan 领走（进程内；media_plan 只拿得到 source.json 的内容）
_PENDING: dict[str, dict[str, Any]] = {}


# ---- 识别 / 解析 ---------------------------------------------------------------------------------------------------

def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def matches(url: str) -> bool:
    return _host_ok(url) and (bool(VIDEO_PATH_RE.search(url)) or "b23.tv" in (urlsplit(url).hostname or ""))


def find_urls(text: str) -> list[str]:
    """消息里的 B 站视频链接（bilibili.com/video/BV… 和 b23.tv 短链）；光秃秃的 BV 号也认（补成标准链接）。按出现顺序去重。"""
    found: list[str] = []
    text = text or ""
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(TRAILING)
        if matches(url) and url not in found:
            found.append(url)
    stripped = URL_RE.sub(" ", text)
    for m in BV_RE.finditer(stripped):
        url = CANONICAL_FMT.format(bvid=m.group(0))
        if url not in found:
            found.append(url)
    return found


def _resolve_short(url: str, *, client: httpx.Client | None = None) -> str:
    own = client is None
    client = client or httpx.Client(headers=login.HEADERS, timeout=20, follow_redirects=True)
    try:
        resp = client.head(url)
        return str(resp.url)
    except httpx.HTTPError as exc:
        raise SourceError(f"短链打不开：{errtext(exc)}") from exc
    finally:
        if own:
            client.close()


def parse(text: str, *, client: httpx.Client | None = None) -> Parsed:
    """链接 / 短链 / 光 BV 号 → {source, source_id, bvid, page, canonical_url, input_url, input_kind}。"""
    raw = (text or "").strip()
    urls = find_urls(raw)
    if not urls:
        raise SourceError(f"不是 B 站视频链接：{raw[:80]}")
    url = urls[0]
    kind = "bvid" if BV_RE.fullmatch(raw) else "url"
    if "b23.tv" in (urlsplit(url).hostname or ""):
        kind = "shortlink"
        url = _resolve_short(url, client=client)
    m = VIDEO_PATH_RE.search(url)
    if not m:
        raise SourceError(f"链接里没有 BV 号：{url[:80]}")
    bvid = "BV" + m.group(1)[2:]
    page = 1
    try:
        page = max(1, int((parse_qs(urlsplit(url).query).get("p") or ["1"])[0]))
    except ValueError:
        page = 1
    canonical = CANONICAL_FMT.format(bvid=bvid) + (f"?p={page}" if page > 1 else "")
    return {"source": name, "source_id": bvid if page == 1 else f"{bvid}_p{page}", "bvid": bvid, "page": page,
            "canonical_url": canonical, "input_url": raw, "input_kind": kind}


# ---- 抓（= 下载）----------------------------------------------------------------------------------------------------

def _login_state(log) -> str:
    """有 cookie 文件就先查一次：失效 → 停下让人重新扫码（不拿过期 cookie 反复撞接口）；没登录过 → 游客。"""
    if not login.has_cookies():
        log("B 站未登录：按游客下载（游客拿不到字幕列表；要字幕先 `python -m link_brain bilibili login`）")
        return "anonymous"
    st = login.status()
    if st["state"] == "logged_out":
        from .. import AccountBlocked
        err = AccountBlocked("B 站登录已失效：请重新扫码（python -m link_brain bilibili login）")
        err.code = "NOT_LOGGED_IN"
        raise err
    if st["state"] == "unknown":
        log(f"B 站登录状态查不到（{st['detail']}），先带着现有登录态试")
    return st["state"]


def fetch(parsed: Parsed, opts: FetchOptions) -> Fetched:
    log = opts.log
    if not ytdlp.ffmpeg_ok():
        from .. import NeedsHuman
        err = NeedsHuman("没有 ffmpeg / ffprobe，无法合并和校验视频：先安装 ffmpeg 再导入")
        err.code = "MISSING_DEPENDENCY"
        raise err
    state = _login_state(log)
    if opts.progress:
        opts.progress("read", "yt-dlp 下载视频 / 字幕 / 弹幕 / 封面（几十秒到几分钟）")
    # 下载用带语言前缀的页面地址（见 ytdlp.DOWNLOAD_URL_FMT）；身份 / 原链接仍是 canonical_url
    result = ytdlp.run(ytdlp.download_url(parsed.get("bvid") or parsed["source_id"], int(parsed.get("page") or 1)),
                       log=log, use_cookies=state != "anonymous")
    video = result["files"]["video"]
    probe = ytdlp.probe_video(video) if video else {"ok": False, "error": "下载器没有写出视频文件"}
    if not probe["ok"]:
        shutil.rmtree(result["dir"], ignore_errors=True)
        code, human = ytdlp.classify_error(result["stderr_tail"]) if not video else ("TRANSIENT.DOWNLOAD_FAILED", probe["error"])
        detail = result["stderr_tail"].splitlines()[-1] if result["stderr_tail"] else ""
        text = f"{human}（yt-dlp 退出码 {result['exit_code']}）" + (f"：{detail}" if detail else "")
        if code.endswith("NOT_LOGGED_IN"):
            from .. import AccountBlocked
            err: SourceError = AccountBlocked(text)
        elif code.endswith("MISSING_DEPENDENCY"):
            from .. import NeedsHuman
            err = NeedsHuman(text)
        else:
            err = SourceError(text)
        err.code = code.split(".", 1)[-1]
        raise err
    log(f"视频 {video.name} {video.stat().st_size} 字节，时长 {probe['duration_sec']} 秒")
    context = {"download": result, "probe": probe, "login_state": state, "log": log}
    return Fetched(raw_files={"ytdlp_info.json": result["info"]}, context=context)


# ---- 规范化 -----------------------------------------------------------------------------------------------------------

def _iso(ts: Any, date8: Any) -> str | None:
    try:
        if ts:
            return datetime.fromtimestamp(int(ts)).astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        pass
    s = str(date8 or "")
    if re.fullmatch(r"\d{8}", s):
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:])).astimezone().isoformat(timespec="seconds")
    return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def normalize(fetched: Fetched, parsed: Parsed, *, captured_at: str) -> dict[str, Any]:
    ctx = fetched.context
    res, probe = ctx["download"], ctx["probe"]
    info = fetched.raw_files.get("ytdlp_info.json") or {}
    files = res["files"]
    state = ctx.get("login_state") or "unknown"

    subs: list[dict[str, Any]] = []
    for s in files["subtitles"]:
        v = ytdlp.validate_srt(s["path"])
        subs.append({"lang": s["lang"], "status": "ok" if v["ok"] else "failed", "cues": v["cues"], "chars": v["chars"],
                     "error": v["error"], "path": s["path"]})
    if not subs:
        if state == "anonymous" or res.get("need_login_subtitle"):
            sub_missing = {"status": "unavailable", "reason": "未登录：B 站不向游客提供字幕列表（扫码登录后重新导入可补）"}
        else:
            sub_missing = {"status": "unavailable", "reason": "来源无字幕"}
    else:
        sub_missing = None
    if files["danmaku"]:
        dv = ytdlp.validate_danmaku(files["danmaku"])
        danmaku = {"status": ("ok" if dv["count"] else "empty_source") if dv["ok"] else "failed", "count": dv["count"],
                   "error": dv["error"], "path": files["danmaku"]}
    elif res.get("danmaku_wanted") is False:
        # 1031 她：同步选项「不存弹幕」——没让下载器去拿，不算没拿到
        danmaku = {"status": "skipped", "count": 0, "error": "这次没存弹幕（同步选项关了）", "path": None}
    else:
        danmaku = {"status": "failed", "count": 0, "error": "下载器没有写出弹幕 XML", "path": None}

    author_id = str(info.get("uploader_id") or "") or None
    note = {
        "note_id": parsed["source_id"],
        "bvid": parsed.get("bvid") or info.get("bvid"),
        "page": parsed.get("page") or 1,
        "cid": _int(info.get("cid")),
        "canonical_url": parsed["canonical_url"],
        "kind": "video",
        "title": str(info.get("title") or "").strip() or parsed["source_id"],
        "body": str(info.get("description") or ""),
        "hashtags": [str(t).strip() for t in (info.get("tags") or []) if str(t).strip()][:30],
        "links": [],
        "author": {"user_id": author_id, "nickname": str(info.get("uploader") or ""), "avatar_url": None,
                   "profile_url": info.get("uploader_url") or (f"https://space.bilibili.com/{author_id}" if author_id else None)},
        "published_at": _iso(info.get("timestamp"), info.get("upload_date")),
        "ip_location": None,
        "engagement": {"liked": _int(info.get("like_count")), "collected": None, "comment_count": _int(info.get("comment_count")),
                       "shared": _int(info.get("repost_count")), "viewed": _int(info.get("view_count"))},
        "images": [],
        "video": {"video_url": None, "cover_url": info.get("thumbnail"), "duration_sec": probe.get("duration_sec") or _int(info.get("duration")),
                  "downloaded": bool(probe.get("ok")), "width": probe.get("width"), "height": probe.get("height"),
                  "vcodec": probe.get("vcodec"), "acodec": probe.get("acodec"), "has_audio": bool(probe.get("has_audio")),
                  "quality": ((res.get("tv") or {}).get("label") if res.get("stream") == "tv" else None)
                  or info.get("format_note") or info.get("resolution"),
                  "stream": res.get("stream") or "web"},
        "subtitles": [{k: v for k, v in s.items() if k != "path"} for s in subs] or ([sub_missing] if sub_missing else []),
        "danmaku": {k: v for k, v in danmaku.items() if k != "path"},
        "attachments": [],
    }
    capture = {
        "captured_at": captured_at,
        "input_url": parsed["input_url"],
        "input_kind": parsed["input_kind"],
        "adapter": version,
        "downloader": {"name": "yt-dlp", "version": ytdlp.version(), "exit_code": res["exit_code"],
                       "cookies_used": bool(res.get("cookies_used")), "seconds": res.get("duration_s"),
                       "quality": res.get("quality"),   # 1031：画质档（max / 1080 / 720），预估按档取样
                       "stream": res.get("stream") or "web",   # 1031：tv = 电视端（多为无水印）片源；web = yt-dlp 网页流
                       "tv": res.get("tv"), "tv_error": res.get("tv_error")},
        "login": state,
        "comments_complete": "unknown",
        "web_probe": None,
        "notes": [res["stderr_tail"]] if res["exit_code"] != 0 and res["stderr_tail"] else [],
    }
    doc = {"schema_version": 1, "source": name, "source_id": parsed["source_id"], "note": note, "comments": [], "capture": capture}
    _PENDING[parsed["source_id"]] = {"dir": res["dir"], "video": files["video"], "cover": files["cover"], "probe": probe,
                                     "subs": subs, "danmaku": danmaku, "sub_missing": sub_missing, "page_url": parsed["canonical_url"]}
    return doc


def meta_fields(source_doc: dict[str, Any]) -> dict[str, Any]:
    note = source_doc["note"]
    return {
        "kind": "video",
        "title": note.get("title"),
        "author": {k: (note.get("author") or {}).get(k) for k in ("user_id", "nickname", "profile_url")},
        "published_at": note.get("published_at"),
        "comments_complete": "unknown",
        "attachments_status": "none",
        "tool_versions": {"adapter": version, "downloader": "yt-dlp " + str((source_doc.get("capture") or {}).get("downloader", {}).get("version") or "?")},
    }


def fingerprint(source_doc: dict[str, Any]) -> str:
    """内容指纹：标题 / 简介 / 作者 / 发布时间 / 时长 / 视频有没有下到 / 哪些语言的字幕下到了。弹幕条数、播放数这类会自然变的不算。"""
    import hashlib
    note = source_doc.get("note") or {}
    payload = {
        "source": source_doc.get("source"), "source_id": source_doc.get("source_id"),
        "title": note.get("title"), "body": note.get("body"), "author": (note.get("author") or {}).get("user_id"),
        "published_at": note.get("published_at"), "duration": (note.get("video") or {}).get("duration_sec"),
        "video": bool((note.get("video") or {}).get("downloaded")),
        "subtitles": sorted(s.get("lang") or "" for s in note.get("subtitles") or [] if s.get("status") == "ok"),
        "danmaku": (note.get("danmaku") or {}).get("status") in ("ok", "empty_source"),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def media_plan(source_doc: dict[str, Any], opts: dict[str, Any]) -> list[MediaTask]:
    """把 yt-dlp 已经写出的本地文件交给通用下载计划（kind=file：挪进 assets、算 bytes / sha256）；没拿到的也留一条带状态。
    `opts`（小红书的 downloadImages / downloadVideo 设置）这里不看：B 站入库的意义就是视频本体。"""
    sid = source_doc.get("source_id") or ""
    pending = _PENDING.pop(sid, None)
    if pending is None:
        return []
    page_url = pending["page_url"]
    cleanup = str(pending["dir"])
    tasks: list[MediaTask] = []
    probe = pending["probe"]
    tasks.append(dict(role="video", index=1, kind="file", url=page_url, stem="video",
                      payload={"path": str(pending["video"]), "cleanup": cleanup, "mime": "video/mp4",
                               "extra": {"duration_sec": probe.get("duration_sec"), "width": probe.get("width"),
                                         "height": probe.get("height"), "vcodec": probe.get("vcodec"), "acodec": probe.get("acodec")}}))
    if pending["cover"]:
        tasks.append(dict(role="video_cover", index=1, kind="file", url=str((source_doc["note"].get("video") or {}).get("cover_url") or page_url),
                          stem="cover-001", payload={"path": str(pending["cover"]), "cleanup": cleanup, "image": True}))
    for i, s in enumerate(pending["subs"], start=1):
        lang = re.sub(r"[^0-9A-Za-z_-]", "_", s["lang"] or "und")
        tasks.append(dict(role="subtitle", index=i, kind="file", url=page_url, stem=f"subtitle.{lang}",
                          payload={"path": str(s["path"]), "cleanup": cleanup, "mime": "application/x-subrip",
                                   "status": s["status"], "error": s.get("error"),
                                   "extra": {"lang": s["lang"], "cues": s.get("cues"), "format": "srt"}}))
    if pending["sub_missing"]:
        tasks.append(dict(role="subtitle", index=1, kind="file", url=page_url, stem="subtitle",
                          payload={"path": None, "cleanup": cleanup, "status": "unavailable", "error": pending["sub_missing"]["reason"],
                                   "extra": {"lang": None, "format": "srt"}}))
    d = pending["danmaku"]
    tasks.append(dict(role="danmaku", index=1, kind="file", url=page_url, stem="danmaku",
                      payload={"path": str(d["path"]) if d.get("path") else None, "cleanup": cleanup, "mime": "application/xml",
                               "status": "ok" if d["status"] in ("ok", "empty_source") else d["status"], "error": d.get("error"),
                               "extra": {"count": d.get("count"), "format": "xml",
                                         **({"empty_source": True} if d["status"] == "empty_source" else {})}}))
    return tasks


def after_publish(parsed: Parsed, version_no: int, manifest: dict[str, Any], source_doc: dict[str, Any]) -> None:
    """RAW 发布后：把站点字幕的文字写成 `derived/transcript.json`（status=ok, engine=bilibili-cc），现有渲染 / 目录检索就能读到
    「视频文字稿」；没有字幕写 status=no_subtitle，夜跑的语音转写看到它就不再对这条视频起 ASR（本轮不做 ASR）。
    已有 ASR 转好的文字稿（engine 不是 bilibili-cc）不覆盖。"""
    sid = parsed["source_id"]
    obj = storage.object_dir(name, sid)
    out = storage.derived_dir(name, sid) / "transcript.json"
    try:
        prev = storage.read_json(out) if out.is_file() else {}
    except (OSError, ValueError):
        prev = {}
    if prev.get("status") == "ok" and prev.get("engine") not in (None, "", "bilibili-cc"):
        return
    subs = [m for m in manifest.get("media") or [] if m.get("role") == "subtitle" and m.get("download_status") == "ok" and m.get("file")]
    subs.sort(key=lambda m: (not str(m.get("lang") or "").lower().startswith("zh"), m.get("index") or 0))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    if subs:
        text = ytdlp.srt_text(obj / subs[0]["file"])
        doc = {"status": "ok" if text.strip() else "no_subtitle", "text": text, "engine": "bilibili-cc", "lang": subs[0].get("lang"),
               "source": "native_subtitle", "file": subs[0]["file"], "error": None, "last_tried": now}
    else:
        reason = next((m.get("error") for m in manifest.get("media") or [] if m.get("role") == "subtitle"), "来源无字幕")
        doc = {"status": "no_subtitle", "text": "", "engine": "bilibili-cc", "source": "native_subtitle", "error": None,
               "reason": reason, "last_tried": now}
    storage.write_json(out, doc)


# ---- 展示 / 其它协议项（B 站没有评论层 / 专辑 / 账号锁，都给空）--------------------------------------------------------

def source_open_url(note: dict[str, Any], meta: dict[str, Any]) -> str | None:
    return meta.get("canonical_url") or note.get("canonical_url")


def suggested_link_url(raw: Any) -> str:
    m = URL_RE.match(str(raw or "").strip())
    return m.group(0).rstrip(".,;:!?'\"*_~") if m else ""


def is_link_only(text: str | None) -> bool:
    if not text:
        return True
    residual = BV_RE.sub("", URL_RE.sub("", text))
    residual = re.sub(r"[\s，。、；：！？…·\-—|｜/\\【】\[\]（）()<>「」]+", "", residual)
    return not residual


def item_flags(obj_dir: Path) -> list[dict[str, str]]:
    return []


def comment_gap_text(comment: dict[str, Any], missing: int, gap_reasons: dict[str, str] | None,
                     floor_limit: int | None = None, scoped: bool = False) -> str:
    return ""


def comment_status_text(capture: dict[str, Any] | None, comments: list[dict[str, Any]],
                        view: dict[str, Any] | None = None) -> str:
    return ""


def comment_gap_lines(source: dict[str, Any], view: dict[str, Any] | None) -> list[str]:
    return []


def restricted_text(view: dict[str, Any] | None) -> str:
    return ""


def comment_view(source: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    return {}


def note_albums() -> dict[str, list[str]]:
    """BV → 它所在的收藏夹名（关系表里 active 的；favorites.update_relations 写）。目录页按它分「专辑」。"""
    from . import favorites
    out: dict[str, list[str]] = {}
    for row in favorites.load_relations().values():
        bv, title = row.get("bvid"), (row.get("folder_title") or "").strip()
        if bv and title and row.get("active", True):
            lst = out.setdefault(bv, [])
            if title not in lst:
                lst.append(title)
    return out


def action_home() -> Path:
    return login.home()


def action_lock_holder() -> dict[str, Any] | None:
    return None


def action_for_route(route: str) -> str:
    return ""


def attachment_backend() -> Any:
    return None
