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


# 跨次保留的字段：last_favorites = 上次**正常**读到的收藏条数（判「读少了一大截」的基准）；
# suspect_favorites = 最近几晚连着读到的可疑条数 {count, nights}
_CARRY = ('last_favorites', 'suspect_favorites')
SUSPECT_ADOPT_NIGHTS = 3  # 连着 3 晚读到差不多同一个「可疑」条数：多半是她真的删了一批收藏，认作新基准


def _update_baseline(status, payload):
    """1001：基准只认正常读到的条数。读到一截（可疑）的那次不能顶掉基准，不然第二晚再截断就不报了。

    例外：连着 SUSPECT_ADOPT_NIGHTS 晚读到的都是差不多同一个数（±10%），说明收藏真的变少了（她删了一批），
    这一晚照样报，但之后以它为基准，免得每晚都报。0 条永远不认。"""
    total = payload.get('favorites_total')
    if not total:
        return
    if not payload.get('suspicious'):
        status['last_favorites'] = total
        status.pop('suspect_favorites', None)
        return
    prev = status.get('suspect_favorites') if isinstance(status.get('suspect_favorites'), dict) else {}
    count = prev.get('count') or 0
    same = count and abs(total - count) <= max(2, count * 0.1)
    nights = (int(prev.get('nights') or 0) + 1) if same else 1
    if nights >= SUSPECT_ADOPT_NIGHTS:
        status['last_favorites'] = total
        status.pop('suspect_favorites', None)
    else:
        status['suspect_favorites'] = {'count': total, 'nights': nights}


def record(state, *, payload=None, message='', account=None, code=''):
    previous = load()
    now = datetime.now().astimezone().isoformat()
    payload = payload or {}
    # known_bad = 以前就抓不到的收藏（已删 / 仅作者可见）又没抓到：不算这次同步失败（1001）
    errors = [item for item in payload.get('items', [])
              if item.get('status') in ('blocked', 'error') and not item.get('known_bad')]
    detail = errors[0].get('error', '') if errors else ''
    if state == 'finished':
        state = 'blocked' if any(x.get('status') == 'blocked' for x in errors) else ('failed' if errors else 'ready')
        message = ('同步已暂停，需要恢复登录或连接' if state == 'blocked' else
                   '部分收藏未同步成功' if errors else '收藏同步完成')
        account = payload.get('login_account', errors[0].get('login_account') if errors else None)
        code = payload.get('code') or (errors[0].get('code') if errors else '') or ''
        if code == 'RATE_LIMITED':
            # 1001（审计 state-4）：限频 = 这次根本没读，别把之前的失败 / 掉登录「!」冲掉，也别改 last_success。
            # running 那一刻存下的 before 才是「这次之前」的真实状态。
            before = previous.get('before') if previous.get('state') == 'running' else previous
            before = before if isinstance(before, dict) else {}
            if before.get('state') not in (None, 'ready', 'running'):
                keep = {k: before.get(k) for k in ('state', 'message', 'account', 'code', 'detail', 'last_success',
                                                   'favorites', 'synced', 'updated_at')}
                status = {**keep, **{k: previous.get(k) for k in _CARRY if k in previous}}
                storage.write_json(path(), status)
                return status
            status = {'state': 'ready', 'message': '刚刚同步过，本次跳过（每 10 分钟最多读一次收藏，稍后再试）',
                      'account': None, 'updated_at': now, 'last_success': before.get('last_success'),
                      'favorites': before.get('favorites'), 'synced': before.get('synced'), 'code': code, 'detail': ''}
            status.update({k: previous[k] for k in _CARRY if k in previous})
            storage.write_json(path(), status)
            return status
        if state == 'ready' and payload.get('suspicious'):
            # 收藏读回 0 条 / 比上次少了一半以上：照常处理读到的，但不能算「同步完成」
            state, code, message = 'failed', 'FAVORITES_SUSPICIOUS', payload['suspicious']
            detail = payload['suspicious']
        elif state == 'ready' and payload.get('deferred'):
            if payload.get('deferred_reason') == 'budget':
                message = f"今天先到这，剩 {payload['deferred']} 篇明天继续"
            else:
                message = f"今天已新抓 {payload.get('daily_limit')} 篇，还有 {payload['deferred']} 篇明天继续"
    status = {'state': state, 'message': message, 'account': account, 'updated_at': now,
              'last_success': now if state == 'ready' else previous.get('last_success'),
              'favorites': payload.get('favorites'), 'synced': payload.get('synced'),
              'code': code, 'detail': detail}
    status.update({k: previous[k] for k in _CARRY if k in previous})
    _update_baseline(status, payload)
    if state == 'running':
        status['pid'] = os.getpid()
        if previous.get('state') != 'running':
            status['before'] = {k: v for k, v in previous.items() if k != 'before'}
        elif isinstance(previous.get('before'), dict):
            status['before'] = previous['before']
    storage.write_json(path(), status)
    return status


def running_elsewhere() -> bool:
    """别的活进程正在同步（状态 running 且 pid 活着、不是本进程）：这时别去改状态文件。"""
    status = load()
    return status.get('state') == 'running' and status.get('pid') not in (None, os.getpid())


ACCOUNT_CODES = ('NOT_LOGGED_IN', 'CAPTCHA_REQUIRED', 'ACCOUNT_RISK', 'RISK_HOLD')
_ACCOUNT_MESSAGES = {
    'NOT_LOGGED_IN': '小红书账号掉登录了：点「!」扫码登录',
    'CAPTCHA_REQUIRED': '小红书要安全验证：点「!」打开验证窗口',
    'ACCOUNT_RISK': '小红书把读取号跳到了登录/安全页：同步已全部暂停，点「!」处理',
    'RISK_HOLD': '风控暂停中：所有用号的同步都停了，点「!」处理后自动恢复',
}


def account_problem(code, detail=''):
    """任何环节（同步 / 附件下载 / 附件补查 / 登录检查）撞见掉登录或安全验证，都记到目录页那个「!」上。

    0927：以前只有同步收藏会写这里，下载附件时掉登录只发手机提醒、目录页照样显示正常。
    """
    previous = load()
    if previous.get('state') == 'blocked' and previous.get('code') == code:
        return previous
    message = _ACCOUNT_MESSAGES.get(code, _ACCOUNT_MESSAGES['CAPTCHA_REQUIRED'])
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
