"""Small wrappers around existing login components; no cookie translation."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import tempfile
import webbrowser
from pathlib import Path

import httpx

from . import storage


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


def endpoint() -> str:
    return os.environ.get('LINK_BRAIN_XHS_ENDPOINT', 'http://127.0.0.1:18060/mcp')


def api(method: str, route: str, *, timeout: float = 45) -> dict:
    response = httpx.request(method, endpoint().removesuffix('/mcp') + route, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get('success') is False:
        raise RuntimeError(payload.get('message') or '读取服务未完成请求')
    return payload.get('data', payload)


def row(key: str, label: str, state: str, message: str, next_step: str = '', detail: str = '', optional=False) -> dict:
    return dict(id=key, label=label, state=state, message=message, next_step=next_step, detail=detail, optional=optional)


def xhs_status(*, timeout=45) -> dict:
    try:
        data = api('GET', '/api/v1/login/status', timeout=timeout)
        if data.get('is_logged_in') is True:
            return row('xhs', '小红书读取', 'ready', '已登录')
        if data.get('is_logged_in') is not False:
            raise ValueError('状态响应缺少 is_logged_in')
        cookie_paths = (home() / 'cookies.json', Path.home() / '.xiaohongshu-mcp' / 'cookies.json')
        expired = bool(config().get('xhs_authenticated')) or any(p.is_file() and p.stat().st_size > 4 for p in cookie_paths)
        return row('xhs', '小红书读取', 'expired' if expired else 'not_logged_in',
                   '登录已失效' if expired else '未登录', '运行 link-brain login，或点击「登录」。')
    except httpx.ConnectError as exc:
        return row('xhs', '小红书读取', 'disconnected', '未连接', '运行 link-brain login，自动启动读取组件。', str(exc))
    except Exception as exc:
        return row('xhs', '小红书读取', 'unknown', '暂时无法验证', '稍后点击「刷新状态」；不要重复扫码。', str(exc))


def fav_exe() -> str | None:
    return executable('LINK_BRAIN_FAVDUMP', ('favdump.exe', 'favdump'))


def fav_profile() -> Path:
    legacy = Path.home() / '.xiaohongshu-mcp' / 'data' / 'xhs' / 'momo-profile'
    return Path(os.environ.get('XHS_FAV_PROFILE') or os.environ.get('XHS_PROFILE_DIR') or
                config().get('favorite_profile') or
                str(legacy if legacy.is_dir() else home() / 'favorite-profile'))


def fav_env() -> dict:
    return {**os.environ, 'XHS_HOST': os.environ.get('XHS_FAV_HOST', 'https://www.xiaohongshu.com'),
            'XHS_PROFILE_DIR': str(fav_profile())}


def run_component(command: list[str], *, env: dict, timeout: int):
    # File-backed output avoids Windows child-browser pipe hangs on timeout.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(command, env=env, stdout=out, stderr=err,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True, timeout=15)
            else:
                proc.kill()
            proc.wait(timeout=15)
            raise RuntimeError('等待组件超时；请关闭该登录窗口，再从设置页重试。')
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(command, code, out.read(), err.read())


def favorite_status() -> dict:
    if not fav_exe():
        return row('favorites', '收藏同步', 'unconfigured', '可选，未配置',
                   '可先粘贴链接归档；需要私密收藏同步时查看 README「收藏组件」。', optional=True)
    if not fav_profile().exists():
        return row('favorites', '收藏同步', 'not_logged_in', '未登录', '运行 link-brain login favorites。', optional=True)
    try:
        result = run_component([fav_exe()], env=fav_env(), timeout=60)
        if result.returncode == 3:
            detail = result.stderr.decode('utf-8', 'replace')
            if 'login check failed' in detail.lower():
                raise RuntimeError(detail[-500:])
            return row('favorites', '收藏同步', 'expired', '登录已失效', '运行 link-brain login favorites。', optional=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode('utf-8', 'replace')[-500:])
        data = json.loads(result.stdout)
        if not isinstance(data.get('items'), list):
            raise ValueError('收藏组件没有返回 items 列表')
        return row('favorites', '收藏同步', 'ready', '已登录', optional=True)
    except Exception as exc:
        return row('favorites', '收藏同步', 'unknown', '暂时无法验证',
                   '关闭收藏登录窗口后刷新状态；读取链接仍可单独使用。', str(exc), True)


def attachment_profile() -> Path:
    explicit = os.environ.get('LINK_BRAIN_AB_PROFILE_PREFS')
    if explicit:
        return Path(explicit).parent.parent
    saved = config().get('attachment_profile')
    if saved:
        return Path(saved)
    # Preserve an explicitly configured existing browser, without an author path fallback.
    p = Path.home() / '.agent-browser' / 'config.json'
    if p.exists():
        existing = json.loads(p.read_text('utf-8')).get('profile')
        if existing and Path(existing).is_dir():
            return Path(existing)
    return home() / 'attachment-profile'


USER_STATE_JS = '''JSON.stringify((() => {
 const x=window.__INITIAL_STATE__?.user?.userInfo;
 const u=x?.value??x?._value??x?._rawValue??x;
 if(u?.guest===false && (u.userId||u.user_id)) return {state:'ready'};
 if(document.querySelector('.login-container,.login-modal,.side-bar-component.login-btn')) return {state:'not_logged_in'};
 return {state:'unknown'};
})())'''
USER_STATE_JS = ' '.join(USER_STATE_JS.splitlines())  # Windows .cmd does not preserve multiline argv.


def browser_state(output: str) -> str:
    try:
        value = json.loads(output.strip())
        if isinstance(value, str):
            value = json.loads(value)
        return value['state'] if value.get('state') in ('ready', 'not_logged_in') else 'unknown'
    except (ValueError, TypeError, AttributeError, KeyError):
        return 'unknown'


def attachment_check(*, login=False, timeout=240, force=False) -> dict:
    from .attachments import _ab, _agent_browser_exe
    try:
        _agent_browser_exe()
    except RuntimeError as exc:
        return row('attachments', '附件下载', 'unconfigured', '可选，未配置',
                   '需要自动下载时运行 npm install -g agent-browser，然后 agent-browser install。', str(exc), True)
    if not login and not attachment_profile().exists():
        return row('attachments', '附件下载', 'unconfigured', '可选，未配置', '需要下载附件时点击「扫码登录」。', optional=True)
    try:
        if force:
            if os.environ.get('LINK_BRAIN_AB_PROFILE_PREFS'):
                raise RuntimeError('附件登录目录由外部配置固定；请先取消该覆盖，再从设置页换号。')
            # A new profile allows changing account without deleting a saved session.
            save({'attachment_profile': str(home() / f'attachment-profile-{int(time.time())}')})
        code, out = _ab(['open', 'about:blank', *(['--headed'] if login else [])], timeout=45)
        if code != 0:
            raise RuntimeError(out[-400:])
        _ab(['eval', 'location.href="https://www.rednote.com/explore";"go"'], timeout=20)
        deadline = time.monotonic() + (timeout if login else 18)
        stable = 0
        state = 'unknown'
        while time.monotonic() < deadline:
            code, out = _ab(['eval', USER_STATE_JS], timeout=15)
            if code == 0:
                state = browser_state(out)
                stable = stable + 1 if state == 'ready' else 0
                if stable >= 2:
                    if login:
                        save({'attachments_authenticated': True})
                    return row('attachments', '附件下载', 'ready', '已登录', optional=True)
            time.sleep(2)
        if state == 'not_logged_in':
            expired = config().get('attachments_authenticated')
            return row('attachments', '附件下载', 'expired' if expired else 'not_logged_in',
                       '登录已失效' if expired else '未登录', '点击「重新扫码」，在打开的窗口完成登录。', optional=True)
        raise RuntimeError('页面没有给出可判断的登录状态')
    except Exception as exc:
        return row('attachments', '附件下载', 'unknown', '暂时无法验证', '关闭附件登录窗口后重试。', str(exc), True)
    finally:
        _ab(['close'], timeout=20)


def reader_exe() -> str | None:
    return executable('LINK_BRAIN_XHS_EXE', ('xiaohongshu-mcp-windows-amd64.exe', 'xiaohongshu-mcp.exe', 'xiaohongshu-mcp'))


def start_reader():
    exe = reader_exe()
    if not exe:
        raise RuntimeError('尚未安装读取组件。运行 link-brain login --install 下载官方 Windows 组件并登录。')
    from urllib.parse import urlsplit
    target = urlsplit(endpoint())
    if target.hostname not in ('localhost', '127.0.0.1'):
        raise RuntimeError('远程读取服务未连接，请由服务管理员启动后重试。')
    home().mkdir(parents=True, exist_ok=True)
    log = (home() / 'reader.log').open('ab')
    try:
        process = subprocess.Popen([exe, '-port', f':{target.port or 18060}'], cwd=home(),
                         env={**os.environ, 'COOKIES_PATH': str(home() / 'cookies.json')},
                         stdout=log, stderr=log,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    finally:
        log.close()
    for _ in range(30):
        try:
            api('GET', '/health', timeout=2)
            return process
        except httpx.HTTPError:
            time.sleep(1)
    raise RuntimeError('读取组件启动未完成。稍后重试；详情见 ' + str(home() / 'reader.log'))


def install_reader() -> None:
    import platform
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('自动下载目前仅支持 Windows x64；其他系统见 README 高级配置。')
    release = httpx.get('https://api.github.com/repos/xpzouying/xiaohongshu-mcp/releases/latest', timeout=30)
    release.raise_for_status()
    asset = next((a for a in release.json()['assets'] if a['name'] == 'xiaohongshu-mcp-windows-amd64.exe'), None)
    if not asset:
        raise RuntimeError('官方发布中未找到 Windows x64 包，请查看 README 的组件下载链接。')
    response = httpx.get(asset['browser_download_url'], follow_redirects=True, timeout=180)
    response.raise_for_status()
    dest = home() / 'bin'
    dest.mkdir(parents=True, exist_ok=True)
    (dest / asset['name']).write_bytes(response.content)


def login_xhs(*, force=False, timeout=300, install=False) -> dict:
    status = xhs_status()
    if status['state'] == 'disconnected':
        if install and not reader_exe():
            install_reader()
        start_reader()
        status = xhs_status(timeout=120)  # First launch may download the component's browser.
    if status['state'] == 'ready' and not force:
        save({'xhs_authenticated': True})
        return status
    if status['state'] == 'unknown':
        return status
    if force:
        api('DELETE', '/api/v1/login/cookies')
    qr = api('GET', '/api/v1/login/qrcode', timeout=60)
    if qr.get('is_logged_in'):
        if force:
            raise RuntimeError('当前读取组件仍保留已登录的持久会话，未切换账号；请先在该组件登录窗口退出账号。')
        return xhs_status()
    import html
    image = qr.get('img', '')
    if not image.startswith('data:image/'):
        raise RuntimeError('读取组件未返回扫码图片，请重试。')
    home().mkdir(parents=True, exist_ok=True)
    page = home() / 'login.html'
    def show(message, *, waiting=False):
        page.write_text('<meta charset="utf-8"><title>小红书登录</title>'
                        + ('<meta http-equiv="refresh" content="3">' if waiting else '')
                        + '<body style="text-align:center;font:20px sans-serif">'
                        + '<h2>小红书登录</h2><p>' + html.escape(message) + '</p>'
                        + (f'<img width="280" src="{html.escape(image, quote=True)}">' if waiting else ''), 'utf-8')
    show('请用小红书 App 扫码并确认。正在等待验证，请保持此页面打开。', waiting=True)
    if not webbrowser.open(page.as_uri()):
        raise RuntimeError('无法打开扫码页面，请打开 ' + str(page))
    deadline = time.monotonic() + timeout
    result = None
    last_error = ''
    try:
        while time.monotonic() < deadline:
            time.sleep(3)
            # Separate service browser; persistent-profile builds serialize this behind QR wait.
            try:
                data = api('GET', '/api/v1/login/status', timeout=max(1, deadline-time.monotonic()))
                if data.get('is_logged_in') is True:
                    save({'xhs_authenticated': True})
                    result = row('xhs', '小红书读取', 'ready', '已登录，登录态已由读取组件保存')
                    return result
                last_error = ''
            except (httpx.HTTPError, RuntimeError) as exc:
                # Older readers cannot launch a second browser while the QR browser is open.
                # Keep waiting for that browser to save and close instead of abandoning the scan.
                last_error = str(exc)
                show('已打开扫码流程，正在等待读取组件完成验证。请勿重复扫码。', waiting=True)
        result = row('xhs', '小红书读取', 'unknown' if last_error else 'not_logged_in',
                     '登录验证未完成' if last_error else '扫码超时',
                     '回到账号设置刷新状态；仍未登录时点击「登录」获取新二维码。', last_error)
        return result
    finally:
        show((result['message'] + '。' + result['next_step']) if result else
             '登录验证中断。请回到账号设置刷新状态后重试。')


def login_favorites(*, timeout=300, force=False) -> dict:
    status = favorite_status()
    if status['state'] == 'ready' and not force:
        return status
    exe = executable('LINK_BRAIN_FAV_LOGIN', ('xiaohongshu-login-persistent.exe',))
    if not fav_exe() or not exe:
        return row('favorites', '收藏同步', 'unconfigured', '收藏组件未配置',
                   '先使用链接归档；收藏组件准备步骤见 README「收藏组件」。', optional=True)
    if force and status['state'] == 'ready':
        if os.environ.get('XHS_FAV_PROFILE') or os.environ.get('XHS_PROFILE_DIR'):
            raise RuntimeError('收藏登录目录由外部配置固定；请先取消该覆盖，再从设置页换号。')
        save({'favorite_profile': str(home() / f'favorite-profile-{int(time.time())}')})
    result = run_component([exe], env=fav_env(), timeout=timeout)
    if result.returncode:
        raise RuntimeError('收藏登录未完成，请重新扫码。')
    return favorite_status()


def run_login(args) -> int:
    from .read import dump_json
    try:
        if args.account == 'attachments':
            result = attachment_check() if not args.force else None
            if result is None or result['state'] != 'ready':
                result = attachment_check(login=True, timeout=args.timeout, force=args.force)
            if result['state'] == 'ready':
                save({'attachments_authenticated': True})
        elif args.account == 'favorites':
            result = login_favorites(timeout=args.timeout, force=args.force)
        else:
            result = login_xhs(force=args.force, timeout=args.timeout, install=args.install)
    except Exception as exc:
        result = row(args.account, '登录', 'error', '登录未完成',
                     str(exc) if isinstance(exc, RuntimeError) else '请重试；仍失败时展开「查看详情」。', str(exc))
    if args.json:
        dump_json(result)
    else:
        print(result['message'] + ('\n下一步：' + result['next_step'] if result['next_step'] else ''))
    return 0 if result['state'] == 'ready' else 1
