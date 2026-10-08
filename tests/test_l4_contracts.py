import json
from pathlib import Path

import pytest

from link_brain import ai_config, providers, storage, sync_state
from link_brain.setup import estimate


FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('kind,value,expected', json.loads((FIXTURES / 'endpoint_cases.json').read_text(encoding='utf-8')))
def test_endpoint_contract(kind, value, expected):
    assert providers.normalize_endpoint(kind, value) == expected


@pytest.mark.parametrize('case', json.loads((FIXTURES / 'with_model_cases.json').read_text(encoding='utf-8')))
def test_model_contract(case):
    settings = {'textAI': {'mode': 'http', 'endpoint': 'https://api.deepseek.com/chat/completions',
                           'model': 'sample-text', 'keyFile': 'synthetic-secrets.json', 'keyField': 'ds'},
                'models': [{'name': 'selected', **case['entry']}], 'activeModel': 'selected'}
    before = json.dumps(settings)
    chosen = ai_config.with_model(settings, 'selected')
    assert ai_config.endpoint_host(chosen['textAI']['endpoint']) == case['host']
    assert chosen['textAI']['model'] == case['model']
    assert bool(chosen['textAI'].get('keyFile')) == case['keyFile']
    assert bool(chosen.get('modelFallback')) == case.get('fallback', False)
    assert json.dumps(settings) == before


def test_progress_counts_and_manual_stop(monkeypatch):
    monkeypatch.setattr(sync_state, '_alive', lambda pid: False)
    monkeypatch.setattr(sync_state, '_refresh_summary', lambda: None)
    sync_state.progress_log().parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(sync_state.path(), {'state': 'running', 'pid': 999999})
    sync_state.progress('处理中', done=2, total=5)
    status = sync_state.page_state()
    assert (status['done'], status['total'], status['remaining']) == (2, 5, 3)
    assert sync_state.stopped_by_user()
    assert storage.read_json(sync_state.path())['code'] == ''
    assert not sync_state.stopped_by_user()


def test_manual_stop_does_not_change_live_process(monkeypatch):
    monkeypatch.setattr(sync_state, '_alive', lambda pid: True)
    storage.write_json(sync_state.path(), {'state': 'running', 'pid': 999999})
    assert not sync_state.stopped_by_user()
    assert storage.read_json(sync_state.path())['state'] == 'running'


def test_estimate_connection_fields():
    result = estimate.estimate()
    for item in result['items']:
        assert 'api_model' in item and 'endpoint' in item
        for alternative in item['alternatives']:
            assert 'api_model' in alternative and 'endpoint' in alternative
