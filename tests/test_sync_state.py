from link_brain import sync_state, favorites
from link_brain.adapters import xiaohongshu as xhs


def test_failed_sync_is_visible_without_notification_connector(monkeypatch):
    def expired(**kwargs):
        raise xhs.AccountBlockedError('登录已失效')
    monkeypatch.setattr(favorites, 'fetch_favorites', expired)
    monkeypatch.setattr(favorites.alert_mod, 'alert', lambda *a, **k: False)
    args = type('Args', (), {})()
    assert favorites.run(args) == 5
    status = sync_state.load()
    assert status['state'] == 'blocked'
    assert status['account'] == 'favorites'
    assert status['updated_at'] and status['last_success'] is None


def test_success_clears_failure_only_after_real_sync_result():
    sync_state.record('finished', payload={'login_account':'favorites','items':[{'status':'blocked','error':'登录失效'}]})
    assert sync_state.load()['state'] == 'blocked'
    sync_state.record('finished', payload={'favorites':2, 'synced':2, 'items':[{'status':'new'},{'status':'hit'}]})
    status = sync_state.load()
    assert status['state'] == 'ready' and status['last_success']
    sync_state.record('running', message='正在同步收藏')
    assert sync_state.load()['last_success'] == status['last_success']


def test_service_failure_does_not_request_relogin():
    sync_state.record('finished', payload={'login_account':None,'items':[{'status':'blocked','error':'连接失败'}]})
    assert sync_state.load()['account'] is None
