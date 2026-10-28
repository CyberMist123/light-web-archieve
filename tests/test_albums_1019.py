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


def test_pick_boards_by_id_name_then_contains():
    data = {"boards": {"b1": {"name": "温暖治愈"}, "b2": {"name": "课"}, "b3": {"name": "课程"}}}
    assert albums.pick_boards(data, ["b2", "温暖", "课", "程", "没有", "b2"]) == (
        [("b2", "点名"), ("b1", "点名"), ("b3", "点名")], ["没有"])
    assert albums.pick_boards(data, ["治愈", "课"])[0] == [("b1", "点名"), ("b2", "点名")]
    assert albums.pick_boards({"boards": {"x": {"name": "AI 一"}, "y": {"name": "AI 二"}}}, ["AI"]) == ([], ["AI"])   # 撞多个


def test_sync_named_board_skips_list_and_reports_missing(reader, monkeypatch):
    calls, _ = reader
    albums.sync(max_boards=5, sleep=lambda s: None)                     # 先有本地列表
    calls.clear()
    monkeypatch.setattr(albums, "_library_ids", lambda: {"n1"})
    code, out = albums.sync(boards=["课"], sleep=lambda s: None)
    assert code == 0 and calls == ["/api/v1/boards/notes?board_id=b2"]  # 认得 → 不读列表、不按顺序挑
    assert out["boards"][0]["missing"] == 1 and out["boards"][0]["missing_ids"] == ["n2"]


def test_sync_named_unknown_board_reads_list_first(reader):
    calls, _ = reader
    code, out = albums.sync(boards=["课", "没这个"], sleep=lambda s: None)
    assert code == 0 and calls == ["/api/v1/boards", "/api/v1/boards/notes?board_id=b2"]
    assert out["unknown"] == ["没这个"]


def test_captcha_hold_pauses_clears_and_retries(monkeypatch):
    """1028 她：熔断 → 停 5 分钟 → 解除 → 接着跑；次数用完照旧停车；掉登录不自动接。"""
    from link_brain.sources.xiaohongshu import accounts as acc
    calls, slept = [], []
    state = {"fail": 1}

    def fake(method, route, **kw):
        calls.append(route)
        if route == "/api/v1/risk/clear":
            return {"cleared": True}
        if state["fail"] > 0:
            state["fail"] -= 1
            raise acc.ReaderError("CAPTCHA_REQUIRED", "要验证")
        return {"ok": 1}
    monkeypatch.setattr(acc, "_api_logged", fake)
    monkeypatch.setattr(acc, "_api", fake)
    monkeypatch.setattr(acc.time, "sleep", slept.append)
    monkeypatch.setattr(acc, "CAPTCHA_AUTO_MAX", 2)
    monkeypatch.setattr(acc, "_auto_cleared", 0)
    assert acc.api("GET", "/api/v1/boards") == {"ok": 1}
    assert calls == ["/api/v1/boards", "/api/v1/risk/clear", "/api/v1/boards"] and slept == [300]
    state["fail"] = 5                                        # 一直撞：用完 2 次照旧抛
    with pytest.raises(acc.ReaderError):
        acc.api("GET", "/api/v1/boards")
    monkeypatch.setattr(acc, "_auto_cleared", 0)
    calls.clear()
    monkeypatch.setattr(acc, "_api_logged", lambda *a, **k: (_ for _ in ()).throw(acc.ReaderError("NOT_LOGGED_IN", "掉了")))
    with pytest.raises(acc.ReaderError):
        acc.api("GET", "/api/v1/boards")
    assert calls == []                                       # 掉登录不解除


def test_check_risk_hold_waits_out_captcha_then_clears(monkeypatch):
    from link_brain.sources.xiaohongshu import accounts as acc
    slept, cleared = [], []
    since = datetime.now().astimezone() - timedelta(minutes=2)
    monkeypatch.setattr(acc, "risk_hold", lambda: {"code": "CAPTCHA_REQUIRED", "since": since.isoformat()})
    monkeypatch.setattr(acc, "_api", lambda m, r, **k: cleared.append(r) or {})
    monkeypatch.setattr(acc.time, "sleep", slept.append)
    monkeypatch.setattr(acc, "CAPTCHA_AUTO_MAX", 1)
    monkeypatch.setattr(acc, "_auto_cleared", 0)
    acc.check_risk_hold()                                    # 不抛：歇满 5 分钟（还差 ~3 分钟）就解除
    assert cleared == ["/api/v1/risk/clear"] and 170 < slept[0] <= 180
    monkeypatch.setattr(acc, "risk_hold", lambda: {"code": "NOT_LOGGED_IN", "since": since.isoformat()})
    with pytest.raises(acc.ReaderError):
        acc.check_risk_hold()
