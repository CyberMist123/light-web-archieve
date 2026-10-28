"""B 站收藏夹同步（1029）：分流计划、待选清单、下载循环（入库用替身）、专辑映射。全部离线。"""
from __future__ import annotations

import pytest

from link_brain import storage
from link_brain.sources import bilibili as bili
from link_brain.sources.bilibili import favorites, sync


def _item(bvid, title, duration=600, page=1, invalid=False, kind="video", fav_time=1, upper="UP"):
    return {"bvid": bvid, "id": 1, "kind": kind, "type": 2 if kind == "video" else 12, "title": title, "fav_time": fav_time,
            "attr": 9 if invalid else 0, "invalid": invalid, "invalid_reason": "up_deleted" if invalid else None,
            "page_count": page, "upper_name": upper, "duration": duration}


SNAPS = [
    {"media_id": 11, "title": "音乐", "items": [_item("BV1aaaaaaaa1", "短 MV", 180, fav_time=5),
                                                _item("BV1aaaaaaaa2", "两小时讲座", 7300, fav_time=4),
                                                _item("BV1aaaaaaaa3", "三 P 课程", 3000, page=3, fav_time=3)]},
    {"media_id": 12, "title": "学习", "items": [_item("BV1aaaaaaaa1", "短 MV", 180, fav_time=2),
                                                _item("BV1aaaaaaaa4", "已失效视频", 100, invalid=True),
                                                _item("", "一张专辑", 0, kind="audio"),
                                                _item("BV1aaaaaaaa5", "已在库", 500, fav_time=1)]},
]


def test_plan_buckets_and_dedupe():
    pl = sync.plan(SNAPS, in_library=lambda bv: bv == "BV1aaaaaaaa5")
    b = pl["buckets"]
    assert pl["bv_total"] == 5
    assert [r["bvid"] for r in b["download"]] == ["BV1aaaaaaaa1"]
    assert b["download"][0]["folders"] == ["音乐", "学习"]          # 跨收藏夹只算一次、两个专辑都记
    assert [r["bvid"] for r in b["long"]] == ["BV1aaaaaaaa2"] and "超过" in b["long"][0]["reason"]
    assert [r["bvid"] for r in b["multi_p"]] == ["BV1aaaaaaaa3"] and "3 P" in b["multi_p"][0]["reason"]
    assert [r["bvid"] for r in b["invalid"]] == ["BV1aaaaaaaa4"]
    assert [r["bvid"] for r in b["hit"]] == ["BV1aaaaaaaa5"]
    assert len(b["non_video"]) == 1
    # 放行长视频
    pl2 = sync.plan(SNAPS, allow={"BV1aaaaaaaa2"})
    assert {r["bvid"] for r in pl2["buckets"]["download"]} == {"BV1aaaaaaaa1", "BV1aaaaaaaa2", "BV1aaaaaaaa5"}


def test_pending_note_lists_links_only():
    pl = sync.plan(SNAPS)
    out = {"buckets": {**pl["buckets"], "downloaded": [], "failed": []}, "counts": {**pl["counts"], "folders": 2, "downloaded": 0, "failed": 0},
           "bv_total": pl["bv_total"], "finished_at": "2026-10-29T03:00:00+11:00"}
    text = sync.render_pending_note(out)
    assert "## 超过 1 小时" in text and "两小时讲座" in text and "https://www.bilibili.com/video/BV1aaaaaaaa2" in text
    assert "2:01:40" in text and "## 多 P 视频" in text and "三 P 课程" in text
    assert "## 原站已失效" in text and "## 不是视频稿件" in text
    assert "短 MV" not in text   # 要下载的不在待选清单里


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    return tmp_path


def test_run_sync_downloads_short_videos_only(vault, monkeypatch):
    from link_brain import ingest, catalog
    from link_brain.sources.bilibili import login

    class Client:
        def close(self):
            pass

    monkeypatch.setattr(favorites, "default_client", lambda: (Client(), {"state": "logged_in"}))
    monkeypatch.setattr(login, "my_mid", lambda client=None: 1234567)
    monkeypatch.setattr(favorites, "list_folders", lambda client, mid: {
        "status": "ok", "folders": [{"media_id": 11, "fid": 1, "owner_mid": mid, "title": "音乐", "private": False, "media_count": 3},
                                    {"media_id": 12, "fid": 2, "owner_mid": mid, "title": "学习", "private": True, "media_count": 4}]})
    snaps = {s["media_id"]: {**s, "owner_mid": 1234567, "complete": True, "status": "complete", "fetched_at": "t"} for s in SNAPS}
    monkeypatch.setattr(favorites, "sync_folder", lambda client, mid_, **kw: {"snapshot": snaps[mid_], "diff": None, "relations": None,
                                                                              "summary": {}, "prev_complete_at": None})
    calls = []

    def fake_ingest(url, **kw):
        calls.append((url, kw.get("ingest_kind")))
        return {"item_id": "bili-" + url.rsplit("/", 1)[1], "hit": False, "manifest": {"media": []}}
    monkeypatch.setattr(ingest, "ingest_url", fake_ingest)
    monkeypatch.setattr(ingest, "after_commit", lambda *a, **k: None)
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: None)
    out = sync.run_sync(gap_s=0, log=lambda m: None)
    assert out["ok"] is True
    assert calls == [("https://www.bilibili.com/video/BV1aaaaaaaa1", "favorite"), ("https://www.bilibili.com/video/BV1aaaaaaaa5", "favorite")]
    assert out["counts"]["downloaded"] == 2 and out["counts"]["long"] == 1 and out["counts"]["multi_p"] == 1
    note = sync.pending_note_path()
    assert note.is_file() and "两小时讲座" in note.read_text(encoding="utf-8")
    assert note.parent.name == "Bilibili"
    last = storage.read_json(favorites.sync_root() / "last-sync.json")
    assert last["counts"]["downloaded"] == 2 and "SESSDATA" not in str(last)
    assert all("media_id_masked" in f and "media_id" not in f for f in last["folders"])


def test_run_sync_stops_on_account_blocked(vault, monkeypatch):
    from link_brain import ingest, catalog, sources
    from link_brain.sources.bilibili import login

    class Client:
        def close(self):
            pass
    monkeypatch.setattr(favorites, "default_client", lambda: (Client(), {"state": "logged_in"}))
    monkeypatch.setattr(login, "my_mid", lambda client=None: 1)
    monkeypatch.setattr(favorites, "list_folders", lambda client, mid: {
        "status": "ok", "folders": [{"media_id": 11, "fid": 1, "owner_mid": 1, "title": "音乐", "private": False, "media_count": 2}]})
    snap = {"media_id": 11, "owner_mid": 1, "title": "音乐", "complete": True, "status": "complete",
            "items": [_item("BV1aaaaaaaa1", "一", 100, fav_time=2), _item("BV1aaaaaaaa2", "二", 100, fav_time=1)]}
    monkeypatch.setattr(favorites, "sync_folder", lambda *a, **k: {"snapshot": snap, "diff": None, "relations": None, "summary": {}, "prev_complete_at": None})

    def blocked(url, **kw):
        err = sources.AccountBlocked("登录失效")
        err.code = "NOT_LOGGED_IN"
        raise err
    monkeypatch.setattr(ingest, "ingest_url", blocked)
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: None)
    out = sync.run_sync(gap_s=0, log=lambda m: None)
    assert out["ok"] is False and out["code"] == "NEEDS_HUMAN" and "要人处理" in out["stopped"]
    assert out["counts"]["failed"] == 1 and out["counts"]["not_reached"] == 1


def test_run_sync_requires_login(vault, monkeypatch):
    class Client:
        def close(self):
            pass
    monkeypatch.setattr(favorites, "default_client", lambda: (Client(), {"state": "logged_out", "detail": "没登录"}))
    out = sync.run_sync(log=lambda m: None)
    assert out["ok"] is False and out["code"] == "NOT_LOGGED_IN"


def test_note_albums_reads_relations(vault):
    snap = {"owner_mid": 1, "media_id": 11, "title": "音乐", "complete": True, "fetched_at": "t",
            "items": [_item("BV1aaaaaaaa1", "一"), _item("BV1aaaaaaaa2", "二")]}
    favorites.update_relations(snap)
    snap2 = {"owner_mid": 1, "media_id": 12, "title": "学习", "complete": True, "fetched_at": "t", "items": [_item("BV1aaaaaaaa1", "一")]}
    favorites.update_relations(snap2)
    assert bili.note_albums() == {"BV1aaaaaaaa1": ["音乐", "学习"], "BV1aaaaaaaa2": ["音乐"]}
    assert "albums" in bili.capabilities


def test_fresh_complete_snapshot_is_reused_without_rescan(vault, monkeypatch):
    from datetime import datetime
    snap = {"owner_mid": 1, "media_id": 11, "title": "音乐", "complete": True, "media_count": 1, "status": "complete",
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"), "items": [_item("BV1aaaaaaaa1", "一")]}
    storage.write_json(favorites.last_complete_path(1, 11), snap)
    assert sync._fresh_snapshot(1, 11, 1, 6.0) is not None
    assert sync._fresh_snapshot(1, 11, 2, 6.0) is None          # 总数变了 → 重扫
    old = {**snap, "fetched_at": "2026-01-01T00:00:00+11:00"}
    storage.write_json(favorites.last_complete_path(1, 12), old)
    assert sync._fresh_snapshot(1, 12, 1, 6.0) is None          # 太旧 → 重扫


def test_choose_deny_writes_tombstone_and_plan_excludes(vault, monkeypatch):
    from link_brain import index as index_mod, ingest
    from link_brain.sources.bilibili import ytdlp
    out = sync.choose(allow=["BV1aaaaaaaa2"], deny=["BV1aaaaaaaa1"])
    assert out["allowed"] == ["BV1aaaaaaaa2"] and out["denied"] == ["BV1aaaaaaaa1"]
    ch = sync.load_choices()
    assert "BV1aaaaaaaa2" in ch["allow"] and "BV1aaaaaaaa1" in ch["deny"]
    conn = index_mod.connect()
    try:
        t = index_mod.get_tombstone(conn, "bilibili", "BV1aaaaaaaa1")
        assert t is not None and t["item_id"] == "bili-BV1aaaaaaaa1"
    finally:
        conn.close()

    def no_download(*a, **k):
        raise AssertionError("屏蔽的不该下载")
    monkeypatch.setattr(ytdlp, "run", no_download)
    monkeypatch.setattr(ytdlp, "ffmpeg_ok", lambda: True)
    got = ingest.ingest_url("https://www.bilibili.com/video/BV1aaaaaaaa1")
    assert got["status"] == "trashed"
    pl = sync.plan(SNAPS, allow=set(ch["allow"]), deny=set(ch["deny"]))
    assert [r["bvid"] for r in pl["buckets"]["denied"]] == ["BV1aaaaaaaa1"]
    assert "BV1aaaaaaaa2" in {r["bvid"] for r in pl["buckets"]["download"]} and pl["buckets"]["long"] == []
    text = sync.render_pending_note({"buckets": {**pl["buckets"], "downloaded": [], "failed": []},
                                     "counts": {**pl["counts"], "folders": 2}, "bv_total": pl["bv_total"]})
    assert "## 你删了的" in text and "短 MV" in text
    assert sync.choose(undo=["BV1aaaaaaaa2"])["undone"] == ["BV1aaaaaaaa2"]
    assert "BV1aaaaaaaa2" not in sync.load_choices()["allow"]
