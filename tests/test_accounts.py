import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from link_brain import accounts, attachments, cli, doctor


@pytest.fixture
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'user')
    monkeypatch.setenv('LINK_BRAIN_HOME', str(tmp_path / 'runtime'))
    monkeypatch.setenv('LINK_BRAIN_VAULT', str(tmp_path / 'vault'))
    monkeypatch.setenv('LINK_BRAIN_MODELS_DIR', str(tmp_path / 'models'))
    for name in ['DASHSCOPE_API_KEY', 'LINK_BRAIN_AB_PROFILE_PREFS', 'XHS_PROFILE_DIR',
                 'XHS_FAV_PROFILE', 'LINK_BRAIN_FAVDUMP', 'LINK_BRAIN_FAV_LOGIN']:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(accounts.shutil, 'which', lambda _: None)
    def disconnected(*args, **kw):
        raise httpx.ConnectError('connection refused')
    monkeypatch.setattr(accounts, 'api', disconnected)
    return tmp_path


def test_clean_environment_optional_missing_is_not_core_failure(clean):
    data = doctor.diagnose()
    rows = {r['id']: r for r in data['checks']}
    assert data['core_ready'] and not data['xhs_ready']
    assert rows['xhs']['state'] == 'disconnected'
    for key in ('favorites', 'attachments', 'ai'):
        assert rows[key]['state'] == 'unconfigured'
        assert rows[key]['optional'] and rows[key]['next_step']
    assert not (clean / 'runtime').exists()  # doctor does not write settings


def test_login_state_is_not_inferred_from_connection_failure(clean, monkeypatch):
    accounts.save({'xhs_authenticated': True})
    assert accounts.xhs_status()['state'] == 'disconnected'
    monkeypatch.setattr(accounts, 'api', lambda *a, **k: {'is_logged_in': False})
    assert accounts.xhs_status()['state'] == 'expired'
    monkeypatch.setattr(accounts, 'api', lambda *a, **k: {})
    assert accounts.xhs_status()['state'] == 'unknown'


def test_already_logged_in_never_opens_qr_or_clears_session(clean, monkeypatch):
    calls = []
    def api(method, route, **kw):
        calls.append((method, route))
        return {'is_logged_in': True}
    monkeypatch.setattr(accounts, 'api', api)
    assert accounts.login_xhs()['state'] == 'ready'
    assert calls == [('GET', '/api/v1/login/status')]


def test_scan_success_then_doctor_ready(clean, monkeypatch):
    statuses = iter([False, True, True])
    calls = []
    def api(method, route, **kw):
        calls.append(route)
        if route.endswith('qrcode'):
            return {'img': 'data:image/png;base64,AA==', 'is_logged_in': False}
        return {'is_logged_in': next(statuses)}
    monkeypatch.setattr(accounts, 'api', api)
    monkeypatch.setattr(accounts.time, 'sleep', lambda _: None)
    opened = []
    monkeypatch.setattr(accounts.webbrowser, 'open', lambda uri: opened.append(uri) or True)
    assert accounts.login_xhs()['state'] == 'ready'
    assert opened and calls.count('/api/v1/login/qrcode') == 1
    assert accounts.config()['xhs_authenticated']
    assert doctor.diagnose()['xhs_ready']
    page = (accounts.home() / 'login.html').read_text('utf-8')
    assert '已登录' in page and '<img' not in page


def test_scan_keeps_waiting_after_reader_500(clean, monkeypatch):
    statuses = iter([False, 'error', True])
    def api(method, route, **kw):
        if route.endswith('qrcode'):
            return {'img': 'data:image/png;base64,AA=='}
        state = next(statuses)
        if state == 'error':
            raise httpx.HTTPStatusError('browser busy', request=httpx.Request('GET', 'http://localhost'),
                                        response=httpx.Response(500))
        return {'is_logged_in': state}
    monkeypatch.setattr(accounts, 'api', api)
    monkeypatch.setattr(accounts.time, 'sleep', lambda _: None)
    monkeypatch.setattr(accounts.webbrowser, 'open', lambda _: True)
    assert accounts.login_xhs()['state'] == 'ready'


def test_timeout_is_actionable(clean, monkeypatch):
    monkeypatch.setattr(accounts, 'api', lambda method, route, **kw:
                        {'img': 'data:image/png;base64,AA=='} if route.endswith('qrcode') else {'is_logged_in': False})
    monkeypatch.setattr(accounts.webbrowser, 'open', lambda _: True)
    result = accounts.login_xhs(timeout=0)
    assert result['state'] != 'ready' and '二维码' in result['next_step']


def test_missing_reader_returns_install_instruction(clean, capsys):
    assert cli.main(['login', '--json']) == 1
    data = json.loads(capsys.readouterr().out)
    assert 'login --install' in data['next_step']


def test_favorites_empty_account_is_valid(clean, monkeypatch):
    monkeypatch.setattr(accounts, 'fav_exe', lambda: 'favdump')
    accounts.fav_profile().mkdir(parents=True)
    monkeypatch.setattr(accounts, 'run_component', lambda *a, **kw:
                        subprocess.CompletedProcess([], 0, b'{"items":[]}', b''))
    assert accounts.favorite_status()['state'] == 'ready'


def test_favorites_error_does_not_claim_logged_out(clean, monkeypatch):
    monkeypatch.setattr(accounts, 'fav_exe', lambda: 'favdump')
    accounts.fav_profile().mkdir(parents=True)
    monkeypatch.setattr(accounts, 'run_component', lambda *a, **kw:
                        subprocess.CompletedProcess([], 1, b'', b'profile in use'))
    assert accounts.favorite_status()['state'] == 'unknown'


def test_favorites_login_probe_error_is_not_expiry(clean, monkeypatch):
    monkeypatch.setattr(accounts, 'fav_exe', lambda: 'favdump')
    accounts.fav_profile().mkdir(parents=True)
    monkeypatch.setattr(accounts, 'run_component', lambda *a, **kw:
                        subprocess.CompletedProcess([], 3, b'', b'login check failed: navigation timeout'))
    assert accounts.favorite_status()['state'] == 'unknown'


def test_attachment_login_polls_same_page_and_closes_only_own_session(clean, monkeypatch):
    assert '\n' not in accounts.USER_STATE_JS  # .cmd truncates multiline expressions
    monkeypatch.setattr(attachments, '_agent_browser_exe', lambda: 'agent-browser')
    monkeypatch.setattr(accounts.time, 'sleep', lambda _: None)
    calls = []
    def ab(args, **kw):
        calls.append(args)
        return 0, json.dumps(json.dumps({'state': 'ready'}))
    monkeypatch.setattr(attachments, '_ab', ab)
    assert accounts.attachment_check(login=True)['state'] == 'ready'
    assert sum('location.href' in ' '.join(c) for c in calls) == 1
    assert calls[-1] == ['close']
    assert all('--all' not in c for c in calls)


@pytest.mark.parametrize('output', ['not ready', '{"state":"not_ready"}', 'error: already in use'])
def test_attachment_unknown_output_is_never_ready(output):
    assert accounts.browser_state(output) == 'unknown'


def test_obsidian_actual_host_config_and_js_flag(clean):
    obs = clean / 'host' / '.obsidian'
    plugin = obs / 'plugins' / 'link-brain-actions'
    plugin.mkdir(parents=True)
    for name in ('main.js', 'manifest.json', 'library-ui.js'):
        (plugin / name).touch()
    (obs / 'community-plugins.json').write_text('["link-brain-actions","dataview"]')
    dv = obs / 'plugins' / 'dataview'
    dv.mkdir()
    (dv / 'data.json').write_text('{"enableDataviewJs":true}')
    rows = {r['id']: r for r in doctor.diagnose(obsidian_dir=str(obs))['checks']}
    assert rows['obsidian']['state'] == rows['dataview']['state'] == 'ready'


def test_doctor_json_cli(clean, capsys):
    assert cli.main(['doctor', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['core_ready'] is True


def test_local_doctor_does_not_launch_account_checks(clean, monkeypatch):
    def must_not_run():
        raise AssertionError('local status must not wait for browsers')
    for name in ('xhs_status', 'favorite_status', 'attachment_check'):
        monkeypatch.setattr(accounts, name, must_not_run)
    data = doctor.diagnose(only='local')
    assert {r['id'] for r in data['checks']} == {'archive','obsidian','dataview','ai'}
