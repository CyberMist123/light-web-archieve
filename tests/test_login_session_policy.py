import importlib.util
from pathlib import Path
import sqlite3

import pytest
from link_brain.sources.xiaohongshu import accounts

spec = importlib.util.spec_from_file_location('cookie_cleanup', Path(__file__).parents[1] / 'reader' / 'clean_legacy_session_cookies.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def test_cleanup_backup_targeting_and_once(tmp_path):
    profile = tmp_path / 'profile'
    db = profile / 'Default' / 'Network' / 'Cookies'
    db.parent.mkdir(parents=True)
    updated = 13_000_000_000_000_000
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE cookies(host_key,name,path,expires_utc,last_update_utc,is_persistent,encrypted_value)')
        for name, domain, duration, persistent in [
            ('websectiga', '.xiaohongshu.com', cleanup.THIRTY_DAYS_US, 1),
            ('sec_poison_id', '.rednote.com', cleanup.THIRTY_DAYS_US, 1),
            ('acw_tc', 'www.rednote.com', cleanup.THIRTY_DAYS_US, 1),
            ('web_session', '.xiaohongshu.com', cleanup.THIRTY_DAYS_US, 1),
            ('id_token', '.rednote.com', cleanup.THIRTY_DAYS_US, 1),
            ('a1', '.xiaohongshu.com', cleanup.THIRTY_DAYS_US, 1),
            ('acw_tc', '.xiaohongshu.com', 60_000_000, 1),
            ('websectiga', '.xiaohongshu.com', 0, 0),
            ('websectiga', 'xiaohongshu.com.evil.test', cleanup.THIRTY_DAYS_US, 1),
        ]:
            conn.execute('INSERT INTO cookies VALUES(?,?,?,?,?,?,?)', (domain,name,'/',updated+duration,updated,persistent,b'synthetic-secret'))
    (profile / 'fingerprint-seed').write_text('synthetic-device')
    closed = lambda _: None
    preview = cleanup.clean(profile, closed=closed)
    assert preview['count'] == 3 and 'synthetic-secret' not in str(preview)
    assert not (profile / cleanup.MARKER).exists()
    result = cleanup.clean(profile, apply=True, closed=closed)
    assert result['deleted'] == 3 and 'synthetic-secret' not in str(result)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM cookies').fetchone()[0] == 6
    backup = Path(result['backup'])
    with sqlite3.connect(backup / 'Default/Network/Cookies') as conn:
        assert conn.execute('SELECT count(*) FROM cookies').fetchone()[0] == 9
    assert (profile / 'fingerprint-seed').read_text() == 'synthetic-device'
    assert cleanup.clean(profile, apply=True, closed=closed)['state'] == 'already_done'
    assert backup.exists()


def test_cleanup_refuses_running_browser(tmp_path):
    def running(_):
        raise RuntimeError('still running')
    with pytest.raises(RuntimeError):
        cleanup.clean(tmp_path, apply=True, closed=running)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('action', ['login', 'login_qr', 'logout'])
def test_risk_does_not_start_login_or_switch(monkeypatch, action):
    monkeypatch.setattr(accounts, 'ensure_reader', lambda: {})
    monkeypatch.setattr(accounts, '_hold_file', lambda: {'code': 'ACCOUNT_RISK'})
    monkeypatch.setattr(accounts, 'api', lambda *a, **k: pytest.fail('unexpected request'))
    with pytest.raises(accounts.ReaderError):
        getattr(accounts, action)()


def test_login_timeout_does_not_restart_or_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(accounts, 'ensure_reader', lambda: {})
    monkeypatch.setattr(accounts, '_hold_file', lambda: None)
    monkeypatch.setattr(accounts, 'restart_reader', lambda: pytest.fail('unexpected restart'))
    def timeout(*args, **kwargs):
        calls.append(args)
        raise accounts.ReaderError('TIMEOUT')
    monkeypatch.setattr(accounts, 'api', timeout)
    with pytest.raises(accounts.ReaderError):
        accounts.login()
    assert len(calls) == 1


def test_missing_identity_does_not_replace_account(monkeypatch):
    monkeypatch.setattr(accounts, 'save', lambda _: pytest.fail('saved unknown account'))
    with pytest.raises(accounts.ReaderError):
        accounts._finish_login({'state': 'success'})


def test_confirmed_other_account_is_saved(monkeypatch):
    saved = []
    monkeypatch.setattr(accounts, 'config', lambda: {'user_id': 'old'})
    monkeypatch.setattr(accounts, 'save', saved.append)
    out = accounts._finish_login({'user_id': 'new', 'nickname': 'Synthetic'})
    assert saved == [{'user_id': 'new', 'nickname': 'Synthetic'}]
    assert '已切换账号' in out['next_step']


def test_qr_existing_login_uses_confirmed_memory_identity(monkeypatch):
    monkeypatch.setattr(accounts, '_check_login_hold', lambda: None)
    monkeypatch.setattr(accounts, '_after_login', lambda s: s)
    calls = []
    def api(method, route, **kwargs):
        calls.append(route)
        if route.endswith('/qrcode'):
            return {'is_logged_in': True}
        assert route.endswith('/session')
        return {'logged_in': True, 'user_id': 'new'}
    monkeypatch.setattr(accounts, 'api', api)
    assert accounts.login_qr()['user_id'] == 'new'
    assert calls == ['/api/v1/login/qrcode', '/api/v1/login/session']


def test_failed_login_with_risk_does_not_offer_rescan(monkeypatch):
    monkeypatch.setattr(accounts, '_check_login_hold', lambda: None)
    monkeypatch.setattr(accounts.time, 'sleep', lambda _: None)
    monkeypatch.setattr(accounts, 'api', lambda *a, **k: {'state': 'failed', 'risk_hold': {'code': 'ACCOUNT_RISK', 'detail': 'synthetic'}})
    out = accounts.login()
    assert out['code'] in ('ACCOUNT_RISK', 'RISK_HOLD')
    assert out['message'] != '登录没有完成'
