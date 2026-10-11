"""1011：收藏同步的结构化进度（sync-status.json 的 `live`）。

以前进度句「第 594/1246 条收藏是新的」里的 594 是列表位置，不是进度。现在：今天第几篇 / 每天上限、这一趟新抓几篇、
库里几篇 / 收藏一共几篇（还差几篇）、正在抓哪篇、歇几秒（next_at）、今天额度大约几点抓完；收尾后 live 收起。
不联网：fetch_favorites / ingest_url / item_payload / _render_local 全部替身，_sleep 不真睡。
"""

from __future__ import annotations

from datetime import datetime

from link_brain import favorites as fav_mod, storage, sync_state
from link_brain.adapters import xiaohongshu as xhs


def _fav(nid: str) -> dict:
    return {"note_id": nid, "xsec_token": "TOK", "title": f"标题-{nid}",
            "url": f"https://www.xiaohongshu.com/explore/{nid}?xsec_token=TOK"}


def _setup(monkeypatch, favs, archived, *, limit=150, today=34):
    monkeypatch.setattr(fav_mod, "fetch_favorites", lambda *, limit=50, verbose=False, mode="full": list(favs))
    monkeypatch.setattr(fav_mod, "_render_local", lambda *a, **k: None)
    monkeypatch.setattr(fav_mod, "_already_archived", lambda fav: fav.get("note_id") in archived)
    monkeypatch.setattr(fav_mod.read_mod, "item_payload", lambda key, sid, status: {
        "item_id": f"xhs-{sid}", "status": status, "url": None, "title": f"标题-{sid}"})
    monkeypatch.setattr("link_brain.ai_config.sync_options", lambda: {"dailyNewLimit": limit})
    monkeypatch.setattr(fav_mod, "_rest_wait", lambda: 77.0)
    monkeypatch.setattr("link_brain.enrich.mark_pending", lambda *a, **k: None)
    monkeypatch.setattr("link_brain.attachments.grab_after_ingest", lambda *a, **k: "")
    root = storage.archive_root()
    (root / xhs.SOURCE).mkdir(parents=True, exist_ok=True)
    for nid in archived:
        (root / xhs.SOURCE / nid).mkdir(exist_ok=True)
    storage.write_json(root / "sync-quota.json", {"date": datetime.now().date().isoformat(), "new": today})
    sync_state.record("running", message="正在同步收藏")


def _live():
    return storage.read_json(sync_state.path()).get("live") or {}


def test_live_progress_fields_and_message(monkeypatch):
    favs = [_fav(f"n{i}") for i in range(10)]
    archived = {"n0", "n1", "n2", "n3", "n4", "n5"}          # 库里 6/10，还差 4
    _setup(monkeypatch, favs, archived)
    seen: dict[str, list] = {"fetch": [], "rest": []}

    def fake_ingest(url, **kw):
        nid = url.split("/explore/")[1].split("?")[0]
        if nid not in archived:
            seen["fetch"].append((_live(), storage.read_json(sync_state.path())["message"]))
        return {"hit": nid in archived, "note_id": nid, "item_id": f"xhs-{nid}", "title": f"标题-{nid}"}

    monkeypatch.setattr(fav_mod.ingest_mod, "ingest_url", fake_ingest)
    monkeypatch.setattr(fav_mod, "_sleep", lambda s: seen["rest"].append(_live()))
    out = fav_mod.sync_favorites(limit=0)
    assert len(out["fetched_new"]) == 4

    first, msg = seen["fetch"][0]
    assert first["phase"] == "fetching" and first["phase_text"] == "抓取中"
    assert first["today_new"] == 34 and first["daily_limit"] == 150 and first["this_run_new"] == 0
    assert first["archived"] == 6 and first["favorites_total"] == 10 and first["remaining"] == 4
    assert first["title"] == "标题-n6"
    assert first["eta_at"]
    # 不再是「第 7/10 条收藏是新的」这种列表位置
    assert msg == "正在同步收藏：今天第 35/150 篇 · 《标题-n6》"

    # 第二篇开抓前在歇：rest_s / next_at；计数已经跟着第一篇存好走了
    rest = seen["rest"][0]
    assert rest["phase"] == "resting" and rest["phase_text"] == "歇 77 秒" and rest["rest_s"] == 77
    assert datetime.fromisoformat(rest["next_at"]) > datetime.now().astimezone()
    assert rest["today_new"] == 35 and rest["this_run_new"] == 1 and rest["archived"] == 7 and rest["remaining"] == 3

    last = seen["fetch"][-1][0]
    assert last["today_new"] == 37 and last["this_run_new"] == 3 and last["remaining"] == 1

    # 收尾 + record(finished) 之后 live 收起；page_state 只在 running 时带 live
    st = storage.read_json(sync_state.path())
    assert st["live"]["phase"] == "finishing" and st["live"]["remaining"] == 0 and st["live"]["today_new"] == 38
    assert sync_state.page_state()["live"]["phase"] == "finishing"
    sync_state.record("finished", payload=out)
    assert "live" not in storage.read_json(sync_state.path())
    assert sync_state.page_state()["live"] is None


def test_live_unlimited_quota_and_no_eta_when_quota_full(monkeypatch):
    favs = [_fav("a"), _fav("b")]
    _setup(monkeypatch, favs, set(), limit=0, today=3)
    msgs = []
    monkeypatch.setattr(fav_mod.ingest_mod, "ingest_url", lambda url, **kw: (
        msgs.append(storage.read_json(sync_state.path())["message"]),
        {"hit": False, "note_id": url.split("/explore/")[1].split("?")[0], "item_id": "x", "title": "t"})[1])
    monkeypatch.setattr(fav_mod, "_sleep", lambda s: None)
    fav_mod.sync_favorites(limit=0)
    assert msgs[0].startswith("正在同步收藏：今天第 4 篇 · ")       # 0 = 不限：不写「/0」

    # 额度已满：一篇都不抓，也就没有 eta
    favs2 = [_fav("c")]
    _setup(monkeypatch, favs2, set(), limit=5, today=5)
    live = fav_mod._Live(fav_mod._Quota())
    live.count(favs2)
    assert live._eta() is None and live.remaining == 1


def test_progress_without_live_keeps_previous_live(monkeypatch):
    """「已存好」「查附件」这些中间句不带 live：进度条保持上一次的。"""
    sync_state.progress_log().parent.mkdir(parents=True, exist_ok=True)
    sync_state.record("running", message="正在同步收藏")
    sync_state.progress("今天第 1/5 篇 · 《x》", live={"phase": "fetching", "today_new": 0, "daily_limit": 5})
    sync_state.progress("《x》查附件 / 下附件中")
    st = storage.read_json(sync_state.path())
    assert st["live"]["phase"] == "fetching" and st["live"]["at"]
    assert st["progress"] == "《x》查附件 / 下附件中"
