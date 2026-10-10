"""1011 增量读收藏：平时只读最新一段（连着碰到 20 篇读过的就停），每周日 / 上次全量超过 7 天才滚到底；
积压按全量名单接着补；增量读不当「只读到一截」、不动基准、口令只合并读到的那段；老读取服务退回 GET；
撞验证自查恢复后 --from-snapshot 只按名单补抓、不读列表。

读取服务是假的（httpx.request 替身，记下方法和 body），抓详情是假的；合成 id。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

from link_brain import accounts, attachments, favorites, storage, sync_state
from link_brain.adapters import xiaohongshu as xhs

from test_night_sync import _ids, env  # noqa: F401 - env 是 fixture


def _fav(note_id, tok="T"):
    return {"note_id": note_id, "xsec_token": tok,
            "url": f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={tok}&xsec_source=pc_feed"}


class Reader:
    """假读取服务：记 (方法, 路径, body)；/favorites 按 handler(method, body) 应答。"""

    def __init__(self, monkeypatch, favorites_handler):
        self.calls, self.handler = [], favorites_handler
        monkeypatch.setattr(accounts.httpx, "request", self)

    def __call__(self, method, url, json=None, timeout=None):
        route = urlsplit(url).path
        self.calls.append((method, route, json))
        if route == "/api/v1/login/session":
            return httpx.Response(200, json={"state": "idle", "risk_hold": None, "lock": None})
        if route == "/api/v1/favorites":
            value = self.handler(method, json)
            if isinstance(value, httpx.Response):
                return value
            return httpx.Response(200, json=value)
        return httpx.Response(404, json={"error": "no route"})

    def fav_calls(self):
        return [c for c in self.calls if c[1] == "/api/v1/favorites"]


def _snapshot(ids, *, days_ago=1, now=None):
    now = now or datetime.now().astimezone()
    at = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    storage.write_json(favorites.fav_list_path(), {"schema_version": 1, "full_at": at, "at": at,
                                                   "items": [_fav(i, "OLD") for i in ids]})


@pytest.fixture
def not_sunday(monkeypatch):
    monkeypatch.setenv("LWA_FAV_FULL_WEEKDAY", "-1")


# ---------------------------------------------------------------- 读全量还是增量

def test_read_mode_rules(monkeypatch):
    sunday = datetime(2026, 10, 11, 4, 0).astimezone()   # 2026-10-11 是周日
    monday = sunday + timedelta(days=1)
    assert favorites.read_mode(now=monday)[0] == "full", "没有名单：全量"
    _snapshot(["a"], days_ago=1, now=monday)
    assert favorites.read_mode(now=monday) == ("incremental", "")
    assert favorites.read_mode(force_full=True, now=monday)[0] == "full"
    _snapshot(["a"], days_ago=2, now=sunday)
    assert favorites.read_mode(now=sunday) == ("full", "每周一次的全量")
    monkeypatch.setenv("LWA_FAV_FULL_WEEKDAY", "-1")
    assert favorites.read_mode(now=sunday)[0] == "incremental"
    _snapshot(["a"], days_ago=7, now=monday)
    assert favorites.read_mode(now=monday)[0] == "full", "上次全量超过 7 天"
    _snapshot(["a"], days_ago=1, now=monday)
    favorites.mark_full_next("按名单抓连着失败")
    assert favorites.read_mode(now=monday)[0] == "full"


# ---------------------------------------------------------------- 增量读：请求、合并、口令、基准

def test_incremental_posts_known_ids_and_merges_backlog(env, monkeypatch, capsys, not_sunday):
    old = _ids(6, "aaaaaaaaaaaaaaaa")
    _snapshot(old)
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": 1233})
    attachments.remember_fav_tokens([_fav(i, "OLD") for i in old], partial=False)
    new = _ids(2, "cccccccccccccccc")
    # 读取服务读到最新那段：2 篇新的 + 3 篇读过的（停在已知处）
    reader = Reader(monkeypatch, lambda m, body: {"nickname": "alice", "items": [_fav(i, "NEW") for i in new + old[:3]],
                                                  "partial": False, "stop_reason": "known_streak",
                                                  "incremental": True, "has_more": True})
    code, out = _run(capsys)
    method, _, body = reader.fav_calls()[0]
    assert method == "POST" and body["stop_after_known"] == 20 and body["expect"] == 1233
    assert set(old) <= set(body["known_ids"]) and not (set(new) & set(body["known_ids"]))
    assert len(reader.fav_calls()) == 1, "一晚只读一次收藏"
    assert code == 0, out
    assert sorted(env.fetched) == sorted(new + old), "新的 + 名单里的积压都照抓"
    assert out["read_mode"] == "incremental" and "favorites_total" not in out and "suspicious" not in out
    assert sync_state.load()["last_favorites"] == 1233, "增量读不动基准"
    snap = favorites.load_snapshot()
    assert [x["note_id"] for x in snap["items"]][:2] == new and len(snap["items"]) == 8
    tokens = storage.read_json(attachments.fav_tokens_path())["tokens"]
    assert tokens[new[0]]["token"] == "NEW" and tokens[old[0]]["token"] == "NEW" and tokens[old[5]]["token"] == "OLD"


def test_incremental_small_count_is_not_suspicious():
    assert favorites.suspicious_reason(25, 1233, {"stop_reason": "known_streak", "incremental": True}) == ""
    assert "0 条" in favorites.suspicious_reason(0, 1233, {"stop_reason": "known_streak", "incremental": True})
    assert favorites.suspicious_reason(25, 1233, {"stop_reason": "stable"}), "全量读少了一大截照旧可疑"


def test_old_reader_without_post_falls_back_to_get(env, monkeypatch, capsys, not_sunday):
    old = _ids(3, "aaaaaaaaaaaaaaaa")
    _snapshot(old)
    items = [_fav(i) for i in old]
    reader = Reader(monkeypatch, lambda m, body: httpx.Response(404, json={"error": "no route"}) if m == "POST"
                    else {"nickname": "alice", "items": items})
    code, out = _run(capsys)
    assert [c[0] for c in reader.fav_calls()] == ["POST", "GET"]
    assert code == 0 and out["favorites_total"] == 3, "退回读全量：照旧认总数"


def test_full_read_replaces_snapshot_but_partial_does_not(env, monkeypatch, capsys):
    _snapshot(_ids(5, "aaaaaaaaaaaaaaaa"), days_ago=8)
    full = _ids(4, "dddddddddddddddd")
    Reader(monkeypatch, lambda m, body: {"nickname": "alice", "items": [_fav(i) for i in full],
                                         "partial": False, "stop_reason": "has_more_false"})
    _run(capsys)
    snap = favorites.load_snapshot()
    assert [x["note_id"] for x in snap["items"]] == full
    assert datetime.fromisoformat(snap["full_at"]) > datetime.now().astimezone() - timedelta(minutes=5)
    # 第二次全量只读到一截：名单不被截短（只把读到的合进去），full_at 不动
    before = snap["full_at"]
    Reader(monkeypatch, lambda m, body: {"nickname": "alice", "items": [_fav(full[0])],
                                         "partial": True, "stop_reason": "budget"})
    favorites.fetch_favorites(limit=0, mode="full")
    snap = favorites.load_snapshot()
    assert len(snap["items"]) == 4 and snap["full_at"] == before


# ---------------------------------------------------------------- 按名单补抓（自查恢复后）

def test_from_snapshot_does_not_read_the_list(env, monkeypatch, capsys):
    old = _ids(3, "aaaaaaaaaaaaaaaa")
    _snapshot(old)
    reader = Reader(monkeypatch, lambda m, body: pytest.fail("按名单补抓不许读收藏列表"))
    code, out = _run(capsys, from_snapshot=True)
    assert code == 0 and sorted(env.fetched) == sorted(old) and reader.fav_calls() == []
    assert out["read_mode"] == "snapshot" and "favorites_total" not in out


def test_from_snapshot_skips_when_snapshot_is_stale(env, monkeypatch, capsys):
    _snapshot(_ids(3, "aaaaaaaaaaaaaaaa"), days_ago=8)
    Reader(monkeypatch, lambda m, body: pytest.fail("不读列表"))
    code, out = _run(capsys, from_snapshot=True)
    assert code == 0 and env.fetched == [] and "名单" in out["note"]


def test_snapshot_failures_force_full_read_next_time(env, monkeypatch, capsys, not_sunday):
    old = _ids(4, "aaaaaaaaaaaaaaaa")
    _snapshot(old)
    env.fail = set(old)
    Reader(monkeypatch, lambda m, body: pytest.fail("不读列表"))
    _run(capsys, from_snapshot=True)
    assert favorites.load_snapshot().get("full_next"), "按名单的旧口令连着失败：下次读全量刷新口令"
    assert favorites.read_mode()[0] == "full"


def _run(capsys, **kw):
    args = dict(limit=0, origin="cli", actor="human", verbose=False, extract=False, budget_min=0, wait_lock_min=0,
                full=False, from_snapshot=False)
    args.update(kw)
    code = favorites.run(SimpleNamespace(**args))
    return code, json.loads(capsys.readouterr().out)
