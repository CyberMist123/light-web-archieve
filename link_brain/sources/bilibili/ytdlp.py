"""yt-dlp 子进程封装（B 站下载引擎，1029 阶段一）。

只做「起子进程 → 枚举它在独立临时目录里实际写出的文件 → 逐个验真」三件事，不自己解析音视频流、不碰 DASH 合并（都是 yt-dlp + ffmpeg 的活）。
参数一律是数组，不拼 shell；每次下载一个全新的临时目录（`~/.link-brain/bilibili/tmp/dl-…`），完了由 ingest 把文件挪进 RAW 再删目录，
不会误捡上次的残留或别的分 P。

为什么不是任务书首选的 Bili23 CLI：PyPI `bili23-downloader` 3.0.0（唯一版本，非 ScottSloan 官方发布）的 `parse` 在 CLI 路径下不初始化
WBI key 直接 TypeError，`download` 的下载 / 字幕 / 弹幕步骤是占位空函数——1029 在本机实测确认，详见 docs/STATE.md。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from ... import storage
from ...errtext import errtext
from . import login

# 可播放优先：AVC 视频流 + 最好音轨，退到任意视频流 + 音轨，再退到单文件；-S res:1080 按短边限到 1080（竖屏 1080x1920 也对）
FORMAT = "bv*[vcodec^=avc1]+ba/bv*+ba/b"
SORT = "res:1080"
# B 站 CDN（TencentEdgeOne 镜像）对不带 Range 的整文件 GET 返回 567：分段带 Range 请求就正常（1029 实测）
CHUNK = "10M"
# 1029 实测：这台机器的出口 IP 被 B 站风控，`/video/BV…` 页面只回空壳（没有 __INITIAL_STATE__），yt-dlp 报
# "Unable to extract initial state"（yt-dlp issue #17894）；带语言前缀的 `/zh-Hans/video/BV…/` 页面正常。
# stable yt-dlp 的 BiliBili 提取器不认带前缀的 URL，这里随包带一个 1 文件插件放宽正则（= yt-dlp PR #17898 的改动），
# 其余逻辑全部继承已装的 yt-dlp。PR 合进 stable 后可以去掉。
DOWNLOAD_URL_FMT = "https://www.bilibili.com/zh-Hans/video/{bvid}/"
PLUGIN_SRC = r"""# 由 link_brain.sources.bilibili.ytdlp 生成（1029）：让 yt-dlp 的 BiliBili 提取器接受带语言前缀的页面地址（= yt-dlp PR #17898）。
from yt_dlp.extractor.bilibili import BiliBiliIE


class BiliBiliLangIE(BiliBiliIE):
    IE_NAME = 'BiliBili:lang'
    _VALID_URL = (r'https?://(?:www\.)?bilibili\.com/(?:[a-z]{2}(?:-Hans|-Hant)?/)'
                  r'(?:video/|festival/[^/?#]+\?(?:[^#]*&)?bvid=)(?P<prefix>[aAbB][vV])(?P<id>[^/?#&]+)')
    _TESTS = []
"""
PLUGIN_VERSION = "1"
TIMEOUT_S = int(os.environ.get("LWA_BILI_DOWNLOAD_TIMEOUT", str(40 * 60)))
TMP_STALE_S = 6 * 3600
SRT_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}")
# 脱敏：cookie 键值、任何带 query 的地址（签名播放 URL 都长这样）
_SECRET_RE = re.compile(r"(SESSDATA|bili_jct|DedeUserID__ckMd5|DedeUserID|sid|refresh_token|buvid3)=[^;&\s\"']+", re.I)
_QUERY_RE = re.compile(r"(https?://[^\s\"'?]+)\?[^\s\"']*")
# info.json 只留这些键（不要 formats / url / http_headers / 字幕 data：里面有带签名的地址、也太大）
INFO_KEEP = ("id", "title", "description", "uploader", "uploader_id", "uploader_url", "upload_date", "timestamp",
             "duration", "like_count", "view_count", "comment_count", "repost_count", "tags", "thumbnail",
             "webpage_url", "width", "height", "fps", "vcodec", "acodec", "ext", "format_id", "format_note",
             "resolution", "playlist_index", "n_entries", "chapters", "extractor", "_type", "display_id",
             "aid", "cid", "bvid", "page", "epoch")


def argv_base() -> list[str]:
    return [sys.executable, "-m", "yt_dlp"]


def version() -> str | None:
    try:
        out = subprocess.run([*argv_base(), "--version"], capture_output=True, text=True, timeout=60, encoding="utf-8",
                             errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def ffmpeg_ok() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def sanitize(text: str | None, limit: int = 600) -> str:
    s = _SECRET_RE.sub(r"\1=***", str(text or ""))
    s = _QUERY_RE.sub(r"\1?…", s)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    return "\n".join(lines)[-limit:]


def sanitize_info(info: dict[str, Any] | None) -> dict[str, Any]:
    """原样响应里只留身份 / 标题 / 作者 / 数字这类字段；字幕只留语言 + 格式。"""
    info = info or {}
    out: dict[str, Any] = {k: info[k] for k in INFO_KEEP if k in info}
    for key in ("subtitles", "requested_subtitles"):
        subs = info.get(key)
        if isinstance(subs, dict):
            out[key] = {lang: sorted({str(x.get("ext") or "") for x in (v if isinstance(v, list) else [v]) if isinstance(x, dict)})
                        for lang, v in subs.items()}
    return out


def tmp_root() -> Path:
    return login.home() / "tmp"


def plugin_dir() -> Path:
    """yt-dlp 插件根目录（`--plugin-dirs` 要的是「下面再套一层目录、里面放 yt_dlp_plugins/」的根）；文件缺了 / 版本旧了就重写。"""
    root = login.home() / "ytdlp-plugins"
    target = root / "lwa-bilibili" / "yt_dlp_plugins" / "extractor" / "bilibili_lang.py"
    stamp = root / "lwa-bilibili" / "VERSION"
    try:
        if not target.is_file() or not stamp.is_file() or stamp.read_text("utf-8").strip() != PLUGIN_VERSION:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(PLUGIN_SRC, encoding="utf-8")
            stamp.write_text(PLUGIN_VERSION, encoding="utf-8")
    except OSError:
        pass
    return root


def download_url(bvid: str, page: int = 1) -> str:
    return DOWNLOAD_URL_FMT.format(bvid=bvid) + (f"?p={page}" if page and page > 1 else "")


def sweep_tmp(now: float | None = None) -> list[Path]:
    """上次崩了留下的临时下载目录（超过 6 小时）清掉；清不掉的留着。"""
    now = time.time() if now is None else now
    removed: list[Path] = []
    try:
        for p in tmp_root().iterdir():
            if p.is_dir() and p.name.startswith("dl-") and now - p.stat().st_mtime > TMP_STALE_S:
                shutil.rmtree(p, ignore_errors=True)
                removed.append(p)
    except OSError:
        pass
    return removed


def new_tmp_dir() -> Path:
    sweep_tmp()
    root = tmp_root()
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"dl-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{secrets.token_hex(3)}"
    p.mkdir()
    return p


def build_argv(url: str, out_dir: Path, *, cookies: Path | None) -> list[str]:
    argv = [*argv_base(), "--no-playlist", "--no-progress", "--no-colors", "--newline", "--ignore-config",
            "--plugin-dirs", str(plugin_dir()), "--http-chunk-size", CHUNK,
            "-f", FORMAT, "-S", SORT, "--merge-output-format", "mp4",
            "--write-subs", "--sub-langs", "all",
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "--write-info-json", "--no-clean-info-json",
            "-o", "%(id)s.%(ext)s", "-P", str(out_dir)]
    if cookies is not None:
        argv += ["--cookies", str(cookies)]
    argv.append(url)
    return argv


def classify_error(stderr: str) -> tuple[str, str]:
    """yt-dlp 的报错 → (故障码, 给人看的一句)。只认几类，其余原样（脱敏）给人。"""
    low = (stderr or "").lower()
    if "ffmpeg" in low and ("not found" in low or "not installed" in low or "ffmpeg is required" in low):
        return "NEEDS_HUMAN.MISSING_DEPENDENCY", "没有 ffmpeg，无法合并音视频"
    if "login" in low and ("required" in low or "premium" in low or "members only" in low):
        return "NEEDS_HUMAN.NOT_LOGGED_IN", "这条视频要登录（或大会员）才能看：请先扫码登录"
    if "deleted or geo-restricted" in low or "video unavailable" in low or "not found" in low and "video" in low:
        return "PERMANENT.NOTE_GONE", "视频不存在、已删除或有地区限制"
    if "unable to extract initial state" in low:
        return "TRANSIENT.SERVICE_BUSY", "B 站页面解析失败（yt-dlp 可能需要升级：python -m pip install -U yt-dlp）"
    if "412" in low or "429" in low or "too many requests" in low or "precondition failed" in low:
        return "TRANSIENT.HTTP_429", "B 站限流 / 风控（412 / 429），稍后再试"
    if "getaddrinfo" in low or "timed out" in low or "connection" in low or "network" in low:
        return "TRANSIENT.NETWORK", "网络不通或超时"
    return "TRANSIENT.DOWNLOAD_FAILED", "下载器失败"


def run(url: str, *, log=lambda _m: None, timeout_s: int | None = None, use_cookies: bool = True) -> dict[str, Any]:
    """起一次 yt-dlp 下载到全新临时目录。返回：
    {dir, exit_code, argv（不含 cookie 路径值）, stderr_tail（脱敏）, info（白名单后的 info.json）, files: {video, cover, danmaku, subtitles[]},
     cookies_used, duration_s, need_login_subtitle}
    子进程失败但视频文件已完整落地也算部分成功，由调用方按文件逐项定状态。"""
    out_dir = new_tmp_dir()
    cookies = login.cookies_path() if (use_cookies and login.has_cookies()) else None
    argv = build_argv(url, out_dir, cookies=cookies)
    shown = [a if a != str(cookies) else "<cookies>" for a in argv]
    log(f"yt-dlp {' '.join(shown[3:])}")
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout_s or TIMEOUT_S, cwd=str(out_dir))
        code, stderr, stdout = proc.returncode, proc.stderr, proc.stdout
    except subprocess.TimeoutExpired:
        code, stderr, stdout = -1, f"yt-dlp 超时（{timeout_s or TIMEOUT_S} 秒）", ""
    except OSError as exc:
        code, stderr, stdout = -2, f"起不来 yt-dlp：{errtext(exc)}", ""
    result = {"dir": out_dir, "exit_code": code, "argv": shown, "cookies_used": cookies is not None,
              "stderr_tail": sanitize(stderr), "duration_s": round(time.monotonic() - started, 1),
              "need_login_subtitle": "subtitles are only available when logged in" in (stderr or "").lower(),
              "stdout_tail": sanitize(stdout, 400)}
    result.update(collect_files(out_dir))
    return result


def collect_files(out_dir: Path) -> dict[str, Any]:
    """只认这个目录里实际存在的文件（不预设名字）：*.info.json / *.mp4|mkv|flv / *.danmaku.xml / *.<lang>.srt / 封面图。"""
    info: dict[str, Any] = {}
    files: dict[str, Any] = {"video": None, "cover": None, "danmaku": None, "subtitles": []}
    for p in sorted(out_dir.iterdir()):
        if not p.is_file():
            continue
        name = p.name
        if name.endswith(".info.json"):
            try:
                info = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
        elif p.suffix.lower() in (".mp4", ".mkv", ".flv", ".webm") and ".part" not in name:
            if files["video"] is None or p.suffix.lower() == ".mp4":
                files["video"] = p
        elif name.endswith(".danmaku.xml"):
            files["danmaku"] = p
        elif p.suffix.lower() == ".srt":
            stem = name[:-4]
            lang = stem.rsplit(".", 1)[1] if "." in stem else "und"
            files["subtitles"].append({"lang": lang, "path": p})
        elif p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and files["cover"] is None:
            files["cover"] = p
    return {"info": sanitize_info(info), "files": files}


# ---- 逐文件验真 ---------------------------------------------------------------------------------------------------

def probe_video(path: Path) -> dict[str, Any]:
    """ffprobe：容器可读、有视频流、时长 > 0 才算 ok；有没有音轨另记（确实无声不算失败）。"""
    out: dict[str, Any] = {"ok": False, "duration_sec": None, "width": None, "height": None, "vcodec": None,
                           "acodec": None, "has_audio": False, "error": None}
    try:
        if not path.is_file() or path.stat().st_size < 1024:
            out["error"] = "文件不存在或过小"
            return out
    except OSError as exc:
        out["error"] = f"读不到文件：{errtext(exc)}"
        return out
    if not shutil.which("ffprobe"):
        out["error"] = "没有 ffprobe，无法校验"
        return out
    try:
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
                               "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        out["error"] = f"ffprobe 跑不动：{errtext(exc)}"
        return out
    if proc.returncode != 0:
        out["error"] = "ffprobe 认不出这个文件：" + sanitize(proc.stderr, 200)
        return out
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        out["error"] = "ffprobe 输出不是 JSON"
        return out
    try:
        dur = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    for s in data.get("streams") or []:
        if s.get("codec_type") == "video" and out["vcodec"] is None:
            out.update(vcodec=s.get("codec_name"), width=s.get("width"), height=s.get("height"))
        elif s.get("codec_type") == "audio":
            out.update(has_audio=True, acodec=s.get("codec_name"))
    out["duration_sec"] = round(dur, 3) if dur else None
    if out["vcodec"] is None:
        out["error"] = "没有视频流"
    elif not dur:
        out["error"] = "读不出时长（可能是半截文件）"
    else:
        out["ok"] = True
    return out


def validate_srt(path: Path) -> dict[str, Any]:
    """SRT：至少一条带合法时间戳且有文字的字幕。返回 {ok, cues, chars, error}。"""
    out: dict[str, Any] = {"ok": False, "cues": 0, "chars": 0, "error": None}
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        out["error"] = f"读不到：{errtext(exc)}"
        return out
    cues = chars = 0
    for block in re.split(r"\r?\n\r?\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) >= 3 and SRT_TIME_RE.match(lines[1].strip()):
            body = " ".join(lines[2:]).strip()
            if body:
                cues += 1
                chars += len(body)
    out.update(cues=cues, chars=chars)
    if cues:
        out["ok"] = True
    else:
        out["error"] = "没有一条带时间戳和文字的字幕"
    return out


def srt_text(path: Path, *, limit: int = 200_000) -> str:
    """SRT 里的纯文字（给 derived/transcript.json / 机读版 / 检索用）：连续重复行只留一次。"""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    rows: list[str] = []
    last = None
    for block in re.split(r"\r?\n\r?\n", text.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) >= 3 and SRT_TIME_RE.match(lines[1]):
            body = " ".join(lines[2:]).strip()
            if body and body != last:
                rows.append(body)
                last = body
    return "\n".join(rows)[:limit]


def validate_danmaku(path: Path) -> dict[str, Any]:
    """弹幕 XML：能解析、`<d>` 条数。0 条也 ok（原站就没弹幕，count=0 让上层记 empty_source）。"""
    out: dict[str, Any] = {"ok": False, "count": 0, "error": None}
    try:
        if path.stat().st_size == 0:
            out["error"] = "空文件"
            return out
        root = ET.parse(str(path)).getroot()
    except (OSError, ET.ParseError) as exc:
        out["error"] = f"XML 解析失败：{errtext(exc)}"
        return out
    out["count"] = sum(1 for _ in root.iter("d"))
    out["ok"] = True
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
