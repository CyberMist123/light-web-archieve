import json
from datetime import datetime, timedelta

from link_brain.sources.xiaohongshu import accounts, comment_fill


def test_reply_cooldown_survives_empty_click_log_and_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "profile_dir", lambda: tmp_path)
    now = datetime.now().astimezone()
    until = now + timedelta(hours=72)
    (tmp_path / "sub-comments-hold.json").write_text(json.dumps({"until": until.isoformat()}))
    assert comment_fill.sub_quota(now) == (0, until)
    assert comment_fill.sub_cooldown(now) == until
    assert comment_fill.sub_quota(until) == (comment_fill.SUB_PER_HOUR, None)


def test_no_reply_hold_preserves_existing_hourly_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "profile_dir", lambda: tmp_path)
    now = datetime.now().astimezone()
    (tmp_path / "sub-expand.json").write_text(json.dumps({"clicks": [now.isoformat()]}))
    assert comment_fill.sub_quota(now) == (comment_fill.SUB_PER_HOUR - 1, None)


def test_plugin_status_shows_reply_wait_without_login_probe(monkeypatch):
    until = (datetime.now().astimezone() + timedelta(hours=72)).isoformat()
    session = {"risk_hold": None, "sub_comments_until": until}
    monkeypatch.setattr(accounts, "api", lambda *a, **kw: session)
    result, state = accounts.status_report(deep=False, launch=False)
    assert state == "unknown"
    assert result["message"] == "楼中楼自动恢复中"
    assert not result.get("action")
    assert accounts.sub_cooldown_row({**session, "logged_in": False}) is None
    assert accounts.sub_cooldown_row({**session, "risk_hold": {"code": "CAPTCHA_REQUIRED"}}) is None
