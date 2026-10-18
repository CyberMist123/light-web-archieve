"""小红书专辑（1019）：列表并进本地、挑该看的专辑、sync 随读随存 / 退出码、目录 albums 字段、album 过滤。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from link_brain import accounts, albums, ask_intent


NOW = datetime(2026, 10, 19, 12, 0).astimezone()


def _board(bid, name, total, **kw):
    return {"id": bid, "name": name, "total": total, "privacy": 0, "desc": "", **kw}


def test_merge_list_adds_updates_and_only_removes_when_complete():
    data = {"boards": {"old": {"name": "旧", "total": 1, "notes": ["n1"]}, "keep": {"name": "课", "total": 1, "notes": ["n2"]}}}
    got = albums.merge_list(data, {"boards": [_board("keep", "课程", 2), _board("new", "吃", 3)], "expected": 3, "partial": True}, NOW)
    assert got == {"listed": 2, "added": 1, "removed": 0} and "old" in data["boards"]       # 没读全：不删
    assert data["boards"]["keep"]["name"] == "课程" and data["boards"]["keep"]["notes"] == ["n2"]
    got = albums.merge_list(data, {"boards": [_board("keep", "课程", 2), _board("new", "吃", 3)], "partial": False}, NOW)
    assert got["removed"] == 1 and "old" not in data["boards"]


def test_due_boards_order():
    old = (NOW - timedelta(days=9)).isoformat()
    fresh = (NOW - timedelta(days=1)).isoformat()
    data = {"boards": {
        "stale": {"total": 2, "checked_at": old, "checked_total": 2},
        "fresh": {"total": 2, "checked_at": fresh, "checked_total": 2},
        "grew": {"total": 5, "checked_at": fresh, "checked_total": 4},
        "never": {"total": 1},
        "empty": {"total": 0},
        "part": {"total": 3, "checked_at": fresh, "checked_total": 3, "partial": True},
    }}
    assert albums.due_boards(data, NOW, 10) == [("never", "没看过"), ("grew", "篇数变了"), ("part", "上次没读全"),
                                                 ("stale", "超过 7 天没看")]
    assert len(albums.due_boards(data, NOW, 2)) == 2


@pytest.fixture
def reader(monkeypatch):
    calls = []
    lists = {"boards": [_board("b1", "温暖治愈", 2), _board("b2", "课", 1)], "expected": 2, "partial": False}
    notes = {"b1": {"board": {"name": "温暖治愈", "total": 2}, "notes": [{"note_id": "n1"}, {"note_id": "n2"}, {"note_id": "n1"}]},
             "b2": {"board": {"name": "课", "total": 1}, "notes": [{"note_id": "n2"}]}}

    def api(method, route, **kw):
        calls.append(route)
        if route == "/api/v1/boards":
            return lists
        bid = route.split("board_id=")[1]
        if isinstance(notes.get(bid), Exception):
            raise notes[bid]
        return notes[bid]
    monkeypatch.setattr(accounts, "api", api)
    monkeypatch.setattr(accounts, "pace", lambda *a, **k: 0.0)
    monkeypatch.setattr(accounts, "check_risk_hold", lambda: None)
    return calls, notes


def test_sync_lists_then_reads_boards_and_maps_notes(reader):
    calls, _ = reader
    code, out = albums.sync(max_boards=5, sleep=lambda s: None)
    assert code == 0 and calls[0] == "/api/v1/boards" and len(calls) == 3
    assert out["listed"]["added"] == 2 and [b["notes"] for b in out["boards"]] == [2, 1]
    assert albums.note_albums() == {"n1": ["温暖治愈"], "n2": ["温暖治愈", "课"]}
    # 同一天再跑：不再读列表，专辑都看过且没变 → 什么都不开
    calls.clear()
    code, out = albums.sync(max_boards=5, sleep=lambda s: None)
    assert code == 0 and calls == [] and out["listed"] is None


def test_sync_stops_on_risk_and_keeps_what_it_read(reader):
    calls, notes = reader
    notes["b2"] = accounts.ReaderError("CAPTCHA_REQUIRED", "要验证")
    code, out = albums.sync(max_boards=5, sleep=lambda s: None)
    assert code == 5 and out["stopped"].startswith("CAPTCHA_REQUIRED")
    assert albums.note_albums() == {"n1": ["温暖治愈"], "n2": ["温暖治愈"]}     # b1 读到的已存


def test_sync_rate_limited_is_quiet(reader):
    _, notes = reader
    notes["b1"] = accounts.ReaderError(accounts.RATE_LIMIT_CODE, "访问频繁")
    code, _ = albums.sync(max_boards=1, sleep=lambda s: None)
    assert code == 0


def test_album_filter_exact_then_contains():
    items = [{"id": "a", "albums": ["温暖治愈和笑话"]}, {"id": "b", "albums": ["课"]}, {"id": "c"}]
    assert [i["id"] for i in ask_intent.apply_strict_filters(items, {"album": "课"})] == ["b"]
    assert [i["id"] for i in ask_intent.apply_strict_filters(items, {"album": "治愈"})] == ["a"]
    assert ask_intent.apply_strict_filters(items, {"album": "没有"}) == []
