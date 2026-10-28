"""B 站登录态（阶段一，1029）：扫码登录一次，之后复用。

凭证**不在 vault、不在仓库**：Netscape 格式的 cookie 文件住 `~/.link-brain/bilibili/cookies.txt`
（`storage.link_brain_home()`；`~/.link-brain/config.json` 里 `bilibili.cookies_file` 可指到别处，比如她自己从浏览器导出的那份）。
下载器（yt-dlp，见 ytdlp.py）用 `--cookies <文件>` 直接读它；本模块只做三件事：扫码写入、查登录状态、给只读接口一个带 cookie 的 httpx 客户端。

规矩：永远不把 cookie 值（SESSDATA / bili_jct / 二维码口令）打印到终端、写进日志 / vault / 测试快照。状态只说
「已登录 / 需重新登录 / 未知」+ 脱敏 mid。任务书原计划用 Bili23 CLI 存凭证；该 PyPI 包 3.0.0 的 parse / download 是占位实现、
且非官方发布，1029 实测不可用，故改由这里按 B 站官方扫码接口自存一份（和 Bili23 做的事一样，只是格式换成 yt-dlp 认的 Netscape）。
"""
from __future__ import annotations

import http.cookiejar
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from ... import storage
from ...errtext import errtext

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
NAV_API = "https://api.bilibili.com/x/web-interface/nav"
QR_GENERATE_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
LOGIN_COOKIE_KEYS = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
POLL_INTERVAL_S = 2.0
# 二维码轮询状态码（B 站）：0 成功 / 86101 等扫码 / 86090 已扫待确认 / 86038 已过期
QR_WAITING, QR_SCANNED, QR_EXPIRED = 86101, 86090, 86038


def home() -> Path:
    return storage.link_brain_home() / "bilibili"


def cookies_path() -> Path:
    """cookie 文件位置：config.json 的 bilibili.cookies_file 优先，否则 ~/.link-brain/bilibili/cookies.txt。"""
    cfg = storage.user_config().get("bilibili")
    custom = cfg.get("cookies_file") if isinstance(cfg, dict) else None
    if isinstance(custom, str) and custom.strip():
        return Path(os.path.expandvars(custom.strip())).expanduser()
    return home() / "cookies.txt"


def has_cookies() -> bool:
    p = cookies_path()
    try:
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def _load_jar() -> http.cookiejar.MozillaCookieJar | None:
    p = cookies_path()
    if not p.is_file():
        return None
    jar = http.cookiejar.MozillaCookieJar(str(p))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError):
        return None
    return jar


def http_client(*, timeout: float = 30) -> httpx.Client:
    """带登录 cookie（有就带）的只读客户端；阶段二的收藏夹枚举也用它。调用方负责 close。"""
    jar = _load_jar()
    return httpx.Client(headers=HEADERS, cookies=jar, timeout=timeout, follow_redirects=True)


def mask_mid(mid: Any) -> str:
    s = str(mid or "")
    return (s[:2] + "*" * max(0, len(s) - 4) + s[-2:]) if len(s) >= 5 else ("*" * len(s))


def status(*, client: httpx.Client | None = None) -> dict[str, Any]:
    """查登录状态：{"state": "logged_in" | "logged_out" | "unknown", "detail": 给人看的一句, "mid_masked": ...}。
    没有 cookie 文件 = logged_out（不联网）；nav 接口 isLogin 假 = logged_out（cookie 过期，需重新扫码）；网络 / 接口异常 = unknown。"""
    if not has_cookies():
        return {"state": "logged_out", "detail": "还没登录过：运行 `python -m link_brain bilibili login` 扫码", "mid_masked": ""}
    own = client is None
    client = client or http_client()
    try:
        resp = client.get(NAV_API)
        data = resp.json() if resp.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001 - 查不到就是未知，不猜
        return {"state": "unknown", "detail": f"查不到登录状态（{errtext(exc)}），稍后再试", "mid_masked": ""}
    finally:
        if own:
            client.close()
    nav = data.get("data") if isinstance(data, dict) else None
    if not isinstance(nav, dict):
        return {"state": "unknown", "detail": "登录接口返回异常，稍后再试", "mid_masked": ""}
    if not nav.get("isLogin"):
        return {"state": "logged_out", "detail": "登录已失效：请重新扫码（`python -m link_brain bilibili login`）", "mid_masked": ""}
    return {"state": "logged_in", "detail": "已登录", "mid_masked": mask_mid(nav.get("mid")),
            "vip": bool((nav.get("vipStatus") or 0))}


def _cookie_text(url: str) -> dict[str, str]:
    """登录成功时 poll 返回的 url 带跨域 cookie 参数；只取登录那几个键。"""
    q = parse_qs(urlparse(url).query)
    return {k: v[0] for k, v in q.items() if k in LOGIN_COOKIE_KEYS and v}


def _save_jar(resp_jar: http.cookiejar.CookieJar, extra: dict[str, str]) -> Path:
    """把登录响应里的 cookie（Set-Cookie 带的过期时间）+ url 参数里补的键写成 Netscape 文件。值只在内存里过一下，不打印。"""
    path = cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    jar = http.cookiejar.MozillaCookieJar(str(path))
    got: set[str] = set()
    for c in resp_jar:
        if c.name in LOGIN_COOKIE_KEYS or c.domain.endswith("bilibili.com"):
            jar.set_cookie(c)
            got.add(c.name)
    far = int(time.time()) + 180 * 24 * 3600   # SESSDATA 实际约半年；没给过期时间的按 180 天记
    for name, value in extra.items():
        if name in got:
            continue
        jar.set_cookie(http.cookiejar.Cookie(0, name, value, None, False, ".bilibili.com", True, True, "/", True,
                                             True, far, False, None, None, {}))
    jar.save(ignore_discard=True, ignore_expires=True)
    return path


def _print_qr(url: str, out) -> None:
    try:
        import qrcode  # bili23 带进来的依赖；没有就只给链接

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(out=out, invert=True)
    except Exception:  # noqa: BLE001
        print("（本机没有 qrcode 包，无法在终端画二维码：pip install qrcode 后重试，或把下面链接转成二维码扫）", file=out)
    print("二维码链接（只用于本次扫码，几分钟后失效）：", url, file=out)


def qr_login(*, timeout_s: int = 180, out=None) -> dict[str, Any]:
    """扫码登录：出二维码 → 轮询 → 成功就写 cookie 文件并复查 nav。返回 status() 的形状（state / detail）。
    人话进度打到 out（默认 stderr），不打 cookie 值。"""
    out = out or sys.stderr
    with httpx.Client(headers=HEADERS, timeout=30) as client:
        try:
            r = client.get(QR_GENERATE_API, params={"source": "main-fe-header", "go_url": "https://www.bilibili.com/"})
            payload = r.json()
        except Exception as exc:  # noqa: BLE001
            return {"state": "unknown", "detail": f"取二维码失败（{errtext(exc)}）", "mid_masked": ""}
        if payload.get("code") != 0:
            return {"state": "unknown", "detail": f"取二维码失败：{payload.get('message') or payload.get('code')}", "mid_masked": ""}
        data = payload.get("data") or {}
        url, key = data.get("url") or "", data.get("qrcode_key") or ""
        if not url or not key:
            return {"state": "unknown", "detail": "二维码接口没有返回链接", "mid_masked": ""}
        _print_qr(url, out)
        print(f"请用手机哔哩哔哩 App 扫码并确认（最多等 {timeout_s} 秒）…", file=out)
        deadline = time.monotonic() + timeout_s
        told_scanned = False
        while time.monotonic() < deadline:
            try:
                r = client.get(QR_POLL_API, params={"qrcode_key": key})
                st = (r.json().get("data") or {})
            except Exception as exc:  # noqa: BLE001
                print(f"轮询失败（{errtext(exc)}），继续等…", file=out)
                time.sleep(POLL_INTERVAL_S)
                continue
            code = st.get("code")
            if code == 0:
                path = _save_jar(r.cookies.jar, _cookie_text(st.get("url") or ""))
                print(f"已保存登录态到 {path.name}（目录 {path.parent}）", file=out)
                return status()
            if code == QR_EXPIRED:
                return {"state": "logged_out", "detail": "二维码已过期，没登录：再运行一次重新出码", "mid_masked": ""}
            if code == QR_SCANNED and not told_scanned:
                print("已扫码，请在手机上点确认…", file=out)
                told_scanned = True
            time.sleep(POLL_INTERVAL_S)
    return {"state": "logged_out", "detail": f"等了 {timeout_s} 秒没扫码，没登录", "mid_masked": ""}


def logout() -> bool:
    """只删本地 cookie 文件（不调 B 站退出接口）。"""
    p = cookies_path()
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
