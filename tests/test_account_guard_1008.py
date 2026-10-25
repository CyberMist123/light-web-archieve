"""1008 事故后加的本机碰号闸：account-guard.json 列了 allowed_roots 时，不在这些目录里的代码一律不许联系读取服务。"""
import json
from pathlib import Path

import pytest

from link_brain import accounts

PKG_ROOT = Path(__file__).resolve().parent.parent  # 仓库根；PR③ 后 accounts 深了一层，不能再按它的 __file__ 推


@pytest.fixture
def calls(monkeypatch):
    seen = []

    class Resp:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"ok": 1}}

    def fake_request(method, url, **kw):
        seen.append((method, url))
        return Resp()

    monkeypatch.setattr(accounts.httpx, "request", fake_request)
    return seen


def _guard(roots):
    accounts.home().mkdir(parents=True, exist_ok=True)
    (accounts.home() / accounts.GUARD_FILE).write_text(json.dumps({"allowed_roots": roots}), "utf-8")


def test_no_guard_file_means_no_guard(calls):
    assert accounts.api("GET", "/api/v1/login/session") == {"ok": 1}
    assert len(calls) == 1


def test_code_outside_allowed_roots_never_reaches_reader(calls, tmp_path):
    _guard([str(tmp_path / "somewhere-else")])
    with pytest.raises(accounts.ReaderError) as e:
        accounts.api("POST", "/api/v1/notes/related-file", body={"note_id": "x"})
    assert e.value.code == "DEV_COPY_BLOCKED"
    assert calls == []
    # ensure_reader 也拦在门口，不会去拉起读取服务
    with pytest.raises(accounts.ReaderError) as e2:
        accounts.ensure_reader(wait=0)
    assert e2.value.code == "DEV_COPY_BLOCKED"
    assert calls == []


def test_code_inside_allowed_root_passes(calls):
    _guard([str(PKG_ROOT)])
    assert accounts.api("GET", "/api/v1/login/session") == {"ok": 1}
    assert len(calls) == 1


def test_malformed_guard_file_blocks(calls):
    accounts.home().mkdir(parents=True, exist_ok=True)
    (accounts.home() / accounts.GUARD_FILE).write_text("{not json", "utf-8")
    with pytest.raises(accounts.ReaderError):
        accounts.api("GET", "/api/v1/login/session")
    assert calls == []
