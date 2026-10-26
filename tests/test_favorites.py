"""`sync-favorites`：favdump 收藏列表 → 逐条 ingest（去重）→ 一个 JSON。

不碰网络、不碰真 favdump、不碰真 vault：monkeypatch `ingest_url` / `_ensure_rendered` /
`item_payload` / `fetch_favorites`。重点验：全量遍历、按 note_id 去重、ServiceDown/未登录停车 +
报警、stdout 只有一个 JSON、`--limit` 生效。
"""

from __future__ import annotations

import json

from link_brain import cli, favorites as fav_mod
from link_brain.adapters import xiaohongshu as xhs


def _fav(note_id: str) -> dict:
    return {
        "note_id": note_id,
        "xsec_token": "TOK",
        "url": f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token=TOK&xsec_source=pc_feed",
        "title": f"标题-{note_id}",
        "type": "normal",
    }


def _wire(monkeypatch, favs, *, ingest=None, alerts=None):
    monkeypatch.setattr(fav_mod, "fetch_favorites", lambda *, limit=50, verbose=False: favs[:limit])
    monkeypatch.setattr(fav_mod, "_render_local", lambda *a, **k: None)
    monkeypatch.setattr(
        fav_mod.read_mod,
        "item_payload",
        lambda source_key, source_id, status: {
            "item_id": f"{source_key}:{source_id}",
            "status": status,
            "url": None,
            "title": f"标题-{source_id}",
        },
    )
    if alerts is not None:
        monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: alerts.append((a, k)))
    if ingest is not None:
        monkeypatch.setattr(fav_mod.ingest_mod, "ingest_url", ingest)


def only_json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_sync_all_favorites_and_dedup(monkeypatch):
    favs = [_fav("aaa"), _fav("bbb"), _fav("aaa")]  # 第三条与第一条同 note_id

    def fake_ingest(url, **kwargs):
        assert kwargs["ingest_kind"] == "favorite"
        nid = url.split("/explore/")[1].split("?")[0]
        return {"hit": nid == "bbb", "note_id": nid, "item_id": f"xiaohongshu:{nid}"}

    _wire(monkeypatch, favs, ingest=fake_ingest)
    out = fav_mod.sync_favorites()
    assert out["favorites"] == 3
    assert out["synced"] == 2  # aaa 去重后只算一条
    statuses = {i["item_id"]: i["status"] for i in out["items"]}
    assert statuses == {"xiaohongshu:aaa": "new", "xiaohongshu:bbb": "hit"}


def test_limit_respected(monkeypatch):
    favs = [_fav(f"n{i:02d}") for i in range(10)]
    _wire(
        monkeypatch,
        favs,
        ingest=lambda url, **k: {
            "hit": True,
            "note_id": url.split("/explore/")[1].split("?")[0],
            "item_id": "xiaohongshu:" + url.split("/explore/")[1].split("?")[0],
        },
    )
    out = fav_mod.sync_favorites(limit=3)
    assert out["favorites"] == 3 and out["synced"] == 3


def test_service_down_stops_without_pushing(monkeypatch):
    favs = [_fav("aaa"), _fav("bbb"), _fav("ccc")]
    alerts: list = []

    def fake_ingest(url, **kwargs):
        nid = url.split("/explore/")[1].split("?")[0]
        if nid == "bbb":
            raise xhs.ServiceDownError("18060 挂了")
        return {"hit": False, "note_id": nid, "item_id": f"xiaohongshu:{nid}"}

    _wire(monkeypatch, favs, ingest=fake_ingest, alerts=alerts)
    out = fav_mod.sync_favorites()
    # aaa 成功、bbb blocked 后立刻停车，ccc 根本没跑
    assert [i["status"] for i in out["items"]] == ["new", "blocked"]
    # 第 4 批：读取服务挂了是 TRANSIENT（下次自动再试），不推送；登记在 sync_state.record（见 test_problems_batch4）
    assert alerts == []


def test_login_required_blocks_whole_batch(monkeypatch, capsys):
    def boom(*, limit=50, verbose=False):
        raise xhs.AccountBlockedError("收藏掉登录了，去扫码")

    monkeypatch.setattr(fav_mod, "fetch_favorites", boom)
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: None)

    class Args:
        limit = 50
        origin = "cli"
        actor = "human"
        verbose = False
        extract = False

    code = fav_mod.run(Args())
    assert code == 5
    payload = only_json(capsys)  # stdout 恰好一个 JSON
    assert payload["favorites"] == 0 and payload["items"][0]["status"] == "blocked"


def test_cli_dispatches_sync_favorites(monkeypatch, capsys):
    favs = [_fav("aaa"), _fav("bbb")]
    _wire(monkeypatch, favs, ingest=lambda url, **k: {
        "hit": True, "note_id": url.split("/explore/")[1].split("?")[0],
        "item_id": "xiaohongshu:" + url.split("/explore/")[1].split("?")[0]})
    code = cli.main(["sync-favorites", "--limit", "5"])
    assert code == 0
    payload = only_json(capsys)
    assert payload["favorites"] == 2 and payload["synced"] == 2 and payload["favorites_total"] == 2


def test_favorite_account_tag_is_deduplicated_and_survives_meta_rebuild(tmp_path, monkeypatch):
    from link_brain import favorites, storage
    monkeypatch.setattr(storage, "object_dir", lambda src, nid: tmp_path / nid)
    (tmp_path / "n1").mkdir()
    storage.write_json(tmp_path / "n1" / "meta.json", {"item_id": "xhs-n1"})
    assert favorites.tag_account("n1", {"nickname": "a", "user_id": "u1"}) is True
    assert favorites.tag_account("n1", {"nickname": "a", "user_id": "u1"}) is False
    assert favorites.tag_account("n1", {"nickname": "b", "user_id": "u2"}) is True
    tags = storage.read_json(tmp_path / "n1" / "meta.json")["favorited_by"]
    assert [t["nickname"] for t in tags] == ["a", "b"]


def test_switching_account_syncs_whoever_is_logged_in(monkeypatch):
    """1026 她定：没有「登错号」——登哪个号就同步哪个号；sync_account 只记上次同步的号，旧的登错号问题清掉。"""
    from link_brain import accounts, favorites as fav, problems
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: None)
    tagged = []
    def fake_fetch(nick):
        def _f(**kw):
            fav._CURRENT_ACCOUNT = {"nickname": nick, "user_id": ""}
            return [{"url": "https://example.invalid/x"}]
        return _f
    monkeypatch.setattr(fav, "_sync_one", lambda *a, **k: (tagged.append(fav._CURRENT_ACCOUNT["nickname"]),
                                                           {"item_id": "xhs-1", "status": "hit"})[1])
    monkeypatch.setattr(fav, "fetch_favorites", fake_fetch("momo"))
    assert fav.sync_favorites()["synced"] == 1
    assert accounts.config()["sync_account"] == "momo"
    problems.report_blocked("login", "WRONG_ACCOUNT", "旧版留下的登错号")
    monkeypatch.setattr(fav, "fetch_favorites", fake_fetch("Mac！"))
    out = fav.sync_favorites()
    assert out["synced"] == 1 and out.get("code") != "WRONG_ACCOUNT"
    assert accounts.config()["sync_account"] == "Mac！"
    assert tagged == ["momo", "Mac！"]
    assert "NEEDS_HUMAN.WRONG_ACCOUNT" not in [r.get("code") for r in problems.load()]


def test_snapshot_remembers_account_and_tags_with_it(monkeypatch):
    """1026：全量名单记下是哪个号的；换了号的一截不合进上一个号的名单，下次读全量。"""
    from link_brain import favorites as fav
    fav._CURRENT_ACCOUNT = {"nickname": "momo", "user_id": "u1"}
    fav._remember_list([{"note_id": "a1", "url": "https://example.invalid/a1"}], full=True)
    snap = fav.load_snapshot()
    assert snap["account"] == {"nickname": "momo", "user_id": "u1"}
    fav._CURRENT_ACCOUNT = {"nickname": "Mac！", "user_id": ""}
    fav._remember_list([{"note_id": "b1", "url": "https://example.invalid/b1"}], full=False)
    snap = fav.load_snapshot()
    assert [x["note_id"] for x in snap["items"]] == ["a1"] and snap.get("full_next")
    assert fav.read_mode()[0] == "full"

def test_retire_legacy_wrong_account():
    """1026：旧版留下的「登错号」问题和 sync-status 暂停一并收掉，第二次 0 开销。"""
    from link_brain import problems, storage, sync_state
    problems.report_blocked("login", "WRONG_ACCOUNT", "旧版留下的登错号")
    storage.write_json(sync_state.path(), {"state": "blocked", "code": "WRONG_ACCOUNT", "detail": "x", "message": "m"})
    assert problems.retire_wrong_account() >= 2
    assert sync_state.load()["state"] == "ready" and sync_state.load()["code"] == ""
    assert "NEEDS_HUMAN.WRONG_ACCOUNT" not in [r.get("code") for r in problems.load()]
    assert problems.retire_wrong_account() == 0
