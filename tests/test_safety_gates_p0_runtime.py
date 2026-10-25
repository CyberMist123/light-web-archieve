"""1024 第 1 波 p0-runtime：安全闸门查不出来就关（不碰号）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from link_brain import accounts, night_captcha, problems, repair, storage

from test_night_captcha_1011 import T0, Clock, FakeReader, _hold, night  # noqa: F401 - night 是 fixture


def _old_download_problem():
    old = (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="seconds")
    problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "超时", item_id="xhs-a")
    rows = problems._read_rows()
    rows[0]["ts"] = old
    problems.path().write_text(json.dumps(rows[0], ensure_ascii=False) + "\n", encoding="utf-8")


def test_repair_skips_account_steps_when_risk_state_unreadable(monkeypatch):
    _old_download_problem()

    def boom():
        raise OSError("熔断文件读不出来")
    monkeypatch.setattr(accounts, "risk_hold", boom)
    called = []
    out = repair.run(auto=True, execute=lambda argv, t: called.append(argv) or (0, "", False))
    assert called == [], "查不到风控状态就当有风控，碰号的修复不跑"
    assert out["results"][0]["status"] == "skipped"


def test_night_probe_not_sent_when_marker_cannot_be_written(night, monkeypatch):  # noqa: F811
    fake = FakeReader(monkeypatch, _hold())
    real = storage.write_json

    def no_write(path, payload):
        if path == night_captcha.state_path():
            raise PermissionError(13, "写不进去")
        return real(path, payload)
    monkeypatch.setattr(storage, "write_json", no_write)
    out = night_captcha.recover(now_fn=Clock(T0 + timedelta(minutes=46)))
    assert fake.probes() == [], "「今晚查过」写不进去就不查（不然一晚可能查两次）"
    assert out["exit"] != 0 and "写不进去" in out["message"]


def test_night_probe_marker_written_before_probe(night, monkeypatch):  # noqa: F811
    fake = FakeReader(monkeypatch, _hold())
    seen = []
    real = fake.__call__

    def spy(method, route, **kw):
        if route == "/api/v1/risk/probe":
            seen.append(night_captcha.night(night_captcha.night_key(T0 + timedelta(minutes=46))))
        return real(method, route, **kw)
    monkeypatch.setattr(accounts, "api", spy)
    assert night_captcha.recover(now_fn=Clock(T0 + timedelta(minutes=46)))["exit"] == 0
    assert seen and seen[0].get("probing_at"), "发自查之前就要记下「今晚正在查」"


def test_night_probe_busy_releases_marker(night, monkeypatch):  # noqa: F811
    fake = FakeReader(monkeypatch, _hold(), probe="busy")
    now = T0 + timedelta(minutes=46)
    assert night_captcha.recover(now_fn=Clock(now))["result"] == "busy"
    fake.probe = "cleared"
    assert night_captcha.recover(now_fn=Clock(now + timedelta(minutes=5)))["result"] == "cleared", "没查成的不算查过"
    assert len(fake.probes()) == 2
