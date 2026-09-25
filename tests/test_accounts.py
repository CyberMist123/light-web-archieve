"""一个号一个读取服务（2026-09-25）：状态、扫码、报错→解决方案、收藏/附件停车。"""
import json
from pathlib import Path

import httpx
import pytest

from link_brain import accounts, attachments, doctor, favorites
from link_brain.adapters import xiaohongshu as xhs


@pytest.fixture
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'user')
    monkeypatch.setenv('LINK_BRAIN_HOME', str(tmp_path / 'runtime'))
    monkeypatch.setenv('LINK_BRAIN_VAULT', str(tmp_path / 'vault'))
    monkeypatch.setenv('LINK_BRAIN_MODELS_DIR', str(tmp_path / 'models'))
    for name in ['DASHSCOPE_API_KEY', 'XHS_PROFILE_DIR', 'LINK_BRAIN_XHS_EXE', 'LINK_BRAIN_XHS_ENDPOINT']:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(accounts.shutil, 'which', lambda _: None)
    monkeypatch.setattr(accounts.time, 'sleep', lambda _: None)

    def refused(*a, **kw):
        raise httpx.ConnectError('connection refused')
    monkeypatch.setattr(accounts.httpx, 'request', refused)
    return tmp_path


class FakeReader:
    """按路由应答的假读取服务；记下调用顺序。"""

    def __init__(self, monkeypatch, routes):
        self.calls, self.routes = [], routes
        monkeypatch.setattr(accounts, 'api', self)

    def __call__(self, method, route, **kw):
        self.calls.append(route)
        value = self.routes[route]
        if callable(value):
            value = value()
        if isinstance(value, Exception):
            raise value
        return value


def test_clean_environment_reports_missing_component_not_core_failure(clean):
    data = doctor.diagnose()
    rows = {r['id']: r for r in data['checks']}
    assert data['core_ready'] and not data['xhs_ready']
    assert rows['xhs']['state'] == 'unconfigured' and rows['xhs']['next_step']
    assert 'favorites' not in rows and 'attachments' not in rows  # 一个号一行
    assert not (clean / 'runtime').exists()  # doctor 不写配置


def test_api_maps_error_payload_to_code(clean, monkeypatch):
    def reply(method, url, **kw):
        return httpx.Response(423, json={'error': '要验证', 'code': 'CAPTCHA_REQUIRED', 'details': 'x'})
    monkeypatch.setattr(accounts.httpx, 'request', reply)
    with pytest.raises(accounts.ReaderError) as err:
        accounts.api('GET', '/api/v1/favorites')
    assert err.value.code == 'CAPTCHA_REQUIRED' and err.value.needs_human


def test_ready_saves_nickname(clean, monkeypatch):
    FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'idle'},
                             '/api/v1/login/status': {'is_logged_in': True, 'username': 'momo', 'user_id': 'u1'}})
    r = accounts.xhs_status()
    assert r['state'] == 'ready' and r['account'] == 'momo'
    assert accounts.config()['user_id'] == 'u1'


def test_logged_out_after_success_is_expired_with_login_action(clean, monkeypatch):
    accounts.save({'nickname': 'momo'})
    FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'idle'},
                             '/api/v1/login/status': {'is_logged_in': False}})
    r = accounts.xhs_status()
    assert (r['state'], r['action']) == ('expired', 'login')


@pytest.mark.parametrize('code,state,action', [
    ('CAPTCHA_REQUIRED', 'captcha', 'verify'),
    ('RATE_LIMITED', 'busy', 'wait'),
    ('DISCONNECTED', 'disconnected', 'retry'),
])
def test_every_error_has_a_solution(clean, monkeypatch, code, state, action):
    FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'idle'},
                             '/api/v1/login/status': accounts.ReaderError(code)})
    r = accounts.xhs_status()
    assert (r['state'], r['action']) == (state, action) and r['next_step']


def test_status_never_touches_browser_while_qr_pending(clean, monkeypatch):
    fake = FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'waiting'}})
    assert accounts.xhs_status()['state'] == 'busy'
    assert fake.calls == ['/api/v1/login/session']


def test_login_polls_only_memory_state_until_success(clean, monkeypatch):
    sessions = iter([{'state': 'idle'}, {'state': 'waiting'}, {'state': 'waiting'},
                     {'state': 'success', 'nickname': 'momo', 'user_id': 'u1'}])
    fake = FakeReader(monkeypatch, {'/api/v1/login/session': lambda: next(sessions),
                                    '/api/v1/login/qrcode': {'img': 'data:image/png;base64,AAAA'}})
    opened = []
    monkeypatch.setattr(accounts.webbrowser, 'open', lambda uri: opened.append(uri) or True)
    r = accounts.login(timeout=60)
    assert r['state'] == 'ready' and r['message'] == '已登录：momo'
    assert '/api/v1/login/status' not in fake.calls  # 出码后绝不碰会导航的接口
    assert opened and '已登录' in (clean / 'runtime' / 'login.html').read_text('utf-8')


def test_login_timeout_says_qr_expired(clean, monkeypatch):
    sessions = iter([{'state': 'idle'}, {'state': 'timeout'}])
    FakeReader(monkeypatch, {'/api/v1/login/session': lambda: next(sessions),
                             '/api/v1/login/qrcode': {'img': 'data:image/png;base64,AAAA'}})
    monkeypatch.setattr(accounts.webbrowser, 'open', lambda uri: True)
    r = accounts.login(timeout=60)
    assert r['message'] == '二维码已过期' and r['action'] == 'login'


def test_login_reports_account_switch(clean, monkeypatch):
    accounts.save({'user_id': 'old'})
    sessions = iter([{'state': 'idle'}, {'state': 'success', 'nickname': 'b', 'user_id': 'new'}])
    FakeReader(monkeypatch, {'/api/v1/login/session': lambda: next(sessions),
                             '/api/v1/login/qrcode': {'img': 'data:image/png;base64,AAAA'}})
    monkeypatch.setattr(accounts.webbrowser, 'open', lambda uri: True)
    assert '已切换账号' in accounts.login(timeout=60)['next_step']


def test_favorites_captcha_stops_without_retry(clean, monkeypatch):
    fake = FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'idle'},
                                    '/api/v1/favorites': accounts.ReaderError('CAPTCHA_REQUIRED')})
    alerts = []
    monkeypatch.setattr(favorites.alert_mod, 'alert', lambda *a, **k: alerts.append(a))
    out = favorites.sync_favorites()
    assert out['code'] == 'CAPTCHA_REQUIRED' and out['items'][0]['status'] == 'blocked'
    assert fake.calls.count('/api/v1/favorites') == 1 and len(alerts) == 1


def test_favorites_rate_limited_is_quiet(clean, monkeypatch):
    FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'idle'},
                             '/api/v1/favorites': accounts.ReaderError('RATE_LIMITED')})
    alerts = []
    monkeypatch.setattr(favorites.alert_mod, 'alert', lambda *a, **k: alerts.append(a))
    assert favorites.sync_favorites()['code'] == 'RATE_LIMITED' and not alerts


def test_favorites_success_returns_items(clean, monkeypatch):
    FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'idle'},
                             '/api/v1/favorites': {'nickname': 'momo', 'items': [{'note_id': 'a'}, {'note_id': 'b'}]}})
    assert [x['note_id'] for x in favorites.fetch_favorites(limit=1)] == ['a']


def test_attachment_account_problem_is_needs_human(clean, monkeypatch, tmp_path):
    FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'idle'},
                             '/api/v1/attachments/download': accounts.ReaderError('NOT_LOGGED_IN')})
    with pytest.raises(attachments.AttachmentNeedsHuman) as err:
        attachments.fetch_bytes(doc_id='d', note_id='n', xsec_token='t', file_name='f.pdf', staging_dir=tmp_path / 's')
    assert err.value.code == 'NOT_LOGGED_IN' and '扫码登录' in str(err.value)


def test_attachment_download_returns_file(clean, monkeypatch, tmp_path):
    f = tmp_path / 's' / 'f.pdf'
    f.parent.mkdir(parents=True)
    f.write_bytes(b'%PDF')
    FakeReader(monkeypatch, {'/api/v1/login/session': {'state': 'idle'},
                             '/api/v1/attachments/download': {'path': str(f), 'bytes': 4}})
    assert attachments.fetch_bytes(doc_id='d', note_id='n', xsec_token='t', file_name='f.pdf',
                                   staging_dir=tmp_path / 's') == f


def test_mcp_call_surfaces_needs_human_code(clean, monkeypatch):
    FakeReader(monkeypatch, {'/api/v1/login/session': accounts.ReaderError('NOT_INSTALLED')})
    with pytest.raises(xhs.AccountBlockedError) as err:
        xhs.call_tool('get_feed_detail', {})
    assert err.value.code == 'NOT_INSTALLED'


def test_json_output_is_one_object(clean, monkeypatch, capsys):
    FakeReader(monkeypatch, {'/api/v1/login/session': accounts.ReaderError('CAPTCHA_REQUIRED')})
    from types import SimpleNamespace
    code = accounts.run_login(SimpleNamespace(verify=False, status=True, force=False, timeout=5, json=True))
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out['action'] == 'verify'
