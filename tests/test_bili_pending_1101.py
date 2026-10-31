"""1101「挑要下的视频」页的后端：pending-data.json（只读本地快照）、页面 md / 脚本、下载 = choose --allow 后数据跟着变。全部离线。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from link_brain import storage
from link_brain.sources.bilibili import favorites, sync, toview, ytdlp


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    monkeypatch.setattr(ytdlp, "missing_tools", lambda: [])
    (tmp_path / "vault").mkdir()
    return tmp_path / "vault"


def _item(bvid, title, duration, page=1, fav_time=1, cover="https://i0.hdslb.com/bfs/archive/x.jpg"):
    return {"bvid": bvid, "id": 1, "kind": "video", "type": 2, "title": title, "fav_time": fav_time, "attr": 0, "invalid": False,
            "invalid_reason": None, "page_count": page, "upper_name": "某 UP", "duration": duration, "cover": cover}


def _snaps():
    storage.write_json(favorites.snapshot_path(1, 11), {"owner_mid": 1, "media_id": 11, "title": "音乐", "complete": True, "items": [
        _item("BV1aaaaaaaa1", "短 MV", 180, fav_time=50),
        _item("BV1aaaaaaaa2", "两小时讲座", 7300, fav_time=40),
        _item("BV1aaaaaaaa6", "八 P 合集", 3000, page=8, fav_time=60, cover="")]})
    storage.write_json(favorites.snapshot_path(1, 12), {"owner_mid": 1, "media_id": 12, "title": "学习", "complete": True, "items": [
        _item("BV1aaaaaaaa2", "两小时讲座", 7300, fav_time=40),
        _item("BV1aaaaaaaa7", "三小时纪录片", 11000, fav_time=70)]})


def test_cover_urls_are_https_or_empty():
    assert favorites._item_row({"cover": "http://i0.hdslb.com/a.jpg"})["cover"] == "https://i0.hdslb.com/a.jpg"
    assert favorites._item_row({"cover": "//i1.hdslb.com/b.jpg"})["cover"] == "https://i1.hdslb.com/b.jpg"
    assert favorites._item_row({"cover": "javascript:alert(1)"})["cover"] == ""
    assert toview.item_row({"bvid": "BV1x", "pic": "http://i2.hdslb.com/c.jpg"})["cover"] == "https://i2.hdslb.com/c.jpg"


def test_pending_data_lists_long_and_multi_with_covers(vault):
    _snaps()
    d = sync.pending_data(max_duration_s=3600)
    # 收藏时间新的在前；短的不在（自动下）；跨收藏夹的只算一次、两个收藏夹都记
    assert [(r["bvid"], r["kind"]) for r in d["items"]] == [("BV1aaaaaaaa7", "long"), ("BV1aaaaaaaa6", "multi"), ("BV1aaaaaaaa2", "long")]
    lec = d["items"][2]
    assert lec["folders"] == ["音乐", "学习"] and lec["folder_ids"] == ["11", "12"] and lec["cover"].startswith("https://")
    assert lec["upper"] == "某 UP" and lec["fav_time"] == 40 and lec["chosen"] is False and lec["url"].endswith("/BV1aaaaaaaa2")
    assert d["items"][1]["page_count"] == 8 and d["items"][1]["done"] == 0
    assert d["folders"] == [{"id": "12", "title": "学习"}, {"id": "11", "title": "音乐"}]
    assert d["synced"] is True and d["max_duration"] == 3600 and d["auto_max"] == 5
    # 时长不限：只剩多 P
    assert [r["kind"] for r in sync.pending_data(max_duration_s=0)["items"]] == ["multi"]
    # 没给上限 → 按上次同步用的
    storage.write_json(favorites.sync_root() / "last-sync.json", {"options": {"max_duration_s": 7200}})
    assert {r["bvid"] for r in sync.pending_data()["items"]} == {"BV1aaaaaaaa7", "BV1aaaaaaaa6", "BV1aaaaaaaa2"}
    storage.write_json(favorites.sync_root() / "last-sync.json", {"options": {"max_duration_s": 9000}})
    assert {r["bvid"] for r in sync.pending_data()["items"]} == {"BV1aaaaaaaa7", "BV1aaaaaaaa6"}


def test_never_synced_says_so(vault):
    d = sync.pending_data()
    assert d["items"] == [] and d["synced"] is False and d["message"] == "还没同步过 B 站收藏"


def test_publish_writes_page_script_and_data_and_follows_renamed_page(vault):
    _snaps()
    sync.publish_pending(max_duration_s=3600)
    page = vault / "B站挑选.md"
    text = page.read_text(encoding="utf-8")
    assert text.startswith("---\nlb-page: bili-pending\ncssclasses: [lb-bilipage]\n---\n\n```dataviewjs\n")
    assert "_archive/bili-pending-page.js" in text.replace('"', "") or "bili-pending-page.js" in text
    script = (vault / "_archive" / "bili-pending-page.js").read_text(encoding="utf-8")
    assert "function lbPageLib" in script and "lbPageLib(dv, app, 'bili-pending')" in script
    data = json.loads((vault / "_archive" / "bilibili-sync" / "pending-data.json").read_text(encoding="utf-8"))
    assert len(data["items"]) == 3
    # 用户改了名：按页头找回那一份重写，不再另冒一份
    page.rename(vault / "我挑的B站.md")
    sync.publish_pending(max_duration_s=3600)
    assert not page.exists() and (vault / "我挑的B站.md").read_text(encoding="utf-8").startswith("---\nlb-page: bili-pending\n")
    assert sync.render_pending_note({"buckets": {"long": [{}]}, "counts": {}}, page=sync.pending_page_name()).count("[[我挑的B站|挑要下的视频]]") == 1


def test_download_button_is_choose_allow_and_data_follows(vault, capsys):
    _snaps()
    sync.publish_pending(max_duration_s=3600)
    data_path = vault / "_archive" / "bilibili-sync" / "pending-data.json"
    # 「下载」= choose --allow；后端顺手重写页面数据（页面靠文件版本变了重画）
    assert sync.run_choose(SimpleNamespace(allow=["BV1aaaaaaaa2"], deny=None, undo=None, max_duration=3600)) == 0
    capsys.readouterr()
    chosen = {r["bvid"]: r["chosen"] for r in json.loads(data_path.read_text(encoding="utf-8"))["items"]}
    assert chosen == {"BV1aaaaaaaa7": False, "BV1aaaaaaaa6": False, "BV1aaaaaaaa2": True}
    assert "BV1aaaaaaaa2" in sync.load_choices()["allow"]
    # 下次同步就下：plan 把它放进 download
    pl = sync.plan(sync._local_snapshots(), allow=set(sync.load_choices()["allow"]))
    assert "BV1aaaaaaaa2" in {r["bvid"] for r in pl["buckets"]["download"]}
    # 「不下」= choose --undo
    sync.run_choose(SimpleNamespace(allow=None, deny=None, undo=["BV1aaaaaaaa2"], max_duration=3600))
    capsys.readouterr()
    assert not any(r["chosen"] for r in json.loads(data_path.read_text(encoding="utf-8"))["items"])


def test_pending_cli_returns_page_name(vault, capsys):
    _snaps()
    assert sync.run_pending(SimpleNamespace(max_duration=0)) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True and out["page"] == "B站挑选.md" and [r["kind"] for r in out["items"]] == ["multi"]
    assert out["message"] == "1 个视频等你挑，点过「下载」的 0 个"


def test_delete_button_is_choose_deny_into_trash_records(vault, capsys):
    """「删除」= choose --deny：不下载、不进收藏，写删除屏蔽；回收站「记录」里有它（能重新导入），页面上不再列。"""
    _snaps()
    sync.publish_pending(max_duration_s=3600)
    sync.run_choose(SimpleNamespace(allow=None, deny=["BV1aaaaaaaa7"], undo=None, max_duration=3600))
    capsys.readouterr()
    data = json.loads((vault / "_archive" / "bilibili-sync" / "pending-data.json").read_text(encoding="utf-8"))
    assert "BV1aaaaaaaa7" not in {r["bvid"] for r in data["items"]}
    trash = json.loads((vault / "_archive" / "trash-data.json").read_text(encoding="utf-8"))
    rec = [x for x in trash["items"] if x["item_id"] == "bili-BV1aaaaaaaa7"]
    assert rec and rec[0]["title"] == "三小时纪录片" and rec[0]["has_files"] is False
