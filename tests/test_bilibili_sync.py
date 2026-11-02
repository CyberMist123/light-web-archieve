"""B 站收藏夹同步（1029）：分流计划、待选清单、下载循环（入库用替身）、专辑映射。全部离线。"""
from __future__ import annotations

import pytest

from link_brain import storage
from link_brain.sources import bilibili as bili
from link_brain.sources.bilibili import favorites, sync, ytdlp


def _item(bvid, title, duration=600, page=1, invalid=False, kind="video", fav_time=1, upper="UP"):
    return {"bvid": bvid, "id": 1, "kind": kind, "type": 2 if kind == "video" else 12, "title": title, "fav_time": fav_time,
            "attr": 9 if invalid else 0, "invalid": invalid, "invalid_reason": "up_deleted" if invalid else None,
            "page_count": page, "upper_name": upper, "duration": duration}


SNAPS = [
    {"media_id": 11, "title": "音乐", "items": [_item("BV1aaaaaaaa1", "短 MV", 180, fav_time=5),
                                                _item("BV1aaaaaaaa2", "两小时讲座", 7300, fav_time=4),
                                                _item("BV1aaaaaaaa3", "三 P 课程", 3000, page=3, fav_time=3),
                                                _item("BV1aaaaaaaa6", "八 P 合集", 3000, page=8, fav_time=3)]},
    {"media_id": 12, "title": "学习", "items": [_item("BV1aaaaaaaa1", "短 MV", 180, fav_time=2),
                                                _item("BV1aaaaaaaa4", "已失效视频", 100, invalid=True),
                                                _item("", "一张专辑", 0, kind="audio"),
                                                _item("BV1aaaaaaaa5", "已在库", 500, fav_time=1)]},
]


def test_plan_buckets_and_dedupe():
    pl = sync.plan(SNAPS, in_library=lambda bv: bv == "BV1aaaaaaaa5")
    b = pl["buckets"]
    assert pl["bv_total"] == 6
    # 1031：≤5 P 的拆成每 P 一条（P1 的 source_id 就是 BV 号，其余 BV_pN，地址带 ?p=N）
    assert [(r["bvid"], r.get("page", 1)) for r in b["download"]] == [("BV1aaaaaaaa1", 1), ("BV1aaaaaaaa3", 1), ("BV1aaaaaaaa3", 2), ("BV1aaaaaaaa3", 3)]
    p3 = b["download"][3]
    assert p3["source_id"] == "BV1aaaaaaaa3_p3" and p3["url"].endswith("/BV1aaaaaaaa3?p=3") and p3["title"] == "三 P 课程 · P3"
    assert b["download"][1]["source_id"] == "BV1aaaaaaaa3" and "?p=" not in b["download"][1]["url"] and p3["duration"] == 1000
    assert b["download"][0]["folders"] == ["音乐", "学习"]          # 跨收藏夹只算一次、两个专辑都记
    assert [r["bvid"] for r in b["long"]] == ["BV1aaaaaaaa2"] and "超过" in b["long"][0]["reason"]
    assert [r["bvid"] for r in b["multi_p"]] == ["BV1aaaaaaaa6"] and "8 P" in b["multi_p"][0]["reason"]
    assert [r["bvid"] for r in b["invalid"]] == ["BV1aaaaaaaa4"]
    assert [r["bvid"] for r in b["hit"]] == ["BV1aaaaaaaa5"]
    assert len(b["non_video"]) == 1
    # 放行长视频
    pl2 = sync.plan(SNAPS, allow={"BV1aaaaaaaa2"})
    assert {r["bvid"] for r in pl2["buckets"]["download"]} == {"BV1aaaaaaaa1", "BV1aaaaaaaa2", "BV1aaaaaaaa3", "BV1aaaaaaaa5"}
    # 勾了的 8 P 拆成 8 条；已入库的那几 P 算 hit
    pl3 = sync.plan(SNAPS, allow={"BV1aaaaaaaa6"}, in_library=lambda sid: sid in ("BV1aaaaaaaa6", "BV1aaaaaaaa6_p2"))
    got = [r["source_id"] for r in pl3["buckets"]["download"] if r["bvid"] == "BV1aaaaaaaa6"]
    assert got == [f"BV1aaaaaaaa6_p{n}" for n in range(3, 9)] and not pl3["buckets"]["multi_p"]
    assert {r["source_id"] for r in pl3["buckets"]["hit"]} >= {"BV1aaaaaaaa6", "BV1aaaaaaaa6_p2"}
    # ≤5 P 但总时长超过上限：整条进 long（勾了再拆）
    long_mp = sync.plan([{"media_id": 1, "title": "x", "items": [_item("BV1aaaaaaaa7", "长多P", 9000, page=2)]}])
    assert [r["bvid"] for r in long_mp["buckets"]["long"]] == ["BV1aaaaaaaa7"] and not long_mp["buckets"]["download"]


def test_pending_note_is_one_sentence_pointing_to_page():
    """1101 作者：清单里打勾显示成划线、还叫人敲命令行 / 找 Fable——改成一句话 + 指向「挑要下的视频」页。"""
    pl = sync.plan(SNAPS)
    out = {"buckets": {**pl["buckets"], "downloaded": [], "failed": [{"bvid": "BV1x"}]}, "counts": {**pl["counts"], "folders": 2, "downloaded": 3, "failed": 1},
           "bv_total": pl["bv_total"], "finished_at": "2026-10-29T03:00:00+11:00"}
    text = sync.render_pending_note(out, page="我的B站挑选.md")
    assert "有 2 个视频超过 1 小时或分 P 超过 5 个" in text and "[[我的B站挑选|挑要下的视频]]" in text and "选中想要的点「下载」" in text and "点「删除」（放进回收站" in text
    assert "没下成的 1 条不用管，下次同步会自动再试" in text and "本次新下 3 条" in text
    for bad in ("- [ ]", "--allow", "Fable", "命令行", "两小时讲座", "https://"):
        assert bad not in text, bad
    none = sync.render_pending_note({"buckets": {}, "counts": {}})
    assert "这次没有要挑的视频" in none and "[[B站挑选|挑要下的视频]]" in none


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    monkeypatch.setattr(ytdlp, "missing_tools", lambda: [])   # 1031：开跑前的缺下载器检查不看测试机装没装
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
    def fake_folder(client, mid_, **kw):   # 真的 sync_folder 会把快照落盘（「挑要下的视频」页只读本地快照）
        storage.write_json(favorites.snapshot_path(1234567, mid_), snaps[mid_])
        return {"snapshot": snaps[mid_], "diff": None, "relations": None, "summary": {}, "prev_complete_at": None}
    monkeypatch.setattr(favorites, "sync_folder", fake_folder)
    calls = []

    def fake_ingest(url, **kw):
        calls.append((url, kw.get("ingest_kind")))
        return {"item_id": "bili-" + url.rsplit("/", 1)[1], "hit": False, "manifest": {"media": []}}
    monkeypatch.setattr(ingest, "ingest_url", fake_ingest)
    committed = []
    monkeypatch.setattr(ingest, "after_commit", lambda src, sid, **k: committed.append(sid))
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: None)
    out = sync.run_sync(gap_s=0, log=lambda m: None)
    assert out["ok"] is True
    assert calls == [("https://www.bilibili.com/video/BV1aaaaaaaa1", "favorite"),
                     ("https://www.bilibili.com/video/BV1aaaaaaaa3", "favorite"), ("https://www.bilibili.com/video/BV1aaaaaaaa3?p=2", "favorite"),
                     ("https://www.bilibili.com/video/BV1aaaaaaaa3?p=3", "favorite"), ("https://www.bilibili.com/video/BV1aaaaaaaa5", "favorite")]
    assert committed == ["BV1aaaaaaaa1", "BV1aaaaaaaa3", "BV1aaaaaaaa3_p2", "BV1aaaaaaaa3_p3", "BV1aaaaaaaa5"]   # 按 P 的 source_id 收尾
    assert out["counts"]["downloaded"] == 5 and out["counts"]["long"] == 1 and out["counts"]["multi_p"] == 1
    note = sync.pending_note_path()
    assert note.is_file() and "[[B站挑选|挑要下的视频]]" in note.read_text(encoding="utf-8")
    assert note.parent.name == "Bilibili"
    # 1101：同步完写出「挑要下的视频」页和它的数据
    page = storage.vault_root() / "B站挑选.md"
    assert page.read_text(encoding="utf-8").startswith("---\nlb-page: bili-pending\ncssclasses: [lb-bilipage]\n---\n")
    assert "bili-pending-page.js" in page.read_text(encoding="utf-8")
    pdata = storage.read_json(favorites.sync_root() / "pending-data.json")
    assert [(r["bvid"], r["kind"]) for r in pdata["items"]] == [("BV1aaaaaaaa2", "long"), ("BV1aaaaaaaa6", "multi")]
    last = storage.read_json(favorites.sync_root() / "last-sync.json")
    assert last["counts"]["downloaded"] == 5 and "SESSDATA" not in str(last)
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
    # 1031：停下来带具体细分码（设置页按码给下一步），不再是笼统的 NEEDS_HUMAN
    assert out["ok"] is False and out["code"] == "NOT_LOGGED_IN" and "要人处理" in out["stopped"]
    assert "扫码登录" in out["message"]
    assert out["counts"]["failed"] == 1 and out["counts"]["not_reached"] == 1


def test_run_sync_requires_login(vault, monkeypatch):
    class Client:
        def close(self):
            pass
    monkeypatch.setattr(favorites, "default_client", lambda: (Client(), {"state": "logged_out", "detail": "没登录"}))
    out = sync.run_sync(log=lambda m: None)
    assert out["ok"] is False and out["code"] == "NOT_LOGGED_IN"


def test_run_sync_stops_before_scanning_when_ytdlp_missing(vault, monkeypatch):
    """1031：.venv 里没装 yt-dlp 时，开跑前就停、不连 B 站；上次的进度和计数留着，原因换成人话。"""
    storage.write_json(favorites.sync_root() / "last-sync.json",
                       {"state": "stopped", "stopped": "要人处理（MISSING_DEPENDENCY）：NeedsHuman: 旧的整段报错 D:/x/python.exe",
                        "counts": {"failed": 1, "multi_p": 106}, "progress": {"done": 1, "total": 819}, "code": "MISSING_DEPENDENCY"})
    monkeypatch.setattr(ytdlp, "missing_tools", lambda: ["yt-dlp"])
    monkeypatch.setattr(favorites, "default_client", lambda: pytest.fail("缺下载器时不该去连 B 站"))
    out = sync.run_sync(gap_s=0, log=lambda m: None)
    assert out["ok"] is False and out["code"] == "MISSING_DEPENDENCY"
    # 1102：装法是 extras 那一句（yt-dlp 在 `bilibili` 功能包里），不再叫人 pip install -e .
    assert "yt-dlp" in out["stopped"] and "uv pip install link-brain[bilibili]" in out["stopped"]
    assert "pip install -e ." not in out["message"] and "立即同步" in out["message"]
    for text in (out["stopped"], out["message"]):
        assert "NeedsHuman" not in text and "python.exe" not in text and "No module" not in text
    last = storage.read_json(favorites.sync_root() / "last-sync.json")
    assert last["stopped"] == out["stopped"] and last["state"] == "stopped"
    assert last["progress"] == {"done": 1, "total": 819} and last["counts"]["multi_p"] == 106


def test_missing_dependency_from_ytdlp_is_plain_words(vault, monkeypatch):
    """yt-dlp 子进程报 No module named yt_dlp：停下的原因不带类名、退出码和解释器路径。"""
    from link_brain import ingest, catalog
    from link_brain.sources.bilibili import login

    class Client:
        def close(self):
            pass
    monkeypatch.setattr(favorites, "default_client", lambda: (Client(), {"state": "logged_in"}))
    monkeypatch.setattr(login, "my_mid", lambda client=None: 1)
    monkeypatch.setattr(favorites, "list_folders", lambda client, mid: {
        "status": "ok", "folders": [{"media_id": 11, "fid": 1, "owner_mid": 1, "title": "音乐", "private": False, "media_count": 1}]})
    snap = {"media_id": 11, "owner_mid": 1, "title": "音乐", "complete": True, "status": "complete",
            "items": [_item("BV1aaaaaaaa1", "一", 100)]}
    monkeypatch.setattr(favorites, "sync_folder", lambda *a, **k: {"snapshot": snap, "diff": None, "relations": None, "summary": {}, "prev_complete_at": None})
    monkeypatch.setattr(ytdlp, "ffmpeg_ok", lambda: True)
    monkeypatch.setattr(login, "status", lambda **k: {"state": "logged_in"}, raising=False)
    monkeypatch.setattr(ytdlp, "run", lambda *a, **k: {"exit_code": 1, "files": {"video": None}, "dir": vault / "nope",
                                                       "stderr_tail": r"D:\LWA\.venv\Scripts\python.exe: No module named yt_dlp"})
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: None)
    out = sync.run_sync(gap_s=0, workers=1, tv=False, log=lambda m: None)
    assert out["code"] == "MISSING_DEPENDENCY", out
    assert out["stopped"].startswith("要人处理：缺下载器 yt-dlp")
    assert "要用 B 站下载，先装 `uv pip install link-brain[bilibili]`" in out["stopped"]
    assert "NeedsHuman" not in out["stopped"] and "python.exe" not in out["stopped"] and "退出码" not in out["stopped"]


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
    assert sync.choose(undo=["BV1aaaaaaaa2"])["undone"] == ["BV1aaaaaaaa2"]
    assert "BV1aaaaaaaa2" not in sync.load_choices()["allow"]


def test_prefetch_runs_downloads_in_parallel_and_run_reuses_them(tmp_path, monkeypatch):
    """1029：并行只并行 yt-dlp；run() 领到后台下好的结果，不再重下；没人领的被清掉。"""
    import threading
    import time as _t
    from link_brain.sources.bilibili import ytdlp
    live, peak, lock = [0], [0], threading.Lock()

    def fake_download(url, **kw):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        _t.sleep(0.2)
        with lock:
            live[0] -= 1
        d = tmp_path / url.rsplit("/", 2)[-2]
        d.mkdir(exist_ok=True)
        return {"dir": d, "cookies_used": True, "duration_s": 0.2, "url": url, "fresh": False}
    monkeypatch.setattr(ytdlp, "_download", lambda url, **kw: fake_download(url, **kw))
    urls = [ytdlp.download_url(f"BV1bbbbbbbb{i}") for i in range(4)]
    ytdlp.prefetch_start(4)
    try:
        assert all(ytdlp.prefetch(u) for u in urls) and not ytdlp.prefetch(urls[0])   # 同一条不排两次
        got = ytdlp.run(urls[0])
        assert got["url"] == urls[0] and got["fresh"] is False
        assert ytdlp.run(urls[1])["url"] == urls[1]
    finally:
        ytdlp.prefetch_stop()
    assert peak[0] >= 2                       # 真的同时在下
    _t.sleep(0.5)
    assert not (tmp_path / "BV1bbbbbbbb3").exists()   # 下完没人领 → 清掉
    # 没开池时 run() 就是原来那样现下
    monkeypatch.setattr(ytdlp, "_download", lambda url, **kw: {"dir": tmp_path, "cookies_used": True, "duration_s": 0, "url": url, "fresh": True})
    assert ytdlp.run(urls[2])["fresh"] is True


def test_run_sync_parallel_prefetches_ahead_and_falls_back_on_rate_limit(vault, monkeypatch):
    from link_brain import ingest, catalog, sources
    from link_brain.sources.bilibili import login, ytdlp

    class Client:
        def close(self):
            pass
    many = [{"media_id": 21, "title": "多", "items": [_item(f"BV1cccccccc{i}", f"v{i}", 60, fav_time=10 - i) for i in range(6)]}]
    monkeypatch.setattr(favorites, "default_client", lambda: (Client(), {"state": "logged_in"}))
    monkeypatch.setattr(login, "my_mid", lambda client=None: 1)
    monkeypatch.setattr(favorites, "list_folders", lambda client, mid: {
        "status": "ok", "folders": [{"media_id": 21, "fid": 1, "owner_mid": mid, "title": "多", "private": False, "media_count": 6}]})
    snap = {**many[0], "owner_mid": 1, "complete": True, "status": "complete", "fetched_at": "t"}
    monkeypatch.setattr(favorites, "sync_folder", lambda client, mid_, **kw: {"snapshot": snap, "diff": None, "relations": None,
                                                                             "summary": {}, "prev_complete_at": None})
    queued = []
    monkeypatch.setattr(ytdlp, "prefetch", lambda url: queued.append(url) or True)
    seen = []

    def fake_ingest(url, **kw):
        seen.append(url)
        if len(seen) == 2:
            err = sources.SourceError("B 站限流")
            err.code = "HTTP_429"
            raise err
        return {"item_id": "bili-" + url.rsplit("/", 1)[1], "hit": False, "manifest": {"media": []}}
    monkeypatch.setattr(ingest, "ingest_url", fake_ingest)
    monkeypatch.setattr(ingest, "after_commit", lambda *a, **k: None)
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: None)
    logs = []
    out = sync.run_sync(gap_s=0, workers=3, log=logs.append, sleep=lambda s: None)
    assert len(seen) == 6                                   # 入库仍一条一条走完
    assert queued[:4] == [ytdlp.download_url(f"BV1cccccccc{i}") for i in range(4)]   # 第一条时先排 workers+1 条
    assert any("退回一条一条下" in m for m in logs)
    # 每条都把后面 workers+1 条的窗口再递一遍（真 prefetch 去重）；第 2 条撞限流后就不再往后排
    assert len(queued) == 8 and set(queued) == {ytdlp.download_url(f"BV1cccccccc{i}") for i in range(5)}
    assert out["counts"]["downloaded"] == 5 and out["counts"]["failed"] == 1


def test_long_list_for_picking(monkeypatch):
    """1031 作者：超过时长上限、还没入库的列出来让用户勾；已放行的标 chosen；失效 / 多 P / 已入库 / 删掉的不列；只读本地快照。"""
    from link_brain import index as index_mod
    root = favorites.sync_root() / "folders"
    root.mkdir(parents=True, exist_ok=True)
    storage.write_json(root / "1-10.json", {"title": "学习", "media_id": 10, "items": [
        _item("BV1long1", "长课", duration=7200), _item("BV1long2", "长剧", duration=5000),
        _item("BV1short", "短", duration=60), _item("BV1dead", "失效", duration=9000, invalid=True),
        _item("BV1multi", "多P", duration=9000, page=8), _item("BV1have", "已入库", duration=9000), _item("BV1gone", "删了", duration=9000)]})
    storage.write_json(root / "1-10.last-complete.json", {"title": "旧的", "items": [_item("BV1old", "不该读", duration=9000)]})
    storage.write_json(sync.choices_path(), {"allow": {"BV1long2": {}}, "deny": {"BV1gone": {}}})

    class Conn:
        def close(self):
            pass
    monkeypatch.setattr(index_mod, "connect", lambda: Conn())
    monkeypatch.setattr(index_mod, "find_object", lambda conn, src, bv: {} if bv == "BV1have" else None)
    out = sync.long_list(max_duration_s=3600)
    assert [r["bvid"] for r in out["items"]] == ["BV1long1", "BV1long2"]   # 没选的在前、长的在前
    assert [r["chosen"] for r in out["items"]] == [False, True]
    assert out["total"] == 2 and out["chosen"] == 1
    assert out["items"][0]["duration_text"] and out["items"][0]["folders"] == ["学习"]


def test_multi_list_for_picking(vault, monkeypatch):
    """1031 作者：多于 5 P 的列进挑选页；勾过的标 chosen，已下了几 P 照实给；≤5 P 的不列（同步时自动拆开下）。"""
    from link_brain import index as index_mod
    root = favorites.sync_root() / "folders"
    root.mkdir(parents=True, exist_ok=True)
    storage.write_json(root / "1-10.json", {"title": "课", "media_id": 10, "items": [
        _item("BV1six", "六P", duration=600, page=6), _item("BV1ten", "十P", duration=900, page=10), _item("BV1three", "三P", page=3)]})
    storage.write_json(sync.choices_path(), {"allow": {"BV1ten": {}}, "deny": {}})

    class Conn:
        def close(self):
            pass
    monkeypatch.setattr(index_mod, "connect", lambda: Conn())
    monkeypatch.setattr(index_mod, "find_object", lambda conn, src, sid: {} if sid in ("BV1ten", "BV1ten_p2") else None)
    out = sync.multi_list()
    assert [(r["bvid"], r["page_count"], r["chosen"], r["done"]) for r in out["items"]] == [("BV1six", 6, False, 0), ("BV1ten", 10, True, 2)]
    assert out["auto_max"] == 5 and out["chosen"] == 1


def test_part_title_from_ytdlp():
    assert bili._part_title("合集 p02 第二讲", {"id": "BV1x_p2"}) == "合集 · P2 第二讲"
    assert bili._part_title("合集 p01", {"id": "BV1x_p1"}) == "合集 · P1"
    assert bili._part_title("歌名 p02 现场", {"id": "BV1x"}) == "歌名 p02 现场"   # 单 P 的标题碰巧带 p02：不动
