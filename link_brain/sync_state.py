"""Last sync outcome for the local UI, independent of notification integrations."""
from datetime import datetime

from . import storage


def path():
    return storage.archive_root() / 'sync-status.json'


def load():
    try:
        return storage.read_json(path())
    except (OSError, ValueError):
        return {}


def record(state, *, payload=None, message='', account=None):
    previous = load()
    now = datetime.now().astimezone().isoformat()
    payload = payload or {}
    errors = [item for item in payload.get('items', []) if item.get('status') in ('blocked', 'error')]
    if state == 'finished':
        state = 'blocked' if any(x.get('status') == 'blocked' for x in errors) else ('failed' if errors else 'ready')
        message = ('同步已暂停，需要恢复登录或连接' if state == 'blocked' else
                   '部分收藏未同步成功' if errors else '收藏同步完成')
        account = payload.get('login_account', errors[0].get('login_account') if errors else None)
    status = {'state': state, 'message': message, 'account': account, 'updated_at': now,
              'last_success': now if state == 'ready' else previous.get('last_success'),
              'favorites': payload.get('favorites'), 'synced': payload.get('synced'),
              'detail': errors[0].get('error', '') if errors else ''}
    storage.write_json(path(), status)
    return status
