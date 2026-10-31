"""1031 她：挑选页（收藏夹开关 + 长视频勾选）、稍后再看一起同步、下载路数放到 8。全部离线：B 站接口是假响应，入库是替身。"""
from __future__ import annotations

import pytest

from link_brain import storage
from link_brain.sources import bilibili as bili
from link_brain.sources.bilibili import favorites, sync, toview, ytdlp


def _item(bvid, title, duration=600, page=1, invalid=False, fav_time=1):
    return {"bvid": bvid, "id": 1, "kind": "video", "type": 2, "title": title, "fav_time": fav_time, "attr": 9 if invalid else 0,
            "invalid": invalid, "invalid_reason": "up_deleted" if invalid else None, "page_count": page, "upper_name": "UP",
            "duration": duration}


# bilibili-API-collect history&toview/toview.md 的形状（字段删到用得上的）
TOVIEW_BODY = {"code": 0, "message": "0", "data": {"count": 3, "list": [
    {"aid": 101, "bvid": "BV1tv0000001", "title": "稍后看的短片", "videos": 1, "duration": 300, "state": 0, "add_at": 1761800000,
     "owner": {"mid": 9, "name": "某UP"}, "cid": 5, "pubdate": 1760000000},
    {"aid": 102, "bvid": "BV1tv0000002", "title": "稍后看的长片", "videos": 1, "duration": 9000, "state": 0, "add_at": 1761700000,
     "owner": {"mid": 9, "name": "某UP"}},
    {"aid": 103, "bvid": "BV1tv0000003", "title": "已失效视频", "videos": 1, "duration": 10, "state": -100, "add_at": 1761600000,
     "owner": {}},
]}}


class Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class Client:
    def __init__(self, body=TOVIEW_BODY, status=200):
        self.body, self.status, self.urls = body, status, []

    def get(self, url, params=None):
        self.urls.append(url)
        return Resp(self.body, self.status)

    def close(self):
        pass


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    monkeypatch.setattr(ytdlp, "missing_tools", lambda: [])   # 1031：开跑前的缺下载器检查不看测试机装没装
    return tmp_path


# ---- 稍后再看 ----

def test_toview_snapshot_same_shape_as_folder(vault):
    c = Client()
    r = toview.sync_toview(c, 1234567, now="2026-10-31T10:00:00+11:00")
    assert c.urls == ["https://api.bilibili.com/x/v2/history/toview"]
    snap = r["snapshot"]
    assert r["error"] is None and snap["complete"] and snap["media_id"] == "toview" and snap["title"] == "稍后再看"
    assert favorites.snapshot_path(1234567, "toview").name == "1234567-toview.json"
    assert storage.read_json(favorites.snapshot_path(1234567, "toview"))["item_count"] == 3
    a, b, dead = snap["items"]
    assert (a["bvid"], a["duration"], a["page_count"], a["upper_name"], a["fav_time"], a["kind"]) == ("BV1tv0000001", 300, 1, "某UP", 1761800000, "video")
    assert dead["invalid"] is True and not a["invalid"]
    # 同一套 plan：短的下、长的进 long、失效的进 invalid；专辑 = 稍后再看
    pl = sync.plan([snap])
    assert [x["bvid"] for x in pl["buckets"]["download"]] == ["BV1tv0000001"]
    assert [x["bvid"] for x in pl["buckets"]["long"]] == ["BV1tv0000002"]
    assert pl["buckets"]["download"][0]["folders"] == ["稍后再看"] and pl["buckets"]["download"][0]["folder_ids"] == ["toview"]
    assert bili.note_albums()["BV1tv0000001"] == ["稍后再看"]


def test_toview_removed_items_keep_album(vault):
    """从稍后再看里移除的：不删本地、不解除「稍后再看」专辑（收藏夹取消收藏照旧解除）。"""
    toview.sync_toview(Client(), 1)
    body = {"code": 0, "data": {"count": 1, "list": [TOVIEW_BODY["data"]["list"][1]]}}
    toview.sync_toview(Client(body), 1)
    albums = bili.note_albums()
    assert albums["BV1tv0000001"] == ["稍后再看"] and albums["BV1tv0000002"] == ["稍后再看"]
    # 空列表（data.list=null）也不炸
    r = toview.sync_toview(Client({"code": 0, "data": {"count": 0, "list": None}}), 1)
    assert r["snapshot"]["status"] == "empty" and r["snapshot"]["items"] == []
    # 收藏夹那边仍然解除（不受影响）
    favorites.update_relations({"owner_mid": 1, "media_id": 11, "title": "音乐", "complete": True, "items": [_item("BV1x", "x")]})
    favorites.update_relations({"owner_mid": 1, "media_id": 11, "title": "音乐", "complete": True, "items": []})
    assert "BV1x" not in bili.note_albums()


def test_toview_error_falls_back_to_last_snapshot(vault):
    toview.sync_toview(Client(), 1)
    r = toview.sync_toview(Client({"code": -412, "message": "请求被拦截"}), 1)
    assert r["stale"] is True and r["error"]["reason"] == "rate_limited" and r["snapshot"]["item_count"] == 3
    r2 = toview.sync_toview(Client({"code": -101, "message": "账号未登录"}), 2)
    assert r2["stale"] is False and r2["snapshot"]["items"] == [] and r2["snapshot"]["status"] == "not_logged_in"
    assert not favorites.snapshot_path(2, "toview").exists()


# ---- 跑同步：跳过收藏夹 + 稍后再看 + 8 路 ----

def _wire(monkeypatch, client):
    from link_brain import catalog, ingest
    from link_brain.sources.bilibili import login
    monkeypatch.setattr(favorites, "default_client", lambda: (client, {"state": "logged_in"}))
    monkeypatch.setattr(login, "my_mid", lambda client=None: 1)
    monkeypatch.setattr(favorites, "list_folders", lambda c, mid: {"status": "ok", "folders": [
        {"media_id": 11, "fid": 1, "owner_mid": 1, "title": "音乐", "private": False, "media_count": 1},
        {"media_id": 12, "fid": 2, "owner_mid": 1, "title": "私房", "private": True, "media_count": 1}]})
    snaps = {11: {"media_id": 11, "owner_mid": 1, "title": "音乐", "complete": True, "status": "complete", "items": [_item("BV1music0001", "歌")]},
             12: {"media_id": 12, "owner_mid": 1, "title": "私房", "complete": True, "status": "complete", "items": [_item("BV1priv00001", "私")]}}
    scanned = []

    def sync_folder(c, media_id, **kw):
        scanned.append(media_id)
        return {"snapshot": snaps[media_id], "diff": None, "relations": None, "summary": {}, "prev_complete_at": None}
    monkeypatch.setattr(favorites, "sync_folder", sync_folder)
    got = []

    def fake_ingest(url, **kw):
        got.append(url.rsplit("/", 1)[1])
        return {"item_id": "bili-" + got[-1], "hit": False, "manifest": {"media": []}}
    monkeypatch.setattr(ingest, "ingest_url", fake_ingest)
    monkeypatch.setattr(ingest, "after_commit", lambda *a, **k: None)
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: None)
    return scanned, got


def test_run_sync_skips_closed_folders_and_includes_toview(vault, monkeypatch):
    client = Client()
    scanned, got = _wire(monkeypatch, client)
    out = sync.run_sync(gap_s=0, folder_gap_s=0, skip_folders=["12"], workers=20, log=lambda m: None, sleep=lambda s: None)
    assert out["ok"] is True
    assert scanned == [11], "关掉的收藏夹不扫"
    assert sorted(got) == ["BV1music0001", "BV1tv0000001"], "关掉的不下；稍后再看里的短片一起下"
    assert out["counts"]["skipped_folders"] == 1 and out["counts"]["toview"] == 3
    assert out["options"]["workers"] == 8 and out["options"]["skip_folders"] == ["12"], "路数上限 8"
    assert [f["title"] for f in out["folders"]] == ["音乐", "稍后再看"]
    # 列到的全部收藏夹（含关掉的）落盘给挑选页
    fl = storage.read_json(sync.folder_list_path())
    assert [(f["id"], f["title"], f["private"]) for f in fl["folders"]] == [("11", "音乐", False), ("12", "私房", True)]


def test_run_sync_skip_toview(vault, monkeypatch):
    client = Client()
    scanned, got = _wire(monkeypatch, client)
    out = sync.run_sync(gap_s=0, folder_gap_s=0, skip_folders=["toview"], log=lambda m: None, sleep=lambda s: None)
    assert client.urls == [] and sorted(got) == ["BV1music0001", "BV1priv00001"]
    assert out["counts"]["skipped_folders"] == 1 and "toview" not in out["counts"]


def test_cli_args_skip_folder_pick_and_workers_cap(vault, monkeypatch):
    from link_brain import cli
    seen = {}
    monkeypatch.setattr(sync, "run_sync", lambda **kw: seen.update(kw) or {"ok": True, "message": "ok", "buckets": {}})
    args = cli.build_parser().parse_args(["bilibili", "sync", "--json", "--workers", "12", "--skip-folder", "12", "--skip-folder", "toview"])
    assert sync.run(args) == 0
    assert seen["workers"] == 8 and seen["skip_folders"] == ["12", "toview"]
    args = cli.build_parser().parse_args(["bilibili", "pick", "--json", "--max-duration", "1800"])
    assert args.bilibili_cmd == "pick" and args.max_duration == 1800


# ---- 挑选页数据 ----

def test_picker_lists_folders_toview_first_and_long_with_folder_ids(vault, monkeypatch):
    from link_brain import index as index_mod
    empty = sync.picker(max_duration_s=3600)
    assert empty["empty"] is True and "先点一次「预估」或「立即同步」" in empty["message"] and empty["folders"] == []

    storage.write_json(sync.folder_list_path(), {"owner_mid": 1, "fetched_at": "t", "folders": [
        {"id": "11", "title": "音乐", "private": False, "media_count": 2}, {"id": "12", "title": "私房", "private": True, "media_count": 1}]})
    root = favorites.sync_root() / "folders"
    storage.write_json(root / "1-11.json", {"owner_mid": 1, "media_id": 11, "title": "音乐", "media_count": 2,
                                           "items": [_item("BV1long00001", "长课", 7200), _item("BV1short0001", "短", 60)]})
    storage.write_json(root / "1-toview.json", {"owner_mid": 1, "media_id": "toview", "title": "稍后再看", "media_count": 1,
                                               "items": [_item("BV1long00001", "长课", 7200)]})
    storage.write_json(root / "99-5.json", {"owner_mid": 99, "media_id": 5, "title": "别人的", "items": []})

    class Conn:
        def close(self):
            pass
    monkeypatch.setattr(index_mod, "connect", lambda: Conn())
    monkeypatch.setattr(index_mod, "find_object", lambda conn, src, bv: None)
    p = sync.picker(max_duration_s=3600)
    assert [(f["id"], f["kind"]) for f in p["folders"]] == [("toview", "toview"), ("11", "folder"), ("12", "folder")]
    assert p["folders"][2]["private"] is True and p["folders"][2]["scanned"] is False
    assert p["folders"][0]["media_count"] == 1
    long_rows = p["long"]["items"]
    assert [r["bvid"] for r in long_rows] == ["BV1long00001"]
    assert sorted(long_rows[0]["folder_ids"]) == ["11", "toview"] and sorted(long_rows[0]["folders"]) == ["稍后再看", "音乐"]
    assert "收藏夹 3 个" in p["message"]
    # 不限时长：不列长视频
    assert sync.picker(max_duration_s=0)["long"]["total"] == 0
