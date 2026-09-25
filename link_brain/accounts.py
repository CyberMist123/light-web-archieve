"""小红书账号：一个号、一个读取服务、一个持久浏览器目录。

读取服务（link-brain-reader，xiaohongshu-mcp 的扩展版）独占一个 Chromium profile，
评论 / 私密收藏 / 附件都经它的 HTTP 接口、在同一进程里串行跑——同一个号不会再有
第二个网页会话去顶掉它（2026-09-25 实测：一个号三项全通）。

扫码的铁律：出码之后只轮询 `/login/session`（纯内存状态，不开浏览器）。
旧流程轮询 `/login/status`，而它每查一次都会把正在扫的二维码页导航走。

所有失败都落成 `ReaderError(code)`，`SOLUTIONS` 给出人话原因 + 下一步 + 界面按钮，
调用方据此停车，而不是反复重试（重试会撞风控验证码，0925 真撞过）。
"""
from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import storage

DEFAULT_ENDPOINT = 'http://127.0.0.1:18061/mcp'
READER_NAMES = ('link-brain-reader.exe', 'link-brain-reader')

# code -> (状态, 一句话原因, 下一步, 界面按钮 action)
SOLUTIONS = {
    'NOT_LOGGED_IN': ('expired', '登录已失效', '点击「扫码登录」，用收藏所在的小红书账号扫码。', 'login'),
    'CAPTCHA_REQUIRED': ('captcha', '小红书要求安全验证', '点击「打开验证」，在弹出的窗口里手动拖动滑块，完成后关掉窗口；也可以过几小时再试。不要反复重试。', 'verify'),
    'RATE_LIMITED': ('busy', '刚刚同步过', '为避免触发风控，收藏每 10 分钟最多读一次，请稍后再试。', 'wait'),
    'LOGIN_IN_PROGRESS': ('busy', '正在等待扫码', '先完成或关闭正在进行的扫码，再重试。', 'wait'),
    'VERIFY_WINDOW_OPEN': ('busy', '验证窗口还开着', '完成验证后关掉那个小红书窗口，再重试。', 'wait'),
    'DISCONNECTED': ('disconnected', '读取服务没有运行', '点击「重试」会自动启动；仍失败请查看详情里的日志路径。', 'retry'),
    'NOT_INSTALLED': ('unconfigured', '未安装读取组件', '按 README「小红书读取组件」放置 link-brain-reader，然后刷新状态。', 'none'),
    'NO_DOWNLOAD_BUTTON': ('error', '附件页没有下载按钮', '文件可能已被作者删除或关闭下载，可在网页手动下载后用「挂载本地文件」。', 'none'),
    'DOWNLOAD_TIMEOUT': ('error', '附件下载超时', '稍后重试；多次失败请在网页手动下载后挂载。', 'retry'),
    'TIMEOUT': ('unknown', '读取服务响应超时', '机器负载高时会发生：稍后点击「重试」。', 'retry'),
}


class ReaderError(RuntimeError):
    def __init__(self, code: str, message: str = '', detail: str = ''):
        self.code, self.detail = code, detail
        super().__init__(message or SOLUTIONS.get(code, ('', code))[1])

    @property
    def needs_human(self) -> bool:
        return self.code in ('NOT_LOGGED_IN', 'CAPTCHA_REQUIRED', 'NOT_INSTALLED')


def home() -> Path:
    return Path(os.environ.get('LINK_BRAIN_HOME', str(Path.home() / '.link-brain')))


def config() -> dict:
    p = home() / 'accounts.json'
    if not p.exists():
        return {}
    data = json.loads(p.read_text('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('账号配置格式不正确：' + str(p))
    return data


def save(values: dict) -> None:
    data = config()
    data.update(values)
    home().mkdir(parents=True, exist_ok=True)
    (home() / 'accounts.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')


def endpoint() -> str:
    return os.environ.get('LINK_BRAIN_XHS_ENDPOINT') or config().get('endpoint') or DEFAULT_ENDPOINT


def base_url() -> str:
    return endpoint().removesuffix('/mcp')


def executable(env: str, names: tuple[str, ...]) -> str | None:
    explicit = os.environ.get(env)
    if explicit:
        return explicit if Path(explicit).is_file() else shutil.which(explicit)
    for name in names:
        for root in (home() / 'bin', storage.repo_root() / 'tools', Path.home() / '.xiaohongshu-mcp'):
            if (root / name).is_file():
                return str(root / name)
        found = shutil.which(name)
        if found:
            return found
    return None


def reader_exe() -> str | None:
    return executable('LINK_BRAIN_XHS_EXE', READER_NAMES)


def profile_dir() -> Path:
    """读取服务独占的浏览器目录；登录态住在这里（不导出 cookie）。"""
    explicit = os.environ.get('XHS_PROFILE_DIR') or config().get('profile')
    if explicit:
        return Path(explicit)
    legacy = Path.home() / '.xiaohongshu-mcp' / 'data' / 'xhs' / 'momo-profile'
    return legacy if legacy.is_dir() else home() / 'xhs-profile'


def reader_env() -> dict:
    # 不钉域名：登录落在 xiaohongshu.com 还是 rednote.com 因号而异（0926 实测），
    # 读取服务在登录成功时探明并记在 profile 的 site-host 里。要强制时才设 XHS_HOST。
    return {**os.environ, 'XHS_PROFILE_DIR': str(profile_dir())}


def api(method: str, route: str, *, timeout: float = 45, body: dict | None = None) -> dict:
    try:
        response = httpx.request(method, base_url() + route, json=body, timeout=timeout)
    except httpx.ConnectError as exc:
        raise ReaderError('DISCONNECTED', detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise ReaderError('TIMEOUT', detail=str(exc)) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400 or payload.get('success') is False:
        code = payload.get('code') or f'HTTP_{response.status_code}'
        detail = payload.get('details')
        raise ReaderError(code, payload.get('error') or payload.get('message') or '',
                          json.dumps(detail, ensure_ascii=False) if isinstance(detail, (dict, list)) else str(detail or ''))
    return payload.get('data', payload)


def ensure_reader(*, wait: float = 40):
    """服务没起就在本机拉起（脱离父进程，插件/同步退出后仍在）；远程地址不代管。"""
    try:
        return api('GET', '/api/v1/login/session', timeout=5)
    except ReaderError as exc:
        if exc.code != 'DISCONNECTED':
            raise
    target = urlsplit(endpoint())
    if target.hostname not in ('localhost', '127.0.0.1'):
        raise ReaderError('DISCONNECTED', '远程读取服务未连接，请由服务管理员启动。')
    exe = reader_exe()
    if not exe:
        raise ReaderError('NOT_INSTALLED')
    home().mkdir(parents=True, exist_ok=True)
    log = home() / 'reader.log'
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with log.open('ab') as out:
        # 只监听本机：这个服务握着小红书登录，不能对局域网开放
        subprocess.Popen([exe, '-port', f'127.0.0.1:{target.port or 18061}'], cwd=home(), env=reader_env(),
                         stdout=out, stderr=out, stdin=subprocess.DEVNULL, creationflags=flags,
                         close_fds=True)
    deadline = time.monotonic() + wait  # 首次启动可能要下载内置浏览器
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            return api('GET', '/api/v1/login/session', timeout=3)
        except ReaderError as exc:
            if exc.code != 'DISCONNECTED':
                raise
    raise ReaderError('DISCONNECTED', '读取服务启动未完成', '日志：' + str(log))


def row(key: str, label: str, state: str, message: str, next_step: str = '', detail: str = '',
        optional=False, action: str = '', account: str = '') -> dict:
    return dict(id=key, label=label, state=state, message=message, next_step=next_step, detail=detail,
                optional=optional, action=action, account=account)


def error_row(exc: Exception, key='xhs', label='小红书账号') -> dict:
    if isinstance(exc, ReaderError) and exc.code in SOLUTIONS:
        state, message, step, action = SOLUTIONS[exc.code]
        return row(key, label, state, message, step, exc.detail or '', action=action)
    return row(key, label, 'unknown', '暂时无法验证', '稍后点击「重试」；持续出现请展开详情。',
               str(exc), action='retry')


def xhs_status(*, deep=True) -> dict:
    """一个账号一行。deep=False 只看服务内存状态（不开浏览器，毫秒级）。"""
    try:
        session = ensure_reader()
        if session.get('state') == 'waiting':
            return error_row(ReaderError('LOGIN_IN_PROGRESS'))
        if session.get('verifying'):
            return error_row(ReaderError('VERIFY_WINDOW_OPEN'))
        name = config().get('nickname', '')
        if not deep and session.get('logged_in') is not None:
            ok = session['logged_in']
        else:
            data = api('GET', '/api/v1/login/status', timeout=90)
            if data.get('login_pending'):
                return error_row(ReaderError('LOGIN_IN_PROGRESS'))
            ok = data.get('is_logged_in') is True
            if ok and data.get('username'):
                name = data['username']
                save({'nickname': name, 'user_id': data.get('user_id', '')})
        if ok:
            return row('xhs', '小红书账号', 'ready', '已登录' + (f'：{name}' if name else ''), account=name)
        if config().get('nickname'):
            return error_row(ReaderError('NOT_LOGGED_IN'))
        return row('xhs', '小红书账号', 'not_logged_in', '未登录', '点击「扫码登录」，用收藏所在的账号扫码。',
                   action='login')
    except Exception as exc:  # noqa: BLE001 - 状态检查永不抛给界面
        return error_row(exc)


def _login_page(message: str, image: str = '', *, done=False, ok=False) -> str:
    color = '#1f9d55' if ok else ('#c0392b' if done else '#ff2442')
    img = f'<img src="{html.escape(image, quote=True)}" alt="二维码">' if image and not done else ''
    refresh = '' if done else '<meta http-equiv="refresh" content="2">'
    return f'''<!doctype html><meta charset="utf-8">{refresh}<title>小红书登录</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f6f7;
font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#222}}
.card{{background:#fff;border-radius:18px;padding:36px 40px;box-shadow:0 8px 30px rgba(0,0,0,.08);text-align:center;width:340px}}
.logo{{display:inline-block;background:#ff2442;color:#fff;font-weight:700;border-radius:10px;padding:4px 12px;letter-spacing:1px}}
img{{width:240px;height:240px;margin:22px 0 8px;image-rendering:pixelated}}
.msg{{color:{color};font-weight:600;margin-top:14px}} .tip{{color:#888;font-size:13px}}</style>
<div class="card"><span class="logo">小红书</span>{img}<div class="msg">{html.escape(message)}</div>
<div class="tip">{'打开小红书 App → 左上角 ≡ → 扫一扫。扫码后在手机上确认登录。' if not done else '可以关闭此页面。'}</div></div>'''


def _finish_login(s: dict) -> dict:
    name = s.get('nickname') or ''
    previous = config().get('user_id')
    save({'nickname': name, 'user_id': s.get('user_id', '')})
    switched = previous and s.get('user_id') and previous != s.get('user_id')
    return row('xhs', '小红书账号', 'ready', '已登录' + (f'：{name}' if name else ''),
               '已切换账号：收藏同步将读取这个号的收藏。' if switched else '', account=name)


def login(*, timeout=330) -> dict:
    """打开小红书官方登录窗口，人在官方页面扫码；这里只轮询服务内存态，窗口由服务关闭并落盘。"""
    ensure_reader()
    api('POST', '/api/v1/login/window', timeout=20)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.5)
        s = api('GET', '/api/v1/login/session', timeout=10)
        state = s.get('state')
        if state == 'success':
            return _finish_login(s)
        if state == 'cancelled':
            return row('xhs', '小红书账号', 'not_logged_in', '已取消登录', '需要时再点「扫码登录」。', action='login')
        if state == 'failed':
            return row('xhs', '小红书账号', 'error', '登录没有完成', '点「扫码登录」再试一次。', action='login')
        if state == 'timeout':
            break
    return row('xhs', '小红书账号', 'not_logged_in', '登录窗口已超时', '点「扫码登录」重新打开。', action='login')


def logout() -> dict:
    ensure_reader()
    api('POST', '/api/v1/login/logout', timeout=90)
    data = config()
    for key in ('nickname', 'user_id'):
        data.pop(key, None)
    home().mkdir(parents=True, exist_ok=True)
    (home() / 'accounts.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
    return row('xhs', '小红书账号', 'not_logged_in', '已退出登录', '点「扫码登录」登录新的账号。', action='login')


def login_qr(*, timeout=270, open_browser=True) -> dict:
    """远程扫码用（如把二维码发到手机）：出码成网页 → 只轮询内存状态 → 成功时服务已把登录态落盘。"""
    ensure_reader()
    qr = api('GET', '/api/v1/login/qrcode', timeout=90)
    if qr.get('is_logged_in'):
        return xhs_status()
    image = qr.get('img', '')
    if not image.startswith('data:image/'):
        raise ReaderError('QR_FAILED', '读取服务没有返回二维码，请重试。')
    home().mkdir(parents=True, exist_ok=True)
    page = home() / 'login.html'
    page.write_text(_login_page('等待扫码…', image), 'utf-8')
    if open_browser and not webbrowser.open(page.as_uri()):
        raise ReaderError('QR_FAILED', '无法打开扫码页面，请手动打开 ' + str(page))
    deadline = time.monotonic() + timeout
    result = None
    try:
        while time.monotonic() < deadline:
            time.sleep(2)
            s = api('GET', '/api/v1/login/session', timeout=10)
            if s.get('state') == 'success':
                result = _finish_login(s)
                page.write_text(_login_page(result['message'], done=True, ok=True), 'utf-8')
                return result
            if s.get('state') == 'timeout':
                break
        result = row('xhs', '小红书账号', 'not_logged_in', '二维码已过期',
                     '点击「扫码登录」获取新的二维码。', action='login')
        page.write_text(_login_page('二维码已过期，请回到 Obsidian 重新点「扫码登录」', done=True), 'utf-8')
        return result
    except Exception:
        page.write_text(_login_page('登录中断，请回到 Obsidian 查看提示', done=True), 'utf-8')
        raise


def open_verify() -> dict:
    ensure_reader()
    api('POST', '/api/v1/verify/window', timeout=20)
    return row('xhs', '小红书账号', 'busy', '验证窗口已打开',
               '在弹出的小红书窗口里手动完成拼图验证，然后关掉窗口，再点「刷新」。', action='wait')


def run_login(args) -> int:
    from .read import dump_json
    try:
        if getattr(args, 'verify', False):
            result = open_verify()
        elif getattr(args, 'logout', False):
            result = logout()
        elif getattr(args, 'qr', False):
            result = login_qr(timeout=args.timeout)
        elif getattr(args, 'status', False):
            result = xhs_status()
        else:
            result = xhs_status(deep=False) if not args.force else None
            if result is None or result['state'] != 'ready':
                result = login()
    except Exception as exc:  # noqa: BLE001
        result = error_row(exc)
    if args.json:
        dump_json(result)
    else:
        print(result['message'] + ('\n下一步：' + result['next_step'] if result['next_step'] else ''))
    return 0 if result['state'] in ('ready', 'busy') or result['message'] == '已退出登录' else 1
