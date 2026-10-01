"""小红书账号：一个号、一个读取服务、一个持久浏览器目录。

读取服务（link-brain-reader，xiaohongshu-mcp 的扩展版）独占一个 Chromium profile，
评论 / 私密收藏 / 附件都经它的 HTTP 接口、在同一进程里串行跑——同一个号不会再有
第二个网页会话去顶掉它（2026-09-25 实测：一个号三项全通）。

扫码的铁律：出码之后只轮询 `/login/session`（纯内存状态，不开浏览器）。
旧流程轮询 `/login/status`，而它每查一次都会把正在扫的二维码页导航走。

所有失败都落成 `ReaderError(code)`，`SOLUTIONS` 给出人话原因 + 下一步 + 界面按钮，
调用方据此停车，而不是反复重试（重试会撞风控验证码，0925 真撞过）。

1001 护号（审计 A-3/A-5/B-3/B-6）：
- 风控熔断：读取服务撞到验证 / 登录异常页会写 `<profile>/risk-hold.json`，之后拒绝一切开页请求
  （HTTP 423 · code=RISK_HOLD）。批量入口开工前先看 `risk_hold()`，有就直接停，不开页。
- 跨进程账号锁 `~/.link-brain/account.lock`：同步收藏 / 附件 / catch / 登录检查同一时刻只有一个在用号。
- 跨进程开页间隔 `pace()`：任何碰号的请求开页前，距上一次开页至少随机 20–40 秒（`last-open.txt`）。
"""
from __future__ import annotations

import contextlib
import html
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import storage

DEFAULT_ENDPOINT = 'http://127.0.0.1:18061/mcp'
READER_NAMES = ('link-brain-reader.exe', 'link-brain-reader')

# 要人处理的码（读取服务的风险码 + 本地要装组件）：撞见就停车，绝不重试
NEEDS_HUMAN_CODES = ('NOT_LOGGED_IN', 'CAPTCHA_REQUIRED', 'ACCOUNT_RISK', 'RISK_HOLD', 'NOT_INSTALLED')
RISK_CODES = ('CAPTCHA_REQUIRED', 'ACCOUNT_RISK', 'RISK_HOLD')

# code -> (状态, 一句话原因, 下一步, 界面按钮 action)
SOLUTIONS = {
    'NOT_LOGGED_IN': ('expired', '登录已失效', '点击「扫码登录」，用收藏所在的小红书账号扫码。', 'login'),
    'CAPTCHA_REQUIRED': ('captcha', '小红书要求安全验证', '点击「打开验证」，在弹出的窗口里手动拖动滑块，完成后关掉窗口；也可以过几小时再试。不要反复重试。', 'verify'),
    'ACCOUNT_RISK': ('expired', '小红书把读取号跳到了登录/安全页（风控）',
                     '所有用号的同步都已暂停。点击「扫码登录」用收藏所在的号重新登录，登录成功会自动恢复；'
                     '如果弹的是拼图验证就点「打开验证」手动完成。不要反复重试。', 'login'),
    'RISK_HOLD': ('captcha', '风控暂停中：读取服务已停止用号开页',
                  '上次撞到了安全验证或登录异常，之后所有会用号开页的操作都暂停了。点击「打开验证」或「扫码登录」处理完，'
                  '暂停会自动解除；在那之前夜里的同步、附件补下都会跳过。', 'verify'),
    'ACCOUNT_BUSY': ('busy', '正在同步收藏', '号正被另一个任务使用（同步收藏 / 附件 / 导入），它做完再试。', 'wait'),
    'RATE_LIMITED': ('busy', '刚刚同步过', '为避免触发风控，收藏每 10 分钟最多读一次，请稍后再试。', 'wait'),
    'LOGIN_IN_PROGRESS': ('busy', '正在等待扫码', '先完成或关闭正在进行的扫码，再重试。', 'wait'),
    'VERIFY_WINDOW_OPEN': ('busy', '验证窗口还开着', '完成验证后关掉那个小红书窗口，再重试。', 'wait'),
    'DISCONNECTED': ('disconnected', '读取服务没有运行', '点击「重试」会自动启动；仍失败请查看详情里的日志路径。', 'retry'),
    'NOT_INSTALLED': ('unconfigured', '未安装读取组件', '按 README「小红书读取组件」放置 link-brain-reader，然后刷新状态。', 'none'),
    'NO_DOWNLOAD_BUTTON': ('error', '附件页没有下载按钮', '文件可能已被作者删除或关闭下载，可在网页手动下载后用「挂载本地文件」。', 'none'),
    'DOWNLOAD_TIMEOUT': ('error', '附件下载超时', '稍后重试；多次失败请在网页手动下载后挂载。', 'retry'),
    'TIMEOUT': ('unknown', '读取服务响应超时', '机器负载高时会发生：稍后点击「重试」。', 'retry'),
    'BUSY': ('unknown', '读取服务正忙', '正在抓别的笔记，做完自然恢复；不是掉登录，不用扫码。', 'retry'),
}


class ReaderError(RuntimeError):
    def __init__(self, code: str, message: str = '', detail: str = '', *, hold: dict | None = None):
        self.code, self.detail, self.hold = code, detail, hold
        super().__init__(message or SOLUTIONS.get(code, ('', code))[1])

    @property
    def needs_human(self) -> bool:
        return self.code in NEEDS_HUMAN_CODES


class AccountBusyError(RuntimeError):
    """账号锁被别的任务占着（CLI 退出码 6）。`holder` = 锁文件内容（pid / owner / started / heartbeat）。"""

    exit_code = 6

    def __init__(self, holder: dict | None = None):
        self.holder = holder or {}
        owner = self.holder.get('owner') or '别的任务'
        super().__init__(f'号正被「{owner}」使用（正在同步收藏或下附件），稍后再试')


def home() -> Path:
    return Path(os.environ.get('LINK_BRAIN_HOME', str(Path.home() / '.link-brain')))


def _atomic_write_text(path: Path, text: str) -> None:
    """先写临时文件再 os.replace：进程半路被杀也不会留下半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(text, encoding='utf-8')
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


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
    _atomic_write_text(home() / 'accounts.json', json.dumps(data, ensure_ascii=False, indent=2))


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


# 会让读取服务用号开页的接口：请求回来（成功失败都算）时把开页时刻戳挪到「这页看完」（见 pace_done）
PAGE_ROUTES = ('/api/v1/favorites', '/api/v1/attachments/download', '/api/v1/notes/related-file',
               '/api/v1/login/status')


def api(method: str, route: str, *, timeout: float = 45, body: dict | None = None) -> dict:
    opens_page = route.split('?', 1)[0] in PAGE_ROUTES
    try:
        response = httpx.request(method, base_url() + route, json=body, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ReaderError('TIMEOUT', detail=str(exc)) from exc
    except httpx.RequestError as exc:
        # 1001（A-5）：连接被重置（10054 → ReadError / RemoteProtocolError）和连不上一样，都是「服务断了」。
        # 以前只接 ConnectError，下载附件途中断线就一路崩到整晚补下 / 补查停掉。
        raise ReaderError('DISCONNECTED', detail=f'{type(exc).__name__}: {exc}') from exc
    finally:
        if opens_page:
            pace_done()
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if response.status_code >= 400 or payload.get('success') is False:
        code = payload.get('code') or ('RISK_HOLD' if response.status_code == 423 else f'HTTP_{response.status_code}')
        detail = payload.get('details')
        hold = payload.get('hold') if isinstance(payload.get('hold'), dict) else None
        if code == 'RISK_HOLD' and hold and not detail:
            detail = hold
        exc = ReaderError(code, payload.get('error') or payload.get('message') or '',
                          json.dumps(detail, ensure_ascii=False) if isinstance(detail, (dict, list)) else str(detail or ''),
                          hold=hold)
        _note_account(exc.code, f'{route}: {exc}')
        raise exc
    return payload.get('data', payload)


def _note_account(code: str, detail: str = '') -> None:
    """掉登录 / 要验证：不管哪个环节撞见，都点亮目录页的「!」（0927）。写不进去不影响主流程。"""
    try:
        from . import sync_state
        if code in sync_state.ACCOUNT_CODES:
            sync_state.account_problem(code, detail)
        elif code == 'OK':
            sync_state.account_ok()
    except Exception:  # noqa: BLE001
        pass


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


def restart_reader() -> None:
    """服务卡死（常见于高负载下浏览器启动没回来、一直占着账号目录）时：结束服务和占着该目录的浏览器，再拉起。

    0929：只杀真卡死的。服务只是正忙（正在抓一篇长评论）时，登录检查会排队超时；以前据此把服务连同
    正在用账号目录的浏览器一起杀掉 → 正在跑的同步/补查全断（10054），新浏览器读到的是没落好盘的账号目录，
    误判「游客」弹登录窗。现在先问一下服务本身还应不应答（毫秒级接口），应答就说明是忙不是死，不杀。

    1001（A-3）：但「应答」不等于「没卡死」——关浏览器卡住时锁永远不放，session 照样秒回。
    所以应答时再看它报的锁占了多久：超过 XHS_LOCK_MAX_S + 60 秒才算卡死，照旧重启；
    没有锁 / 锁还在预算内 = 忙，不杀。session 不应答才按旧逻辑直接重启。
    """
    if os.name != 'nt' or urlsplit(endpoint()).hostname not in ('localhost', '127.0.0.1'):
        return
    try:
        session = api('GET', '/api/v1/login/session', timeout=5)
    except ReaderError:
        session = None  # 不应答：真死了
    if session is not None:
        lock = session.get('lock') if isinstance(session.get('lock'), dict) else None
        held = (lock or {}).get('held_s')
        if not (isinstance(held, (int, float)) and held > lock_max_seconds() + 60):
            raise ReaderError('BUSY', '读取服务正在处理别的任务（没有卡死），等它做完再试')
        print(f'[reader] 读取服务的锁被「{lock.get("owner")}」占了 {held:.0f} 秒，判定卡死，重启', file=sys.stderr)
    profile =str(profile_dir()).replace("'", "''")
    names = ','.join(f"'{n}'" for n in READER_NAMES)
    script = (f"Get-CimInstance Win32_Process | Where-Object {{ @({names}) -contains $_.Name -or "
              f"($_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*{profile}*') }} | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], capture_output=True, timeout=30,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(1)
    ensure_reader()


def lock_max_seconds() -> float:
    """读取服务单次占锁的上限（与服务端 XHS_LOCK_MAX_S 同一个变量，默认 900 秒）。"""
    try:
        return float(os.environ.get('XHS_LOCK_MAX_S') or 900)
    except ValueError:
        return 900.0


# ---------------------------------------------------------------------------
# 风控熔断（1001，B-3）：服务端写 <profile>/risk-hold.json；这里只读，解除只能靠登录 / 验证 / 人工清除
# ---------------------------------------------------------------------------


def _hold_file() -> dict | None:
    path = profile_dir() / 'risk-hold.json'
    try:
        data = json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('code') else None


def hold_from_session(session: dict | None) -> dict | None:
    """session 带 risk_hold 字段就以它为准（服务是权威）；老版本服务没有这个字段就退回读文件。"""
    if isinstance(session, dict) and 'risk_hold' in session:
        hold = session.get('risk_hold')
        return hold if isinstance(hold, dict) and hold else None
    return _hold_file()


def risk_hold() -> dict | None:
    """现在是不是在熔断中。只问 /login/session（不拿锁、不开浏览器）；服务不在就直接读熔断文件。"""
    try:
        session = ensure_reader()
    except ReaderError:
        return _hold_file()
    return hold_from_session(session)


def hold_error(hold: dict) -> ReaderError:
    since = hold.get('since') or ''
    detail = ' · '.join(str(x) for x in (hold.get('code'), since, hold.get('detail')) if x)
    return ReaderError('RISK_HOLD', detail=detail, hold=hold)


def check_risk_hold() -> None:
    """批量入口开工前调：熔断中就抛 ReaderError('RISK_HOLD')，调用方停车（退出码 5），一页都不开。"""
    hold = risk_hold()
    if hold:
        raise hold_error(hold)


# ---------------------------------------------------------------------------
# 跨进程账号锁（1001，B-6）：~/.link-brain/account.lock = {pid, owner, started, heartbeat}
# ---------------------------------------------------------------------------

LOCK_STALE_SECONDS = 10 * 60
LOCK_HEARTBEAT_SECONDS = 60
_LOCK_STATE: dict = {'count': 0, 'stop': None, 'thread': None, 'owner': ''}
_LOCK_GUARD = threading.Lock()


def lock_path() -> Path:
    return home() / 'account.lock'


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _pid_state(pid) -> str:
    """'alive' / 'dead' / 'unknown'。只有确认进程不在了才是 dead。

    Windows 上 OpenProcess 失败不一定是进程没了：拒绝访问（别的用户 / 会话、提权进程）也会失败。
    那种情况算 unknown，交给心跳判陈旧，别把别人活着的锁当垃圾接管。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return 'dead'
    if pid <= 0:
        return 'dead'
    if os.name == 'nt':
        import ctypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            err = ctypes.get_last_error()
            return 'dead' if err == 87 else 'unknown'  # 87 = ERROR_INVALID_PARAMETER：没有这个进程
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return 'unknown'
            return 'alive' if code.value == 259 else 'dead'  # 259 = STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return 'alive'
    except ProcessLookupError:
        return 'dead'
    except OSError:
        return 'unknown'


def _read_lock() -> tuple[str | None, dict | None]:
    try:
        raw = lock_path().read_text('utf-8')
    except FileNotFoundError:
        return None, None
    except OSError:
        return '', None  # 正在被改写（Windows 上 replace 那一瞬）：当它还在
    try:
        data = json.loads(raw)
    except ValueError:
        return raw, None
    return raw, data if isinstance(data, dict) else None


def _lock_is_stale(info: dict | None) -> bool:
    if not info:
        try:
            return time.time() - lock_path().stat().st_mtime > 60  # 写坏的锁文件：放一分钟再当垃圾
        except OSError:
            return False
    pid = info.get('pid')
    if pid == os.getpid() and not _LOCK_STATE['count']:
        return True  # 本进程以前没放掉的
    if _pid_state(pid) == 'dead':
        return True
    beat = info.get('heartbeat_ts')
    if not isinstance(beat, (int, float)):
        try:
            beat = datetime.fromisoformat(str(info.get('heartbeat'))).timestamp()
        except ValueError:
            beat = 0
    return time.time() - beat > LOCK_STALE_SECONDS


def lock_holder() -> dict | None:
    """别的活进程正占着账号锁 → 锁内容；没人占 / 陈旧锁 → None。"""
    raw, info = _read_lock()
    if raw is None:
        return None
    if _lock_is_stale(info):
        return None
    if info and info.get('pid') == os.getpid():
        return None
    return info or {'owner': '另一个任务'}


def _lock_payload(owner: str, started: str) -> str:
    now = time.time()
    return json.dumps({'pid': os.getpid(), 'owner': owner, 'started': started,
                       'heartbeat': _now_iso(), 'heartbeat_ts': now}, ensure_ascii=False)


def _try_take(owner: str) -> bool:
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    started = _now_iso()
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raw, info = _read_lock()
            if raw is None:
                continue  # 刚被放掉
            if not _lock_is_stale(info):
                return False
            # 陈旧锁：先挪走再抢。os.rename 只有一个进程能成功；挪到手的内容和刚才判陈旧的不一样
            # （别人抢先换上了新锁）就原样放回去。
            aside = path.with_name(f'{path.name}.{os.getpid()}.stale')
            try:
                os.rename(path, aside)
            except OSError:
                return False
            try:
                moved = aside.read_text('utf-8')
            except OSError:
                moved = raw
            if moved != raw:
                try:
                    os.rename(aside, path)
                except OSError:
                    pass
                return False
            aside.unlink(missing_ok=True)
            print(f'[lock] 接管陈旧的账号锁（{(info or {}).get("owner")} pid={(info or {}).get("pid")}）',
                  file=sys.stderr)
            continue
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(_lock_payload(owner, started))
        _LOCK_STATE['started'] = started
        return True
    return False


def _heartbeat(stop: threading.Event, owner: str) -> None:
    while not stop.wait(LOCK_HEARTBEAT_SECONDS):
        raw, info = _read_lock()
        if raw == '':
            continue  # 正在被改写的那一瞬，下一拍再看
        if not info or info.get('pid') != os.getpid():
            # 锁被当成陈旧的接管了（笔记本睡过 10 分钟等）：不去抢回来，但要让本进程停手——
            # 下一次 pace() 抛 AccountBusyError，批量入口停批，别在没锁的情况下接着用号。
            _LOCK_STATE['lost'] = True
            print('[lock] 账号锁被别的任务接管了：本任务开完手上这一页就停', file=sys.stderr)
            return
        try:
            _atomic_write_text(lock_path(), _lock_payload(owner, _LOCK_STATE.get('started') or _now_iso()))
        except OSError:
            pass  # 这一拍没写上，十分钟余量够下一拍补


def _release() -> None:
    stop = _LOCK_STATE.get('stop')
    if stop:
        stop.set()
    _, info = _read_lock()
    if info and info.get('pid') == os.getpid():
        try:
            lock_path().unlink()
        except OSError:
            pass
    _LOCK_STATE.update(stop=None, thread=None, owner='', lost=False)


@contextlib.contextmanager
def account_session(owner: str, wait_s: float = 0):
    """拿账号锁（同一进程可重入）。wait_s 内拿不到 → AccountBusyError（CLI 退出码 6）。"""
    with _LOCK_GUARD:
        if _LOCK_STATE['count']:
            _LOCK_STATE['count'] += 1
            nested = True
        else:
            nested = False
    if nested:
        try:
            yield
        finally:
            with _LOCK_GUARD:
                _LOCK_STATE['count'] -= 1
        return
    deadline = time.monotonic() + max(0.0, float(wait_s or 0))
    told = False
    while not _try_take(owner):
        left = deadline - time.monotonic()
        if left <= 0:
            raise AccountBusyError(lock_holder())
        if not told:
            holder = lock_holder() or {}
            print(f'[lock] 号正被「{holder.get("owner") or "别的任务"}」使用，最多等 {left / 60:.0f} 分钟',
                  file=sys.stderr)
            told = True
        time.sleep(min(5.0, max(0.2, left)))
    stop = threading.Event()
    thread = threading.Thread(target=_heartbeat, args=(stop, owner), daemon=True, name='account-lock-heartbeat')
    with _LOCK_GUARD:
        _LOCK_STATE.update(count=1, stop=stop, thread=thread, owner=owner, lost=False)
    thread.start()
    try:
        yield
    finally:
        with _LOCK_GUARD:
            _LOCK_STATE['count'] = 0
        _release()


# ---------------------------------------------------------------------------
# 跨进程开页间隔（1001，B-2）
# ---------------------------------------------------------------------------


def _gap_range(env: str, default: str) -> tuple[float, float]:
    try:
        lo, hi = (float(x) for x in (os.environ.get(env) or default).split(','))
    except ValueError:
        lo, hi = (float(x) for x in default.split(','))
    return (min(lo, hi), max(lo, hi))


def _pace_stamp() -> Path:
    return home() / 'last-open.txt'


def pace_done() -> None:
    """碰号的请求回来了（成功失败都算）：时刻戳挪到「这一页看完」。

    只在开页前打戳的话，一次长操作（读收藏滚 5 分钟、评论多的笔记）之后下一页会零间隔紧跟着开；
    从上一页结束起算，才像人看完一页再去点下一页。"""
    try:
        _atomic_write_text(_pace_stamp(), str(time.time()))
    except OSError:
        pass


def pace(what: str = '开页') -> float:
    """碰号的请求开页前调：保证距上一次开页（任何进程，从上一页看完算起）至少随机 20–40 秒。返回实际等了几秒。

    本进程拿着的账号锁被别人当陈旧锁接管了（笔记本睡过 10 分钟等）→ 抛 AccountBusyError，调用方停批，
    别在没锁的情况下接着用号。"""
    if _LOCK_STATE.get('lost'):
        raise AccountBusyError(lock_holder())
    lo, hi = _gap_range('LWA_OPEN_GAP', '20,40')
    stamp = _pace_stamp()
    try:
        last = float(stamp.read_text('utf-8').strip())
    except (OSError, ValueError):
        last = 0.0
    wait = min(random.uniform(lo, hi) - (time.time() - last), hi)
    if wait > 0:
        print(f'[pace] 像人一样歇 {wait:.0f} 秒再{what}', file=sys.stderr)
        time.sleep(wait)
    try:
        _atomic_write_text(stamp, str(time.time()))
    except OSError:
        pass
    return max(wait, 0.0)


def row(key: str, label: str, state: str, message: str, next_step: str = '', detail: str = '',
        optional=False, action: str = '', account: str = '') -> dict:
    return dict(id=key, label=label, state=state, message=message, next_step=next_step, detail=detail,
                optional=optional, action=action, account=account)


def error_row(exc: Exception, key='xhs', label='小红书账号') -> dict:
    if isinstance(exc, ReaderError) and exc.code == 'RISK_HOLD':
        return hold_row(exc.hold or {'code': 'RISK_HOLD', 'detail': exc.detail}, key=key, label=label)
    if isinstance(exc, ReaderError) and exc.code in SOLUTIONS:
        state, message, step, action = SOLUTIONS[exc.code]
        out = row(key, label, state, message, step, exc.detail or '', action=action)
        out['code'] = exc.code
        return out
    if isinstance(exc, AccountBusyError):
        state, message, step, action = SOLUTIONS['ACCOUNT_BUSY']
        out = row(key, label, state, message, step, str(exc), action=action)
        out['code'] = 'ACCOUNT_BUSY'
        return out
    return row(key, label, 'unknown', '暂时无法验证', '稍后点击「重试」；持续出现请展开详情。',
               str(exc), action='retry')


def hold_row(hold: dict, key='xhs', label='小红书账号') -> dict:
    """熔断中的一行：按撞到的是什么决定按钮——掉登录 / 登录异常页 → 扫码；验证码 → 打开验证。"""
    state, message, step, _ = SOLUTIONS['RISK_HOLD']
    cause = str(hold.get('code') or '')
    action = 'login' if cause in ('NOT_LOGGED_IN', 'ACCOUNT_RISK') else 'verify'
    if action == 'login':
        state = 'expired'
    since = str(hold.get('since') or '')
    detail = ' · '.join(x for x in (cause, since, str(hold.get('detail') or '')) if x)
    out = row(key, label, state, message, step, detail, action=action)
    out['code'] = 'RISK_HOLD'
    out['risk_hold'] = hold
    return out


# login --status --json 的 login_state（契约名 state，见 run_login 的说明）
LOGIN_STATES = {'logged_in': 0, 'guest': 3, 'unknown': 4, 'risk_hold': 5}


def status_report(*, deep=True) -> tuple[dict, str]:
    """(界面那一行, login_state)。login_state ∈ logged_in / guest / unknown / risk_hold。

    1001：熔断中不开浏览器；账号锁被别的任务占着（同步收藏在跑）、或读取服务正在干活时也不开浏览器，
    直接报「查不清」——以前这时去排队，45 秒超时就被 20:00 的检查报成「掉登录了，去扫码」。
    """
    try:
        session = ensure_reader()
    except ReaderError as exc:
        hold = _hold_file()
        if hold:
            return hold_row(hold), 'risk_hold'
        if exc.code in RISK_CODES:
            return error_row(exc), 'risk_hold'
        return error_row(exc), 'unknown'
    except Exception as exc:  # noqa: BLE001 - 状态检查永不抛给界面
        return error_row(exc), 'unknown'
    try:
        hold = hold_from_session(session)
        if hold:
            return hold_row(hold), 'risk_hold'
        if session.get('state') == 'waiting':
            return error_row(ReaderError('LOGIN_IN_PROGRESS')), 'unknown'
        if session.get('verifying'):
            return error_row(ReaderError('VERIFY_WINDOW_OPEN')), 'unknown'
        name = config().get('nickname', '')
        if not deep and session.get('logged_in') is not None:
            ok = session['logged_in']
        else:
            holder = lock_holder()
            if holder:
                return error_row(AccountBusyError(holder)), 'unknown'
            if isinstance(session.get('lock'), dict) and session['lock']:
                return error_row(ReaderError('BUSY', detail=f"读取服务正在处理「{session['lock'].get('owner')}」")), 'unknown'
            with account_session('login-status', wait_s=0):
                try:
                    data = api('GET', '/api/v1/login/status', timeout=45)
                except ReaderError as exc:
                    if exc.code != 'TIMEOUT':
                        raise
                    restart_reader()  # 真卡死才会重启（见 restart_reader）；只是忙会抛 BUSY
                    data = api('GET', '/api/v1/login/status', timeout=60)
            if data.get('login_pending'):
                return error_row(ReaderError('LOGIN_IN_PROGRESS')), 'unknown'
            ok = data.get('is_logged_in') is True
            if ok and data.get('username'):
                name = data['username']
                save({'nickname': name, 'user_id': data.get('user_id', '')})
        _note_account('OK' if ok else 'NOT_LOGGED_IN', '登录检查：未登录')
        if ok:
            return row('xhs', '小红书账号', 'ready', '已登录' + (f'：{name}' if name else ''), account=name), 'logged_in'
        if config().get('nickname'):
            return error_row(ReaderError('NOT_LOGGED_IN')), 'guest'
        out = row('xhs', '小红书账号', 'not_logged_in', '未登录', '点击「扫码登录」，用收藏所在的账号扫码。',
                  action='login')
        out['code'] = 'NOT_LOGGED_IN'
        return out, 'guest'
    except ReaderError as exc:
        if exc.code in RISK_CODES:
            return error_row(exc), 'risk_hold'
        if exc.code == 'NOT_LOGGED_IN':
            return error_row(exc), 'guest'
        return error_row(exc), 'unknown'
    except Exception as exc:  # noqa: BLE001 - 状态检查永不抛给界面（锁被占 → AccountBusyError 也在这）
        return error_row(exc), 'unknown'


def xhs_status(*, deep=True) -> dict:
    """一个账号一行。deep=False 只看服务内存状态（不开浏览器，毫秒级）。"""
    return status_report(deep=deep)[0]


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


def login(*, timeout=420) -> dict:  # 服务端最长：等锁 60 秒 + 扫码 300 秒，再留余量
    """打开小红书官方登录窗口，人在官方页面扫码；这里只轮询服务内存态，窗口由服务关闭并落盘。"""
    ensure_reader()
    try:
        api('POST', '/api/v1/login/window', timeout=20)
    except ReaderError as exc:
        if exc.code != 'TIMEOUT':
            raise
        restart_reader()
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
    for key in ('nickname', 'user_id', 'sync_account'):  # 主动换号/退出 = 下次同步认新号
        data.pop(key, None)
    home().mkdir(parents=True, exist_ok=True)
    _atomic_write_text(home() / 'accounts.json', json.dumps(data, ensure_ascii=False, indent=2))
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
    """`login`。`--status` 的退出码（1001 契约）：0 已登录 · 3 游客 · 4 查不清（忙 / 超时 / 连不上 / 锁被占）· 5 熔断中。

    `--status --json` 仍输出插件账号面板要的那一行（state=ready/expired/…，插件按它画按钮），
    另加 `login_state`（logged_in / guest / unknown / risk_hold）、`code`、`detail`、`hold_cause` 给脚本用。
    脚本（xhs-login-check.ps1）判 `login_state` 或退出码，**不要判 `state`**（那是插件的取值）。
    """
    from .read import dump_json
    if getattr(args, 'status', False) and not any(getattr(args, k, False) for k in ('verify', 'logout', 'qr')):
        result, login_state = status_report()
        hold = result.get('risk_hold') if isinstance(result.get('risk_hold'), dict) else {}
        result = {**result, 'login_state': login_state, 'code': result.get('code') or '',
                  'detail': result.get('detail') or '',
                  # 熔断的起因（NOT_LOGGED_IN / ACCOUNT_RISK / CAPTCHA_REQUIRED）：脚本据此选「掉登录去扫码」还是「要验证」
                  'hold_cause': (str(hold.get('code') or '') or
                                 (result.get('code') if result.get('code') != 'RISK_HOLD' else '') or '')
                  if login_state == 'risk_hold' else ''}
        if args.json:
            dump_json(result)
        else:
            print(result['message'] + ('\n下一步：' + result['next_step'] if result['next_step'] else ''))
        return LOGIN_STATES[login_state]
    try:
        if getattr(args, 'verify', False):
            result = open_verify()
        elif getattr(args, 'logout', False):
            result = logout()
        elif getattr(args, 'qr', False):
            result = login_qr(timeout=args.timeout)
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
