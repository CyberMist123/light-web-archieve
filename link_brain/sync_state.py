"""Last sync outcome for the local UI, independent of notification integrations."""
import os
import sys
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


INTERRUPTED_MESSAGE = '上次同步中途被打断（Obsidian 关闭或进程被结束），已抓的都在；再点一次同步会接着来'


def _read_raw():
    try:
        status = storage.read_json(path())
    except (OSError, ValueError):
        return {}
    return status if isinstance(status, dict) else {}


def _interrupted(status):
    return {**status, 'state': 'failed', 'code': 'INTERRUPTED', 'message': INTERRUPTED_MESSAGE,
            'detail': status.get('progress', '')}


def load():
    """sync-status.json，读的时候核一下进程还在不在（只读，不落盘）。

    0929：同步进程被打断（关 Obsidian / 结束进程）时来不及写结果，状态会永远停在「正在同步」。
    第 4 批：「pid 还活着」只在 Python 这一份判（CONVENTIONS §3 迁移点），页面不再自己 process.kill(pid, 0)；
    页面拿到的是 problems-summary.json 的 sync 段（page_state），或调 `problems summary` 让 current() 落盘。"""
    status = _read_raw()
    if status.get('state') == 'running' and status.get('pid') and not _alive(status['pid']):
        status = _interrupted(status)
    return status


def current():
    """和 load() 一样，但发现「running + 进程已死」时把 INTERRUPTED 落盘进 sync-status.json（页面不用自判）、
    登记一条 TRANSIENT.INTERRUPTED（下次同步成功自动解决），并刷新 problems-summary.json。永不抛异常。"""
    raw = _read_raw()
    if not (raw.get('state') == 'running' and raw.get('pid') and not _alive(raw['pid'])):
        return load()
    status = {**_interrupted(raw), 'updated_at': datetime.now().astimezone().isoformat()}
    try:
        storage.write_json(path(), status)
    except OSError:
        return status
    _problem('sync.favorites', 'INTERRUPTED', status['message'] + (f"（停在：{status['detail']}）" if status.get('detail') else ''))
    _refresh_summary()
    return status


def page_state():
    """problems-summary.json 的 sync 段（只读）：修正后的状态 + 上次同步时间 + 本次新收几篇 + 还剩几篇逐晚处理。

    {state, code, message, label, hover, detail, updated_at, last_success, favorites, new, deferred, progress, running}
    label / hover 来自 problems 登记表（code 为空时是空串）；new / deferred 是这次同步才开始记的字段，旧文件没有就是 null。"""
    from . import problems
    status = load()
    code = str(status.get('code') or '')
    shown = problems.describe(code, status.get('detail') or status.get('message')) if code else {}
    return {
        'state': status.get('state') or '', 'code': code, 'message': status.get('message') or '',
        'label': shown.get('label', ''), 'hover': shown.get('hover', ''),
        'updated_at': status.get('updated_at'), 'last_success': status.get('last_success'),
        'favorites': status.get('favorites'), 'new': status.get('new'), 'deferred': status.get('deferred'),
        'detail': status.get('detail') or '', 'progress': status.get('progress') or '',
        'running': status.get('state') == 'running',
    }


def _problem(step, code, reason, **kw):
    """问题记录（fail-open：记录失败绝不影响 sync-status.json）。"""
    try:
        from . import problems
        return problems.report(step, code, reason, **kw)
    except Exception as exc:  # noqa: BLE001
        print(f'[sync_state] 问题记录没写上（{type(exc).__name__}: {exc}）', file=sys.stderr)
        return None


def _resolve(step, code=None):
    try:
        from . import problems
        return problems.resolve(step, None, code)
    except Exception:  # noqa: BLE001
        return 0


def _refresh_summary():
    try:
        from . import problems
        problems.write_summary()
    except Exception:  # noqa: BLE001
        pass


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
            _refresh_summary()
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
    finished = state == 'finished'
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
    if finished:
        # 第 4 批：目录页顶部的同步概况要「本次新收几篇 / 还剩几篇逐晚处理」（新增字段，旧字段不动）
        status['new'] = len(payload.get('fetched_new') or [])
        status['deferred'] = int(payload.get('deferred') or 0)
    if state == 'running':
        status['pid'] = os.getpid()
        if previous.get('state') != 'running':
            status['before'] = {k: v for k, v in previous.items() if k != 'before'}
        elif isinstance(previous.get('before'), dict):
            status['before'] = previous['before']
    storage.write_json(path(), status)
    _record_problems(status)
    _refresh_summary()
    return status


def _record_problems(status):
    """这次同步的结论进问题记录（CONVENTIONS §2 迁移点）：sync-status.json 照写，这里只多登记 / 解决一次。

    - ready → 收藏同步和账号的问题全部标已解决（读到了收藏 = 号和服务都好着）；
    - blocked → 账号类（掉登录 / 验证 / 风控 / 熔断 / 登错号）NEEDS_HUMAN 记在 login；服务类 TRANSIENT 记在 sync.favorites；
    - failed → FAVORITES_SUSPICIOUS（读取服务只读到一截，下次自动再读）TRANSIENT；TOO_MANY_FAILURES / 没码的失败（部分收藏没抓到、
      同步进程出错）TRANSIENT：下次同步自动再来，连续 3 天还这样才升级推送。"""
    from . import problems
    state, code = status.get('state'), str(status.get('code') or '')
    if state == 'running':
        return
    if state == 'ready':
        if code != 'RATE_LIMITED':
            _resolve('sync.favorites')
            _resolve('login')
        return
    reason = '；'.join(x for x in (str(status.get('message') or ''), str(status.get('detail') or '')) if x)
    if state == 'blocked' or code in problems.ACCOUNT_CODES:
        problems.report_blocked('sync.favorites', code, reason, service=status.get('account') != 'xhs')
        return
    try:
        problems.normalize(code or 'TRANSIENT.SYNC_FAILED')
    except problems.BadCode:
        code = ''
    _problem('sync.favorites', code or 'TRANSIENT.SYNC_FAILED', reason or '同步没做完')


def running_elsewhere() -> bool:
    """别的活进程正在同步（状态 running 且 pid 活着、不是本进程）：这时别去改状态文件。"""
    status = load()
    return status.get('state') == 'running' and status.get('pid') not in (None, os.getpid())


ACCOUNT_CODES = ('NOT_LOGGED_IN', 'CAPTCHA_REQUIRED', 'ACCOUNT_RISK', 'RISK_HOLD')


def account_message(code):
    """账号类状态的那句话：唯一文案源是 problems.STATE_REGISTRY（第 4 批，三处合一；页面经 catalog-data 的
    state_registry 读同一份）。未知码按「要安全验证」说。"""
    from . import problems
    try:
        shown = problems.describe(code if code in ACCOUNT_CODES else 'CAPTCHA_REQUIRED')
    except Exception:  # noqa: BLE001
        return '小红书账号要处理：点目录页顶部的问题入口检查'
    return shown['hover']


def account_problem(code, detail=''):
    """任何环节（同步 / 附件下载 / 附件补查 / 登录检查）撞见掉登录或安全验证，都记到目录页顶部的问题入口上（第 4 批：「!」并进了问题入口）。

    0927：以前只有同步收藏会写这里，下载附件时掉登录只发手机提醒、目录页照样显示正常。
    """
    previous = load()
    if previous.get('state') == 'blocked' and previous.get('code') == code:
        return previous
    message = account_message(code)
    status = {**previous, 'state': 'blocked', 'message': message, 'account': 'xhs', 'code': code,
              'detail': str(detail)[:300], 'updated_at': datetime.now().astimezone().isoformat()}
    storage.write_json(path(), status)
    try:
        from . import problems
        problems.report_blocked('login', code, f'{message}（{str(detail)[:150]}）' if detail else message)
    except Exception:  # noqa: BLE001
        pass
    _refresh_summary()
    return status


def account_ok():
    """登录恢复了：只清掉『账号类』的「!」，别的失败原样留着。"""
    previous = load()
    # 问题记录：登录检查通过 = 掉登录 / 要验证 / 风控跳页这几件事都好了（登错号要等下次同步认号才算好）
    resolved = sum(_resolve('login', c) for c in (*ACCOUNT_CODES, 'ACCOUNT_BLOCKED', 'NOT_INSTALLED'))
    if previous.get('state') == 'blocked' and previous.get('code') in ACCOUNT_CODES:
        status = {**previous, 'state': 'ready', 'message': '已重新登录，下次同步照常进行', 'code': '', 'detail': '',
                  'updated_at': datetime.now().astimezone().isoformat()}
        storage.write_json(path(), status)
        _refresh_summary()
        return status
    if resolved:
        _refresh_summary()
    return previous
