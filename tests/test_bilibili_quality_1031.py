"""B 站 1031：画质档 / 不存弹幕 / 预估 / 电视端（无水印）取流 / 断点续跑 / 待选清单只提醒多 P。
全部离线：yt-dlp、电视端接口、ffmpeg 都是替身；电视端响应用 fixtures/bilibili_tv_playurl.json（按接口形状合成）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from link_brain import storage
from link_brain.sources import bilibili as bili
from link_brain.sources.bilibili import favorites, login, sync, tvapi, ytdlp

FIX = Path(__file__).parent / "fixtures"
BV = "BV1AbCdEfGhJ"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    monkeypatch.setattr(login, "has_cookies", lambda: False)
    return tmp_path


# ---- 画质档 / 弹幕 -----------------------------------------------------------------------------------------------------

def test_quality_tiers_and_danmaku_flag_in_argv(vault):
    assert ytdlp.normalize_quality("1080p") == "1080" and ytdlp.normalize_quality("MAX") == "max"
    assert ytdlp.normalize_quality("bogus") == "max" and ytdlp.normalize_quality(None) == "max"
    url = ytdlp.download_url(BV)
    a_max = ytdlp.build_argv(url, Path("o"), cookies=None, quality="max", danmaku=True)
    f, s = a_max[a_max.index("-f") + 1], a_max[a_max.index("-S") + 1]
    assert "dynamic_range!=?DV" in f and "vcodec!^=?dvh" in f and s == "res,fps,vcodec"
    assert a_max[a_max.index("--sub-langs") + 1] == "all"
    a_1080 = ytdlp.build_argv(url, Path("o"), cookies=None, quality="1080", danmaku=False)
    assert a_1080[a_1080.index("-f") + 1] == ytdlp.FORMAT and a_1080[a_1080.index("-S") + 1] == "res:1080"   # 1080 档 = 原来的行为
    assert a_1080[a_1080.index("--sub-langs") + 1] == "all,-danmaku"
    a_720 = ytdlp.build_argv(url, Path("o"), cookies=None, quality="720")
    assert a_720[a_720.index("-S") + 1] == "res:720"


def test_configure_sets_and_restores_module_options():
    prev = ytdlp.configure(quality="720", danmaku=False, tv=False)
    try:
        argv = ytdlp.build_argv("https://x/video/BV1AbCdEfGhJ/", Path("o"), cookies=None)
        assert argv[argv.index("-S") + 1] == "res:720" and argv[argv.index("--sub-langs") + 1] == "all,-danmaku"
    finally:
        ytdlp.configure(**prev)
    assert ytdlp.OPTIONS == prev


def test_default_quality_is_max_unless_env(monkeypatch):
    import importlib
    monkeypatch.delenv("LWA_BILI_QUALITY", raising=False)
    assert importlib.reload(ytdlp).DEFAULT_QUALITY == "max"
    monkeypatch.setenv("LWA_BILI_QUALITY", "720")
    try:
        assert importlib.reload(ytdlp).DEFAULT_QUALITY == "720"
    finally:
        monkeypatch.delenv("LWA_BILI_QUALITY")
        importlib.reload(ytdlp)


def test_max_tier_picks_best_playable_format_offline():
    """真 yt-dlp 的选择器跑在假格式表上（不联网）：max 拿 4K AV1、不碰杜比视界；1080 / 720 档照旧 AVC。"""
    yt_dlp = pytest.importorskip("yt_dlp")

    def v(fid, h, codec, dr=None, tbr=1000):
        return {"format_id": fid, "url": "http://x/" + fid, "ext": "mp4", "width": h * 16 // 9, "height": h, "vcodec": codec,
                "acodec": "none", "fps": 30, "dynamic_range": dr, "tbr": tbr, "protocol": "https"}
    fmts = [v("30080", 1080, "avc1.640032", tbr=2000), v("30077", 1080, "hev1.1.6.L150.90", tbr=1200),
            v("30064", 720, "avc1.640028"), v("30120", 2160, "avc1.640034", tbr=8000),
            v("30121", 2160, "hev1.1.6.L153.90", tbr=6000), v("100050", 2160, "av01.0.12M.10", tbr=5000),
            v("30126", 2160, "dvh1.08.09", dr="DV", tbr=12000),
            {"format_id": "30280", "url": "http://x/a", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "tbr": 192,
             "protocol": "https"}]

    def pick(q, drop=()):
        f, s = ytdlp.QUALITY_ARGS[q]
        ydl = yt_dlp.YoutubeDL({"format": f, "format_sort": s.split(","), "quiet": True, "simulate": True})
        info = ydl.process_ie_result({"id": BV, "title": "t", "formats": [dict(x) for x in fmts if x["format_id"] not in drop],
                                      "extractor": "x", "webpage_url": "http://x"}, download=False)
        return info["format_id"]
    assert pick("max") == "100050+30280"
    assert pick("max", drop=("100050",)) == "30121+30280"            # 没 AV1 → HEVC
    assert pick("max", drop=("100050", "30121", "30120")) == "30077+30280"   # 只剩杜比视界的 4K → 不要它，退 1080（HEVC 优先）
    assert pick("1080") == "30080+30280" and pick("720") == "30064+30280"


def test_skipped_danmaku_is_recorded_as_skipped_not_failed(vault, monkeypatch, tmp_path):
    d = tmp_path / "dl"
    d.mkdir()
    (d / f"{BV}.mp4").write_bytes(b"\0" * 2048)
    res = {"dir": d, "exit_code": 0, "argv": [], "cookies_used": False, "stderr_tail": "", "duration_s": 1.0,
           "need_login_subtitle": False, "stdout_tail": "", "quality": "max", "danmaku_wanted": False, "stream": "web",
           "tv": None, "tv_error": None, "info": {"title": "t"},
           "files": {"video": d / f"{BV}.mp4", "cover": None, "danmaku": None, "subtitles": []}}
    monkeypatch.setattr(ytdlp, "version", lambda: "0.test")
    parsed = bili.parse(f"https://www.bilibili.com/video/{BV}")
    fetched = bili.Fetched(raw_files={"ytdlp_info.json": {"title": "t"}},
                           context={"download": res, "probe": {"ok": True, "duration_sec": 10}, "login_state": "anonymous"})
    doc = bili.normalize(fetched, parsed, captured_at="2026-10-31T00:00:00+11:00")
    assert doc["note"]["danmaku"]["status"] == "skipped"
    assert doc["capture"]["downloader"]["quality"] == "max" and doc["capture"]["downloader"]["stream"] == "web"
    tasks = {t["role"]: t for t in bili.media_plan(doc, {})}
    assert tasks["danmaku"]["payload"]["status"] == "skipped"


# ---- 预估 ------------------------------------------------------------------------------------------------------------

ROWS = [{"duration": 600}, {"duration": 1200}, {"duration": 0}]


def test_estimate_uses_library_samples_for_same_quality():
    mb = 1 << 20
    samples = [{"bytes": 20 * mb * m, "duration_s": 60.0 * m, "seconds": 100.0 * m, "quality": "1080"} for m in (1, 2, 3, 4)]
    e = sync.estimate(ROWS, quality="1080", workers=2, gap_s=5, samples=samples)
    assert e["count"] == 3 and e["total_duration_s"] == 1800 and e["unknown_duration"] == 1 and e["estimated"] is True
    assert e["bytes_per_min"]["low"] == e["bytes_per_min"]["high"] == 20 * mb       # 每分钟 20 MB
    assert e["size_bytes"]["low"] == 30 * 20 * mb
    one = 20 * mb * 1 / 100.0                                                         # 单路 bytes / 秒
    assert abs(e["speed_bps"]["low"] - 2 * one) < 2
    assert e["eta_s"]["low"] >= 3 * (5 + sync.INGEST_OVERHEAD_S) and "1 条不知道时长" in e["note"]
    assert "1080p" in e["basis"]["size"] and "下载耗时实测" in e["basis"]["speed"]


def test_estimate_scales_from_1080_and_falls_back_to_state_speed():
    mb = 1 << 20
    samples = [{"bytes": 20 * mb, "duration_s": 60.0, "seconds": None, "quality": "1080"} for _ in range(3)]
    e720 = sync.estimate(ROWS, quality="720", samples=samples)
    assert e720["bytes_per_min"]["high"] < 20 * mb and "换算" in e720["basis"]["size"]
    emax_vip = sync.estimate(ROWS, quality="max", samples=samples, vip=True, workers=3)
    assert emax_vip["bytes_per_min"]["high"] == int(20 * mb * 4.0) and "4K" in emax_vip["basis"]["size"]
    assert emax_vip["speed_bps"] == {"low": 130 * 1024 * 3, "high": 430 * 1024 * 3} and "130–430 KB/s" in emax_vip["basis"]["speed"]
    bare = sync.estimate(ROWS, quality="max", samples=[])
    assert "粗估" in bare["basis"]["size"]


def test_library_samples_reads_raw_manifest_and_capture(vault):
    for i, (q, secs) in enumerate([(None, 50.0), ("max", 80.0)]):
        sid = f"BV1AbCdEfGh{i}"
        raw = storage.raw_dir("bilibili", sid, 1)
        raw.mkdir(parents=True)
        storage.write_json(raw / "manifest.json", {"media": [{"role": "video", "download_status": "ok", "bytes": 1000, "duration_sec": 60}]})
        storage.write_json(raw / "source.json", {"capture": {"downloader": {"seconds": secs, **({"quality": q} if q else {})}}})
    got = sorted(sync.library_samples(), key=lambda s: s["seconds"])
    assert [s["quality"] for s in got] == ["1080", "max"] and got[0]["bytes"] == 1000 and got[1]["seconds"] == 80.0


# ---- 电视端（无水印）取流 --------------------------------------------------------------------------------------------

class Resp:
    def __init__(self, payload=None, status=200, content=b"", headers=None):
        self._p, self.status_code, self.content, self.headers = payload, status, content, headers or {}

    def json(self):
        return self._p


class FakeClient:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def get(self, url, params=None, headers=None):
        self.calls.append(("GET", url, params, headers))
        return self.handler("GET", url, params, headers)

    def post(self, url, data=None):
        self.calls.append(("POST", url, data, None))
        return self.handler("POST", url, data, None)

    def close(self):
        pass


def test_signed_sorts_params_and_appends_md5():
    import hashlib
    out = tvapi.signed({"ts": 1, "appkey": tvapi.APPKEY, "cid": 2})
    assert list(out) == ["appkey", "cid", "ts", "sign"]
    assert out["sign"] == hashlib.md5(f"appkey={tvapi.APPKEY}&cid=2&ts=1{tvapi.APPSEC}".encode()).hexdigest()


def test_pick_prefers_highest_non_dv_and_codec_order_per_tier():
    body = json.loads((FIX / "bilibili_tv_playurl.json").read_text(encoding="utf-8"))["data"]
    m = tvapi.pick(body, "max")
    assert m["qn"] == 120 and m["codec"] == "av1" and m["audio"]["id"] == 30280      # 杜比视界 126 不要；4K 里 AV1 优先
    p1080 = tvapi.pick(body, "1080")
    assert p1080["qn"] == 116 and p1080["codec"] == "avc"                              # 1080 档：不超 1080、AVC 优先
    p720 = tvapi.pick(body, "720")
    assert p720["qn"] == 64 and p720["codec"] == "avc"
    assert tvapi.pick({"dash": {"video": [{"id": 126, "base_url": "https://x", "codecid": 12}], "audio": []}}, "max") is None


def test_playurl_reads_data_or_root_and_marks_token_invalid(vault):
    body = json.loads((FIX / "bilibili_tv_playurl.json").read_text(encoding="utf-8"))
    c = FakeClient(lambda *a: Resp(body))
    got = tvapi.playurl(1, 2, token="tok", client=c)
    assert got["quality"] == 127
    _, url, params, _ = c.calls[0]
    assert url == tvapi.TV_PLAYURL and params["access_key"] == "tok" and params["mobi_app"] == "android_tv_yst"
    assert params["object_id"] == "1" and params["fourk"] == "1" and len(params["sign"]) == 32
    root = {"code": 0, **body["data"]}                     # 有的版本直接回在根上
    assert tvapi.playurl(1, 2, token=None, client=FakeClient(lambda *a: Resp(root)))["dash"]["video"]
    tvapi.save_token({"access_token": "tok", "expires_in": 3600})
    with pytest.raises(tvapi.TvError) as ei:
        tvapi.playurl(1, 2, token="tok", client=FakeClient(lambda *a: Resp({"code": -101, "message": "账号未登录"})))
    assert ei.value.code == "NEEDS_HUMAN.NOT_LOGGED_IN" and tvapi.token_status()["state"] == "expired"
    with pytest.raises(tvapi.TvError) as ei:
        tvapi.playurl(1, 2, token=None, client=FakeClient(lambda *a: Resp({"code": -412})))
    assert ei.value.code == "TRANSIENT.HTTP_429"


def test_token_status_and_store_never_print_token(vault, capsys):
    assert tvapi.token_status()["state"] == "logged_out" and tvapi.usable_token() is None
    tvapi.save_token({"access_token": "SECRET-TOKEN", "refresh_token": "R", "expires_in": 86400 * 30, "mid": 1})
    st = tvapi.token_status()
    assert st["state"] == "logged_in" and "SECRET-TOKEN" not in json.dumps(st) and tvapi.usable_token() == "SECRET-TOKEN"
    assert tvapi.token_status(now=st["expires_at"] + 1)["state"] == "expired"
    assert str(storage.link_brain_home()) in str(tvapi.token_path())
    assert tvapi.clear_token() is True and tvapi.token_status()["state"] == "logged_out"


def test_tv_qr_login_polls_until_token(vault):
    seq = iter([{"code": tvapi.QR_WAITING}, {"code": tvapi.QR_SCANNED},
                {"code": 0, "data": {"access_token": "AT", "refresh_token": "RT", "expires_in": 100000, "mid": 9}}])

    def handler(method, url, data, _h):
        if url == tvapi.TV_QR_AUTH:
            assert data["appkey"] == tvapi.APPKEY and data["sign"]
            return Resp({"code": 0, "data": {"url": "https://passport.example/qr?x=1", "auth_code": "AC"}})
        assert url == tvapi.TV_QR_POLL and data["auth_code"] == "AC"
        return Resp(next(seq))
    import io
    buf = io.StringIO()
    st = tvapi.qr_login(timeout_s=30, out=buf, client=FakeClient(handler), sleep=lambda s: None)
    assert st["state"] == "logged_in" and tvapi.usable_token() == "AT" and "AT" not in buf.getvalue().replace("AC", "")


def test_fetch_stream_ranges_and_falls_back_to_backup(tmp_path):
    data = bytes(range(256)) * 100   # 25600 字节

    def handler(method, url, params, headers):
        if "bad" in url:
            return Resp(status=403)
        a, b = headers["Range"].split("=")[1].split("-")
        a, b = int(a), min(int(b), len(data) - 1)
        return Resp(status=206, content=data[a:b + 1], headers={"content-range": f"bytes {a}-{b}/{len(data)}"})
    import time as _t
    old = tvapi.CHUNK_BYTES
    tvapi.CHUNK_BYTES = 10000
    try:
        n = tvapi.fetch_stream(["https://bad.example/v", "https://ok.example/v"], tmp_path / "v.m4s", client=FakeClient(handler),
                               deadline=_t.monotonic() + 60)
    finally:
        tvapi.CHUNK_BYTES = old
    assert n == len(data) and (tmp_path / "v.m4s").read_bytes() == data and not (tmp_path / "v.m4s.part").exists()


def test_collect_files_derives_aid_cid_from_raw_info(tmp_path):
    """yt-dlp 的 B 站 info 没有 aid / cid 键：从 _old_archive_ids 和弹幕地址补（电视端取流要用，不必再查 view 接口）。"""
    (tmp_path / f"{BV}.info.json").write_text(json.dumps({
        "id": BV, "_old_archive_ids": ["bilibili 170001_part1"],
        "subtitles": {"danmaku": [{"ext": "xml", "url": "https://comment.bilibili.com/279786.xml"}]}}), encoding="utf-8")
    info = ytdlp.collect_files(tmp_path)["info"]
    assert info["aid"] == 170001 and info["cid"] == 279786
    web = FakeClient(lambda *a: pytest.fail("有 aid / cid 就不该查 view 接口"))
    assert tvapi.ids_for(BV, 1, info, client=web) == (170001, 279786)
    view = {"code": 0, "data": {"aid": 5, "cid": 6, "pages": [{"cid": 6}, {"cid": 7}]}}
    assert tvapi.ids_for(BV, 2, {}, client=FakeClient(lambda *a: Resp(view))) == (5, 7)


def _fake_ytdlp(calls):
    def fake(argv, out_dir, timeout_s):
        calls.append(list(argv))
        (out_dir / f"{BV}.info.json").write_text(json.dumps({"id": BV, "aid": 11, "cid": 22, "title": "t"}), encoding="utf-8")
        (out_dir / f"{BV}.zh-CN.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n字\n\n", encoding="utf-8")
        if "--skip-download" not in argv:
            (out_dir / f"{BV}.mp4").write_bytes(b"web" * 1000)
        return 0, "", ""
    return fake


def test_download_prefers_tv_stream_and_keeps_subs_from_ytdlp(vault, monkeypatch):
    calls: list = []
    monkeypatch.setattr(ytdlp, "_ytdlp", _fake_ytdlp(calls))
    monkeypatch.setattr(tvapi, "usable_token", lambda: "tok")

    def fake_tv(bvid, page, out_dir, *, quality, info, token, timeout_s, log, **kw):
        assert bvid == BV and page == 1 and info["aid"] == 11 and token == "tok" and quality == "max"
        (out_dir / f"{bvid}.mp4").write_bytes(b"tv" * 1000)
        return {"ok": True, "file": out_dir / f"{bvid}.mp4", "qn": 120, "label": "4K", "codec": "av1", "bytes": 2000}
    monkeypatch.setattr(tvapi, "download", fake_tv)
    res = ytdlp._download(ytdlp.download_url(BV))
    assert len(calls) == 1 and "--skip-download" in calls[0] and calls[0][-1].endswith(f"/{BV}/")
    assert res["stream"] == "tv" and res["tv"]["label"] == "4K" and res["files"]["video"].read_bytes().startswith(b"tvtv")
    assert res["files"]["subtitles"] and res["tv_error"] is None


def test_download_falls_back_to_web_when_tv_fails_or_off(vault, monkeypatch):
    calls: list = []
    monkeypatch.setattr(ytdlp, "_ytdlp", _fake_ytdlp(calls))
    monkeypatch.setattr(tvapi, "usable_token", lambda: "tok")

    def boom(*a, **k):
        raise tvapi.TvError("电视端没有合适的视频流")
    monkeypatch.setattr(tvapi, "download", boom)
    res = ytdlp._download(ytdlp.download_url(BV))
    assert res["stream"] == "web" and "没有合适" in res["tv_error"] and res["files"]["video"].read_bytes().startswith(b"web")
    assert "--skip-download" in calls[0] and "--skip-download" not in calls[1]
    calls.clear()
    prev = ytdlp.configure(tv=False)
    try:
        res = ytdlp._download(ytdlp.download_url(BV))
    finally:
        ytdlp.configure(**prev)
    assert len(calls) == 1 and "--skip-download" not in calls[0] and res["stream"] == "web" and res["tv_error"] is None


# ---- 待选清单只提醒多 P；时长 0 = 不限 ----------------------------------------------------------------------------------

def _item(bvid, title, duration=600, page=1, invalid=False):
    return {"bvid": bvid, "kind": "video", "title": title, "fav_time": 1, "invalid": invalid, "page_count": page,
            "upper_name": "UP", "duration": duration}


SNAPS = [{"media_id": 1, "title": "夹", "items": [_item("BV1aaaaaaaa1", "短", 100), _item("BV1aaaaaaaa2", "长讲座", 7300),
                                                   _item("BV1aaaaaaaa3", "三P", 300, page=3), _item("BV1aaaaaaaa4", "失效", invalid=True)]}]


def test_pending_note_only_flags_multi_p_and_moves_long_invalid_to_details():
    pl = sync.plan(SNAPS)
    out = {"buckets": {**pl["buckets"], "downloaded": [], "failed": []}, "counts": {**pl["counts"], "folders": 1},
           "bv_total": pl["bv_total"], "options": {"max_duration_s": 3600}}
    text = sync.render_pending_note(out)
    head, details = text.split("# 明细（不用处理，只是查得到）")
    assert "多 P 待选 1" in head and "## 多 P 视频" in head and "三P" in head
    assert "长讲座" not in head and "失效" not in head.split("---", 2)[-1].split("下面这些")[0]
    assert "## 超过 1 小时" in details and "长讲座" in details and "## 原站已失效" in details


def test_max_duration_zero_means_unlimited():
    pl = sync.plan(SNAPS, max_duration_s=0)
    assert "BV1aaaaaaaa2" in {r["bvid"] for r in pl["buckets"]["download"]} and not pl["buckets"]["long"]


# ---- 断点续跑 ---------------------------------------------------------------------------------------------------------

def _client_setup(monkeypatch, snap):
    class Client:
        def close(self):
            pass
    monkeypatch.setattr(favorites, "default_client", lambda: (Client(), {"state": "logged_in", "vip": True}))
    monkeypatch.setattr(login, "my_mid", lambda client=None: 1)
    monkeypatch.setattr(favorites, "list_folders", lambda client, mid: {
        "status": "ok", "folders": [{"media_id": 1, "fid": 1, "owner_mid": 1, "title": "夹", "private": False, "media_count": 4}]})
    monkeypatch.setattr(favorites, "sync_folder", lambda *a, **k: {"snapshot": {**snap, "owner_mid": 1, "complete": True,
                                                                                "status": "complete", "fetched_at": "t"}})


def test_dry_run_has_estimate_and_options(vault, monkeypatch):
    _client_setup(monkeypatch, SNAPS[0])
    monkeypatch.setattr(sync, "library_samples", lambda: [])
    out = sync.run_sync(dry_run=True, quality="1080", workers=3, danmaku=False, log=lambda m: None)
    assert out["ok"] and out["estimate"]["count"] == 1 and out["estimate"]["workers"] == 3
    assert out["options"] == {**out["options"], "quality": "1080", "danmaku": False, "workers": 3, "vip": True}
    assert "估计" in out["message"] and "超过" not in out["message"] and "多 P 的 1 条" in out["message"]
    assert ytdlp.OPTIONS["quality"] == ytdlp.DEFAULT_QUALITY and ytdlp.OPTIONS["danmaku"] is True   # 跑完复原


def test_interrupted_run_is_reported_and_tmp_cleaned(vault, monkeypatch):
    from link_brain import catalog, ingest
    _client_setup(monkeypatch, SNAPS[0])
    root = ytdlp.tmp_root()
    root.mkdir(parents=True, exist_ok=True)
    dead = root / "dl-20261029T201200-999991-abcdef"
    dead.mkdir()
    (dead / "x.mp4.part").write_bytes(b"half")
    mine = root / f"dl-20261031T000000-{os.getpid()}-123456"
    mine.mkdir()
    monkeypatch.setattr(storage, "pid_state", lambda pid: "alive" if int(pid) == os.getpid() else "dead")
    seen = []

    def fake_ingest(url, **kw):
        seen.append(url)
        raise KeyboardInterrupt   # 模拟第一条下到一半进程被结束（走不到收尾）
    monkeypatch.setattr(ingest, "ingest_url", fake_ingest)
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: None)
    with pytest.raises(KeyboardInterrupt):
        sync.run_sync(gap_s=0, log=lambda m: None)
    assert not dead.exists() and mine.exists()
    last = storage.read_json(favorites.sync_root() / "last-sync.json") if (favorites.sync_root() / "last-sync.json").exists() else None
    # 第一条就被打断：还没写过进度，摘要说没同步过；造一份「跑到第 349 条被结束」的进度文件再看摘要
    storage.write_json(favorites.sync_root() / "last-sync.json",
                       {"state": "running", "pid": 999991, "started_at": "2026-10-29T18:00:00+11:00",
                        "counts": {"downloaded": 340, "failed": 9, "long": 11, "invalid": 66, "multi_p": 73},
                        "progress": {"done": 349, "total": 849}})
    s = sync.last_summary()
    assert last is None or last.get("state") == "running"
    assert s["state"] == "interrupted" and s["code"] == "INTERRUPTED" and "349/849" in s["message"]
    assert "再点「立即同步」只补没下的" in s["message"] and s["details"] == {"long": 11, "invalid": 66, "non_video": 0, "denied": 0}
    assert s["multi_p"] == 73 and s["pending_note"].endswith("B站待选清单.md")


def test_resume_only_downloads_what_is_not_in_library(vault, monkeypatch):
    from link_brain import catalog, index as index_mod, ingest
    _client_setup(monkeypatch, {"media_id": 1, "title": "夹", "items": [_item("BV1aaaaaaaa1", "一", 100), _item("BV1aaaaaaaa5", "二", 100)]})
    monkeypatch.setattr(index_mod, "find_object", lambda conn, src, bv: {"x": 1} if bv == "BV1aaaaaaaa1" else None)
    got = []
    monkeypatch.setattr(ingest, "ingest_url", lambda url, **kw: got.append(url) or {"item_id": "bili-x", "manifest": {"media": []}})
    monkeypatch.setattr(ingest, "after_commit", lambda *a, **k: None)
    monkeypatch.setattr(catalog, "ensure_fresh", lambda **k: None)
    out = sync.run_sync(gap_s=0, log=lambda m: None)
    assert got == ["https://www.bilibili.com/video/BV1aaaaaaaa5"] and out["counts"]["hit"] == 1 and out["ok"]
    s = sync.last_summary()
    assert s["state"] == "done" and s["downloaded"] == 1 and s["running"] is False


def test_cli_status_payload_includes_tv_state(vault, monkeypatch, capsys):
    from link_brain import cli
    monkeypatch.setattr(login, "status", lambda: {"state": "logged_in", "detail": "已登录", "mid_masked": "12***34", "vip": True})
    code = cli.main(["bilibili", "status", "--json"])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and payload["vip"] is True and payload["tv"]["state"] == "logged_out" and payload["ok"] is True
