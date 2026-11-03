"""1103：同步途中目录跟上（收藏页「共 N 篇」/ 今日新增 / 卡片不再等整轮收尾）；Token「本月」能现读；楼中楼限频不写原因。

作者实测：顶部「共 0 篇」、侧栏「同步中 2/1420」、正文「还没有收藏」——侧栏读 sync-status.json 的实时进度，
篇数 / 卡片读 catalog-data.json，后者以前只在整轮同步收尾时重建。全部离线：抓取 / 入库 / 建目录都是替身。
"""
from __future__ import annotations

from datetime import datetime

from link_brain import favorites as fav_mod, storage, sync_state
from link_brain.adapters import xiaohongshu as xhs


def _fav(nid: str) -> dict:
    return {"note_id": nid, "xsec_token": "TOK", "title": f"标题-{nid}",
            "url": f"https://www.xiaohongshu.com/explore/{nid}?xsec_token=TOK"}


def _setup_xhs(monkeypatch, favs):
    monkeypatch.setattr(fav_mod, "fetch_favorites", lambda *, limit=50, verbose=False, mode="full": list(favs))
    monkeypatch.setattr(fav_mod, "_render_local", lambda *a, **k: None)
    monkeypatch.setattr(fav_mod, "_already_archived", lambda fav: False)
    monkeypatch.setattr(fav_mod.read_mod, "item_payload", lambda key, sid, status: {
        "item_id": f"xhs-{sid}", "status": status, "url": None, "title": f"标题-{sid}"})
    monkeypatch.setattr("link_brain.ai_config.sync_options", lambda: {"dailyNewLimit": 0})
    monkeypatch.setattr(fav_mod, "_rest_wait", lambda: 77.0)
    monkeypatch.setattr("link_brain.enrich.mark_pending", lambda *a, **k: None)
    monkeypatch.setattr("link_brain.attachments.grab_after_ingest", lambda *a, **k: "")
    monkeypatch.setattr(fav_mod.ingest_mod, "ingest_url", lambda url, **kw: {
        "hit": False, "note_id": url.split("/explore/")[1].split("?")[0], "item_id": "x", "title": "t"})
    (storage.archive_root() / xhs.SOURCE).mkdir(parents=True, exist_ok=True)
    storage.write_json(storage.archive_root() / "sync-quota.json", {"date": datetime.now().date().isoformat(), "new": 0})
    sync_state.record("running", message="正在同步收藏")


def test_xhs_sync_rebuilds_catalog_in_each_rest_and_rest_absorbs_build_time(monkeypatch):
    _setup_xhs(monkeypatch, [_fav("a"), _fav("b"), _fav("c")])
    now = [1000.0]
    monkeypatch.setattr(fav_mod, "_clock", lambda: now[0])
    events = []

    def catch_up():
        events.append(("catalog", now[0]))
        now[0] += 10.0        # 建目录花了 10 秒

    monkeypatch.setattr(fav_mod, "_catalog_catch_up", catch_up)
    monkeypatch.setattr(fav_mod, "_sleep", lambda s: events.append(("sleep", round(s))))
    out = fav_mod.sync_favorites(limit=0)
    assert len(out["fetched_new"]) == 3
    # 第一篇前不歇也不建；之后每次歇之前先让目录跟上刚存好的那篇，歇的时间扣掉建目录花的 10 秒（节奏不变）
    assert [e[0] for e in events] == ["catalog", "sleep", "catalog", "sleep"]
    assert [e[1] for e in events if e[0] == "sleep"] == [67, 67]


def test_xhs_catch_up_uses_catalog_ensure_fresh_without_waiting(monkeypatch):
    seen = []
    monkeypatch.setattr("link_brain.catalog.ensure_fresh", lambda vault=None, *, wait_s=0: seen.append(wait_s) or "busy")
    fav_mod._catalog_catch_up()
    assert seen == [0], "别人正在建目录就不等（收尾还会再建一次）"
    monkeypatch.setattr("link_brain.catalog.ensure_fresh", lambda **k: (_ for _ in ()).throw(RuntimeError("坏了")))
    fav_mod._catalog_catch_up()   # 建目录出错不挡同步


def test_bili_sync_catches_catalog_up_while_downloading(tmp_path, monkeypatch):
    from link_brain import catalog, ingest
    from link_brain.sources.bilibili import favorites, login, sync, ytdlp
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    monkeypatch.setattr(ytdlp, "missing_tools", lambda: [])

    class Client:
        def close(self):
            pass

    items = [{"bvid": f"BV1aaaaaaaa{i}", "id": 1, "kind": "video", "type": 2, "title": f"短 {i}", "fav_time": 10 - i,
              "attr": 0, "invalid": False, "invalid_reason": None, "page_count": 1, "upper_name": "UP", "duration": 100}
             for i in range(1, 5)]
    snap = {"media_id": 11, "title": "音乐", "items": items, "owner_mid": 1, "complete": True, "status": "complete", "fetched_at": "t"}
    monkeypatch.setattr(favorites, "default_client", lambda: (Client(), {"state": "logged_in"}))
    monkeypatch.setattr(login, "my_mid", lambda client=None: 1)
    monkeypatch.setattr(favorites, "list_folders", lambda client, mid: {
        "status": "ok", "folders": [{"media_id": 11, "fid": 1, "owner_mid": mid, "title": "音乐", "private": False, "media_count": 4}]})
    monkeypatch.setattr(favorites, "sync_folder", lambda *a, **k: {"snapshot": snap, "diff": None, "relations": None,
                                                                   "summary": {}, "prev_complete_at": None})
    now = [0.0]

    def fake_ingest(url, **kw):
        now[0] += 40.0        # 每条下 + 入库 40 秒
        return {"item_id": "bili-" + url.rsplit("/", 1)[1], "hit": False, "manifest": {"media": []}}

    monkeypatch.setattr(ingest, "ingest_url", fake_ingest)
    monkeypatch.setattr(ingest, "after_commit", lambda *a, **k: None)
    monkeypatch.setattr(sync.time, "monotonic", lambda: now[0])
    built = []
    monkeypatch.setattr(sync, "_catalog_catch_up", lambda: built.append(now[0]))
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: built.append(("end", now[0])))
    out = sync.run_sync(gap_s=0, log=lambda m: None)
    assert out["counts"]["downloaded"] == 4
    # 至少隔 CATALOG_CATCH_UP_S（60 秒）才建一次：第 2 条（80 秒）、第 4 条（160 秒）后；收尾 _persist 再建一次
    assert built == [80.0, 160.0, ("end", 160.0)]


def test_usage_command_returns_month_summary(monkeypatch, capsys):
    import json
    from link_brain import usage
    monkeypatch.setattr(usage, "month_summary", lambda **k: {"month": "2026-11", "cost_cny": 1.23, "calls": 4})
    monkeypatch.setattr(usage, "summary", lambda **k: {"windows": {}})
    monkeypatch.setattr(usage, "provider_links", lambda *a, **k: {})
    monkeypatch.setattr(usage, "key_status", lambda *a, **k: {})
    monkeypatch.setattr("link_brain.ai_config.ai_table", lambda: [])
    assert usage.run(type("A", (), {"table": False, "balance": False})()) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["month_summary"]["cost_cny"] == 1.23, "目录页「Token 费用 · 本月」现读这一份"


def test_sub_paused_gap_has_no_reason_on_note_page():
    from link_brain.sources.xiaohongshu import presentation
    c = {"comment_id": "c1"}
    text = presentation.comment_gap_text(c, 5, {"c1": "sub_paused"})
    assert text == "还有 5 条回复，后台在补" and "暂停" not in text
    # 别的原因照旧写
    assert "被限频先停" in presentation.comment_gap_text(c, 5, {"c1": "throttled"})
    # 评论区顶上那一行（按设置楼数现算的 view）：不写「楼中楼这会儿暂停」
    line = presentation.comment_status_text({}, [c], view={"missing": 3, "why": "", "why_code": "sub_paused", "floors": 10})
    assert "暂停" not in line and line.endswith("还缺 3 条（后台在补）")
    # 老格式（只有 comment_load）
    line = presentation.comment_status_text({"comment_load": {"replies_missing": 2, "floors_loaded": 4, "fill_attempts": 0,
                                                              "gaps": [{"reason": "sub_paused", "missing": 2}]}}, [c])
    assert "暂停" not in line and "楼中楼还缺 2 条（下次同步接着读）" in line
