"""B 站电视端取流（1031 她：最高画质 + 优先无水印片源）。

为什么走电视端：B 站网页端（yt-dlp 用的那条）给的部分稿件是压了 UP 主水印的二压片源；电视端（云视听小电视）的播放接口对很多稿件
给的是没有水印的片源（粉丝多的 UP 基本都是），而且登录电视端后清晰度上限和网页大会员一样（4K / 8K / HDR）。
拿得到就用电视端的视频流；拿不到（没登录电视端、接口报错、没有合适的流、下载 / 合并失败）一律退回 yt-dlp 的网页流，不让一条视频因此失败。
字幕 / 弹幕 / 封面 / 原始信息照旧由 yt-dlp 取（`--skip-download`），这里只换视频本体。

参考（只读源码、没运行，思路自己重写，不含原项目代码）：
- nilaoda/BBDown（MIT）`BBDown.Core/Parser.cs`：电视端播放接口 `api.snm0516.aisee.tv/x/tv/playurl` 的参数
  （appkey / mobi_app=android_tv_yst / platform=android / fnval=4048 / fourk=1 / object_id=aid / cid / qn / access_key）
  和「电视端不取杜比 / Hi-Res 音轨」；`BBDown.Core/Config.cs` 的 TVHOST；`BBDown/BBDownUtil.cs` 的签名（参数串 + appsec 取 MD5）
  和电视端登录参数；`BBDown/BBDownLoginUtil.cs` 的电视端扫码登录（auth_code → 轮询 86039 等扫 / 86038 过期 → access_token）。
- LOVAHE/BBDownT（接手 BBDown）README：「使用 TV 接口下载（粉丝量大的 UP 主基本上是无水印片源）」、
  「TV 登录产生的 access_token 也可以给 APP 接口使用」、清晰度 / 编码优先级（-q / -e）的思路。

凭证规矩同 login.py：电视端 token 存 `~/.link-brain/bilibili/tv-token.json`（不在 vault、不进仓库），永不打印 token 值。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from ... import storage
from ...errtext import errtext
from . import login

# 电视端（云视听小电视）公开的 appkey / appsec（BBDown 等开源下载器通用的那一对）
APPKEY = "4409e2ce8ffd12b8"
APPSEC = "59b43e04ad6965f34319062b478f83dd"
TV_PLAYURL = "https://api.snm0516.aisee.tv/x/tv/playurl"
TV_QR_AUTH = "https://passport.snm0516.aisee.tv/x/passport-tv-login/qrcode/auth_code"
TV_QR_POLL = "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll"
VIEW_API = "https://api.bilibili.com/x/web-interface/view"
TV_UA = "Mozilla/5.0 BiliDroid/1.12.5 (bbcallen@gmail.com)"
QR_WAITING, QR_SCANNED, QR_EXPIRED = 86039, 86090, 86038
POLL_INTERVAL_S = 2.0
CHUNK_BYTES = 10 * 1024 * 1024    # 同 ytdlp.CHUNK：CDN 对不带 Range 的整文件 GET 回 567，分段要
MAX_QN = 127                       # 要最高的（8K）；接口按账号能拿到的往下给

# 清晰度 id → 短边高度（电视端的流不带宽高，按 id 推）。126 = 杜比视界：Chromium 放不了增强层，排除（同 ytdlp max 档）
QN_HEIGHT = {127: 4320, 126: 2160, 125: 2160, 120: 2160, 116: 1080, 112: 1080, 80: 1080, 74: 720, 64: 720,
             32: 480, 16: 360, 6: 240}
QN_LABEL = {127: "8K", 126: "杜比视界", 125: "HDR", 120: "4K", 116: "1080P60", 112: "1080P+", 80: "1080P",
            74: "720P60", 64: "720P", 32: "480P", 16: "360P", 6: "240P"}
EXCLUDE_QN = {126}
CODEC_NAME = {13: "av1", 12: "hevc", 7: "avc"}
# 同清晰度下的编码偏好：max 档 AV1 > HEVC > AVC（同 ytdlp max）；1080 / 720 档保持原来的 AVC 优先（老机器也能硬解）
CODEC_ORDER = {"max": (13, 12, 7), "1080": (7, 12, 13), "720": (7, 12, 13)}
HEIGHT_CAP = {"max": 10 ** 6, "1080": 1080, "720": 720}


class TvError(Exception):
    def __init__(self, message: str, code: str = "TRANSIENT.DOWNLOAD_FAILED"):
        super().__init__(message)
        self.code = code


# ---- 签名 / token -------------------------------------------------------------------------------------------------

def signed(params: dict[str, Any]) -> dict[str, str]:
    """按键名排序拼参数串，后面接 appsec 取 MD5 作 sign（B 站 app 签名的通用做法）。返回带 sign 的新 dict（顺序即发出的顺序）。"""
    items = sorted((str(k), str(v)) for k, v in params.items() if k != "sign")
    out = dict(items)
    out["sign"] = hashlib.md5((urlencode(items) + APPSEC).encode("utf-8")).hexdigest()
    return out


def token_path() -> Path:
    return login.home() / "tv-token.json"


def load_token() -> dict[str, Any] | None:
    try:
        data = json.loads(token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("access_token") else None


def save_token(data: dict[str, Any]) -> Path:
    now = int(time.time())
    try:
        expires_in = int(data.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    rec = {"access_token": data.get("access_token"), "refresh_token": data.get("refresh_token"),
           "mid": data.get("mid"), "saved_at": now, "expires_at": now + expires_in if expires_in else None}
    p = token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    storage.atomic_write_text(p, json.dumps(rec, ensure_ascii=False))
    return p


def save_web_cookies(data: dict[str, Any]) -> bool:
    """1031 她「给一个（扫码）就行」：电视端扫码成功时响应里带 cookie_info.cookies（网页端登录 cookie），
    照网页端扫码的格式写进 cookies.txt，一次扫码两边都登上。没带 / 写不上返回 False（网页端照旧单独扫）。值不打印。"""
    cookies = ((data.get("cookie_info") or {}).get("cookies")) or []
    extra = {c.get("name"): str(c.get("value")) for c in cookies
             if isinstance(c, dict) and c.get("name") in login.LOGIN_COOKIE_KEYS and c.get("value")}
    if "SESSDATA" not in extra:
        return False
    try:
        import http.cookiejar
        login._save_jar(http.cookiejar.CookieJar(), extra)
        return True
    except OSError:
        return False


def clear_token() -> bool:
    try:
        token_path().unlink()
        return True
    except FileNotFoundError:
        return False


def mark_invalid(reason: str) -> None:
    """接口说 token 不认了：记一笔（不删文件，状态里说「要重新扫电视端」）。"""
    tok = load_token()
    if not tok:
        return
    tok["invalid"] = reason[:200]
    try:
        storage.atomic_write_text(token_path(), json.dumps(tok, ensure_ascii=False))
    except OSError:
        pass


def token_status(now: float | None = None) -> dict[str, Any]:
    """不联网：{state: logged_in | expired | logged_out, detail, expires_at}。"""
    tok = load_token()
    if not tok:
        return {"state": "logged_out", "detail": "电视端没登录：网页流也能下，只是可能带水印", "expires_at": None}
    now = time.time() if now is None else now
    exp = tok.get("expires_at")
    if tok.get("invalid") or (exp and now >= float(exp)):
        return {"state": "expired", "detail": "电视端登录已失效：重新扫一次电视端二维码（不扫也能下，退回网页流）",
                "expires_at": exp}
    left = f"，约 {int((float(exp) - now) // 86400)} 天后要重扫" if exp else ""
    return {"state": "logged_in", "detail": f"电视端已登录（优先拿无水印片源{left}）", "expires_at": exp}


def usable_token() -> str | None:
    st = token_status()
    tok = load_token()
    return tok["access_token"] if st["state"] == "logged_in" and tok else None


# ---- 电视端扫码登录 -------------------------------------------------------------------------------------------------

def _login_params() -> dict[str, Any]:
    """电视端登录要的设备参数（随机设备号；字段名参考 BBDown 的电视端登录参数，值自己生成）。"""
    dev = secrets.token_hex(16)
    return {"appkey": APPKEY, "local_id": dev, "mobi_app": "android_tv_yst", "platform": "android",
            "build": "102801", "channel": "master", "networkstate": "wifi", "ts": int(time.time())}


def _auth_code(client: httpx.Client) -> tuple[str, str] | dict[str, Any]:
    try:
        r = client.post(TV_QR_AUTH, data=signed(_login_params()))
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"state": "unknown", "detail": f"取电视端二维码失败（{errtext(exc)}）"}
    data = payload.get("data") or {}
    if payload.get("code") != 0 or not data.get("url") or not data.get("auth_code"):
        return {"state": "unknown", "detail": f"取电视端二维码失败：{payload.get('message') or payload.get('code')}"}
    return data["url"], data["auth_code"]


def qr_login(*, timeout_s: int = 180, out=None, qr_png: Path | None = None, client: httpx.Client | None = None,
             sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """电视端扫码：手机 B 站 App 扫码确认 → 存 access_token。返回 token_status() 的形状。"""
    out = out or sys.stderr
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": TV_UA}, timeout=30)
    try:
        got = _auth_code(client)
        if isinstance(got, dict):
            return got
        url, code = got
        login._print_qr(url, out, qr_png)
        print(f"请用手机哔哩哔哩 App 扫码并确认（电视端登录，最多等 {timeout_s} 秒；过期会自动换新码）…", file=out)
        deadline = time.monotonic() + timeout_s
        told = False
        while time.monotonic() < deadline:
            params = _login_params()
            params["auth_code"] = code
            try:
                payload = client.post(TV_QR_POLL, data=signed(params)).json()
            except Exception as exc:  # noqa: BLE001
                print(f"轮询失败（{errtext(exc)}），继续等…", file=out)
                sleep(POLL_INTERVAL_S)
                continue
            c = payload.get("code")
            if c == 0 and (payload.get("data") or {}).get("access_token"):
                p = save_token(payload["data"])
                print(f"已保存电视端登录态到 {p.name}（目录 {p.parent}）", file=out)
                web = save_web_cookies(payload["data"])
                if web:
                    print("网页端登录态也一并存好了（同一次扫码）", file=out)
                return {**token_status(), "web_saved": web}
            if c == QR_EXPIRED:
                got = _auth_code(client)
                if isinstance(got, dict):
                    return {"state": "logged_out", "detail": f"二维码已过期，换新码失败：{got['detail']}"}
                url, code = got
                print(f"二维码已过期，已换新码（{datetime.now().strftime('%H:%M:%S')}）：", file=out)
                login._print_qr(url, out, qr_png)
                told = False
                continue
            if c == QR_SCANNED and not told:
                print("已扫码，请在手机上点确认…", file=out)
                told = True
            sleep(POLL_INTERVAL_S)
        return {"state": "logged_out", "detail": f"等了 {timeout_s} 秒没扫码，电视端没登录"}
    except KeyboardInterrupt:
        return {"state": "logged_out", "detail": "扫码被取消，电视端没登录"}
    finally:
        if own:
            client.close()


# ---- 取流 ------------------------------------------------------------------------------------------------------------

def ids_for(bvid: str, page: int, info: dict[str, Any] | None, *, client: httpx.Client) -> tuple[int, int]:
    """(aid, cid)：yt-dlp 的 info 里有就用（ytdlp.collect_files 从 _old_archive_ids / 弹幕地址补出来的，下载地址带了 ?p= 就是那一 P 的），
    没有才查一次网页端 view 接口（不要签名；10-29 记过本机出口 IP 查它会 412，所以只当兜底）。"""
    info = info or {}
    try:
        if info.get("aid") and info.get("cid"):
            return int(info["aid"]), int(info["cid"])
    except (TypeError, ValueError):
        pass
    try:
        payload = client.get(VIEW_API, params={"bvid": bvid}).json()
    except Exception as exc:  # noqa: BLE001
        raise TvError(f"查不到稿件编号（{errtext(exc)}）", "TRANSIENT.NETWORK") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if payload.get("code") != 0 or not isinstance(data, dict):
        raise TvError(f"查不到稿件编号：{payload.get('message') or payload.get('code')}")
    pages = data.get("pages") or []
    idx = max(0, int(page or 1) - 1)
    cid = (pages[idx].get("cid") if idx < len(pages) and isinstance(pages[idx], dict) else None) or data.get("cid")
    if not data.get("aid") or not cid:
        raise TvError("稿件信息里没有 aid / cid")
    return int(data["aid"]), int(cid)


def playurl(aid: int, cid: int, *, token: str | None, client: httpx.Client, qn: int = MAX_QN) -> dict[str, Any]:
    """电视端播放接口 → 带 dash 的那一层（有的回在 data 里，有的直接在根上）。"""
    params: dict[str, Any] = {"appkey": APPKEY, "build": "106500", "cid": cid, "device": "android", "fnval": 4048, "fnver": 0,
                              "fourk": 1, "mid": 0, "mobi_app": "android_tv_yst", "object_id": aid, "platform": "android",
                              "playurl_type": 1, "qn": qn, "ts": int(time.time())}
    if token:
        params["access_key"] = token
    try:
        r = client.get(TV_PLAYURL, params=signed(params))
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        raise TvError(f"电视端播放接口不通（{errtext(exc)}）", "TRANSIENT.NETWORK") from exc
    code = payload.get("code") if isinstance(payload, dict) else None
    if code in (-101, -400) and token:
        mark_invalid(f"播放接口回 {code}")
        raise TvError("电视端登录已失效（接口回 -101）", "NEEDS_HUMAN.NOT_LOGGED_IN")
    if code in (-412, -352, -509, -799):
        raise TvError(f"电视端接口限流 / 风控（{code}）", "TRANSIENT.HTTP_429")
    if code != 0:
        raise TvError(f"电视端播放接口回 {code} {payload.get('message') if isinstance(payload, dict) else ''}")
    body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(body.get("dash"), dict):
        raise TvError("电视端这条没有分段流（dash）")
    return body


def _urls(s: dict[str, Any]) -> list[str]:
    first = s.get("base_url") or s.get("baseUrl") or s.get("url")
    backups = s.get("backup_url") or s.get("backupUrl") or []
    return [u for u in [first, *(backups if isinstance(backups, list) else [])] if isinstance(u, str) and u.startswith("http")]


def pick(body: dict[str, Any], quality: str = "max") -> dict[str, Any] | None:
    """按画质档挑一路视频 + 最好的音轨：清晰度 id 高的先（杜比视界除外、不超过这一档的短边），同清晰度按编码偏好。
    没有合适的 → None（调用方退回网页流）。"""
    quality = quality if quality in HEIGHT_CAP else "max"
    dash = body.get("dash") or {}
    order = CODEC_ORDER[quality]
    cands = []
    for v in dash.get("video") or []:
        try:
            qn, codec = int(v.get("id")), int(v.get("codecid") or 0)
        except (TypeError, ValueError):
            continue
        if qn in EXCLUDE_QN or QN_HEIGHT.get(qn, 0) > HEIGHT_CAP[quality] or codec not in order or not _urls(v):
            continue
        cands.append((QN_HEIGHT.get(qn, 0), qn, len(order) - order.index(codec), int(v.get("bandwidth") or 0), v))
    if not cands:
        return None
    cands.sort(key=lambda c: c[:4], reverse=True)
    video = cands[0][4]
    audios = [a for a in dash.get("audio") or [] if _urls(a)]   # 杜比 / Hi-Res 在 dash.dolby / dash.flac，电视端不取
    audio = max(audios, key=lambda a: int(a.get("bandwidth") or 0)) if audios else None
    qn = int(video["id"])
    return {"video": video, "audio": audio, "qn": qn, "label": QN_LABEL.get(qn, str(qn)),
            "codec": CODEC_NAME.get(int(video.get("codecid") or 0), "?"), "accept": body.get("accept_quality")}


def fetch_stream(urls: list[str], dest: Path, *, client: httpx.Client, deadline: float) -> int:
    """分段 Range 下到 dest（先写 .part，完整了才改名）；一个地址失败换备用地址。返回字节数。"""
    last: Exception | None = None
    part = dest.with_suffix(dest.suffix + ".part")
    for url in urls:
        try:
            got = 0
            total: int | None = None
            with part.open("wb") as fh:
                while total is None or got < total:
                    if time.monotonic() > deadline:
                        raise TvError("电视端下载超时", "TRANSIENT.STEP_TIMEOUT")
                    r = client.get(url, headers={"Range": f"bytes={got}-{got + CHUNK_BYTES - 1}"})
                    if r.status_code not in (200, 206):
                        raise TvError(f"取流 HTTP {r.status_code}")
                    data = r.content
                    if not data:
                        break
                    fh.write(data)
                    got += len(data)
                    cr = r.headers.get("content-range") or ""
                    if "/" in cr and cr.rsplit("/", 1)[1].strip().isdigit():
                        total = int(cr.rsplit("/", 1)[1])
                    elif r.status_code == 200:
                        total = got   # 不认 Range、整个给了
            if got == 0 or (total is not None and got < total):
                raise TvError("流没下完整")
            part.replace(dest)
            return got
        except (TvError, httpx.HTTPError, OSError) as exc:
            last = exc
            part.unlink(missing_ok=True)
            continue
    if isinstance(last, TvError):
        raise last
    raise TvError(f"取流失败（{errtext(last) if last else '没有可用地址'}）", "TRANSIENT.NETWORK")


def merge(video: Path, audio: Path | None, out: Path, *, timeout_s: int = 600) -> None:
    """ffmpeg 只换容器不重编码（-c copy）合成 mp4；faststart 让 Obsidian 里能边下边放。"""
    argv = ["ffmpeg", "-y", "-v", "error", "-i", str(video)]
    if audio is not None:
        argv += ["-i", str(audio)]
    argv += ["-c", "copy", "-movflags", "+faststart", str(out)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    except (OSError, subprocess.SubprocessError) as exc:
        raise TvError(f"ffmpeg 合并失败：{errtext(exc)}", "NEEDS_HUMAN.MISSING_DEPENDENCY" if isinstance(exc, OSError) else
                      "TRANSIENT.DOWNLOAD_FAILED") from exc
    if proc.returncode != 0 or not out.is_file():
        out.unlink(missing_ok=True)
        raise TvError("ffmpeg 合并失败：" + (proc.stderr or "").strip()[-200:])


def download(bvid: str, page: int, out_dir: Path, *, quality: str, info: dict[str, Any] | None, token: str,
             timeout_s: int, log: Callable[[str], None] = lambda _m: None, client: httpx.Client | None = None,
             web_client: httpx.Client | None = None) -> dict[str, Any]:
    """电视端整条：查 aid/cid → 播放接口 → 挑流 → 下视频 / 音频 → 合成 `<bvid>.mp4` 放进 out_dir。
    成功 {ok: True, file, qn, label, codec, bytes}；失败抛 TvError（调用方退回网页流，临时的 .m4s 这里清掉）。"""
    deadline = time.monotonic() + timeout_s
    own = client is None
    own_web = web_client is None
    client = client or httpx.Client(headers={"User-Agent": TV_UA, "Referer": "https://www.bilibili.com/"},
                                    timeout=60, follow_redirects=True)
    web_client = web_client or login.http_client()
    v_tmp, a_tmp = out_dir / "tv-video.m4s", out_dir / "tv-audio.m4s"
    try:
        aid, cid = ids_for(bvid, page, info, client=web_client)
        body = playurl(aid, cid, token=token, client=client)
        chosen = pick(body, quality)
        if chosen is None:
            raise TvError("电视端没有合适的视频流（只有杜比视界 / 超出画质档）", "TRANSIENT.DOWNLOAD_FAILED")
        log(f"电视端片源：{chosen['label']} {chosen['codec']}")
        n = fetch_stream(_urls(chosen["video"]), v_tmp, client=client, deadline=deadline)
        if chosen["audio"] is not None:
            n += fetch_stream(_urls(chosen["audio"]), a_tmp, client=client, deadline=deadline)
        target = out_dir / f"{bvid}.mp4"
        merge(v_tmp, a_tmp if chosen["audio"] is not None else None, target)
        return {"ok": True, "file": target, "qn": chosen["qn"], "label": chosen["label"], "codec": chosen["codec"], "bytes": n}
    finally:
        for p in (v_tmp, a_tmp):
            p.unlink(missing_ok=True)
        if own:
            client.close()
        if own_web:
            web_client.close()
