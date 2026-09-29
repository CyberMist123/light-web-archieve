"""Last sync outcome for the local UI, independent of notification integrations."""
import os
from datetime import datetime

from . import storage


def path():
    return storage.archive_root() / 'sync-status.json'


def _alive(pid) -> bool:
    """只查不杀。Windows 上 os.kill(pid, 0) 会真的结束进程，不能用。"""
    if not pid:
        return False
    if os.name == 'nt':
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def load():
    try:
        status = storage.read_json(path())
    except (OSError, ValueError):
        return {}
    # 0929：同步进程被打断（关 Obsidian / 结束进程）时来不及写结果，状态会永远停在「正在同步」。
    # 读的时候核一下进程还在不在，不在就如实说中断了。
    if status.get('state') == 'running' and status.get('pid') and not _alive(status['pid']):
        status = {**status, 'state': 'failed', 'code': 'INTERRUPTED',
                  'message': '上次同步中途被打断（Obsidian 关闭或进程被结束），已抓的都在；再点一次同步会接着来',
                  'detail': status.get('progress', '')}
    return status


def progress_log():
    return storage.archive_root() / 'sync-progress.log'


def progress(text):
    """同步走到哪一步：写进状态（设置页显示）并追加到 _archive/sync-progress.log（事后查卡在哪）。"""
    now = datetime.now().astimezone()
    try:
        with progress_log().open('a', encoding='utf-8') as f:
            f.write(f"{now:%Y-%m-%d %H:%M:%S}  {text}\n")
        status = storage.read_json(path())
        if status.get('state') == 'running':
            storage.write_json(path(), {**status, 'message': f'正在同步收藏：{text}', 'progress': text,
                                        'updated_at': now.isoformat()})
    except (OSError, ValueError):
        pass


def record(state, *, payload=None, message='', account=None, code=''):
    previous = load()
    now = datetime.now().astimezone().isoformat()
    payload = payload or {}
    errors = [item for item in payload.get('items', []) if item.get('status') in ('blocked', 'error')]
    if state == 'finished':
        state = 'blocked' if any(x.get('status') == 'blocked' for x in errors) else ('failed' if errors else 'ready')
        message = ('同步已暂停，需要恢复登录或连接' if state == 'blocked' else
                   '部分收藏未同步成功' if errors else '收藏同步完成')
        if state == 'ready' and payload.get('deferred'):
            message = f"今天已新抓 {payload.get('daily_limit')} 篇，还有 {payload['deferred']} 篇明天继续"
        account = payload.get('login_account', errors[0].get('login_account') if errors else None)
        code = payload.get('code') or (errors[0].get('code') if errors else '') or ''
        if code == 'RATE_LIMITED':
            state, message = 'ready', '刚刚同步过，本次跳过'
            if previous.get('state') not in (None, 'ready', 'running'):
                state, message = previous['state'], previous.get('message', '')
    status = {'state': state, 'message': message, 'account': account, 'updated_at': now,
              'last_success': now if state == 'ready' else previous.get('last_success'),
              'favorites': payload.get('favorites'), 'synced': payload.get('synced'),
              'code': code, 'detail': errors[0].get('error', '') if errors else ''}
    if state == 'running':
        status['pid'] = os.getpid()
    storage.write_json(path(), status)
    return status


ACCOUNT_CODES = ('NOT_LOGGED_IN', 'CAPTCHA_REQUIRED')


def account_problem(code, detail=''):
    """任何环节（同步 / 附件下载 / 附件补查 / 登录检查）撞见掉登录或安全验证，都记到目录页那个「!」上。

    0927：以前只有同步收藏会写这里，下载附件时掉登录只发手机提醒、目录页照样显示正常。
    """
    previous = load()
    if previous.get('state') == 'blocked' and previous.get('code') == code:
        return previous
    message = '小红书账号掉登录了：点「!」扫码登录' if code == 'NOT_LOGGED_IN' else '小红书要安全验证：点「!」打开验证窗口'
    status = {**previous, 'state': 'blocked', 'message': message, 'account': 'xhs', 'code': code,
              'detail': str(detail)[:300], 'updated_at': datetime.now().astimezone().isoformat()}
    storage.write_json(path(), status)
    return status


def account_ok():
    """登录恢复了：只清掉『账号类』的「!」，别的失败原样留着。"""
    previous = load()
    if previous.get('state') == 'blocked' and previous.get('code') in ACCOUNT_CODES:
        status = {**previous, 'state': 'ready', 'message': '已重新登录，下次同步照常进行', 'code': '', 'detail': '',
                  'updated_at': datetime.now().astimezone().isoformat()}
        storage.write_json(path(), status)
        return status
    return previous
