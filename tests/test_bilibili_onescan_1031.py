"""1031 她「给一个（扫码）就行」：电视端扫码成功的响应里带 cookie_info，网页端 cookie 一并存进 cookies.txt。"""
from __future__ import annotations

from link_brain.sources.bilibili import login, tvapi


def test_tv_login_also_saves_web_cookies(tmp_path, monkeypatch):
    p = tmp_path / "cookies.txt"
    monkeypatch.setattr(login, "cookies_path", lambda: p)
    data = {"access_token": "x", "cookie_info": {"cookies": [
        {"name": "SESSDATA", "value": "s1"}, {"name": "bili_jct", "value": "j1"}, {"name": "DedeUserID", "value": "42"},
        {"name": "other", "value": "nope"}]}}
    assert tvapi.save_web_cookies(data) is True
    text = p.read_text(encoding="utf-8")
    assert "SESSDATA\ts1" in text and "bili_jct\tj1" in text and "DedeUserID\t42" in text
    assert "nope" not in text


def test_no_cookie_info_leaves_web_alone(tmp_path, monkeypatch):
    p = tmp_path / "cookies.txt"
    monkeypatch.setattr(login, "cookies_path", lambda: p)
    assert tvapi.save_web_cookies({"access_token": "x"}) is False
    assert not p.exists()
