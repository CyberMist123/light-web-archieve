"""B 站来源（1029 阶段一）：链接识别、yt-dlp 产物进 RAW、字幕 → transcript.json、去重、登录态不泄露。网络和下载器全部替身。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import domain, index as index_mod, ingest, sources, storage
from link_brain.sources import bilibili as bili
from link_brain.sources.bilibili import login, ytdlp

BV = "BV1AbCdEfGhJ"
URL = f"https://www.bilibili.com/video/{BV}"
SRT = "1\n00:00:01,000 --> 00:00:02,500\n第一句 字幕\n\n2\n00:00:03,000 --> 00:00:04,000\n第二句 台词\n\n"
XML = '<?xml version="1.0" encoding="UTF-8"?><i><chatserver>chat.bilibili.com</chatserver><d p="1.2,1,25,16777215,0,0,0,0">哈哈</d><d p="2.0,1,25,16777215,0,0,0,0">前方高能</d></i>'


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    monkeypatch.setattr(ytdlp, "ffmpeg_ok", lambda: True)
    monkeypatch.setattr(ytdlp, "version", lambda: "0.test")
    monkeypatch.setattr(login, "has_cookies", lambda: False)
    return tmp_path


def _fake_run(*, subtitles=("zh-CN",), danmaku=True, video=True, cover=True, exit_code=0, info=None):
    calls = []

    def run(url, *, log=lambda m: None, timeout_s=None, use_cookies=True):
        calls.append(url)
        d = ytdlp.new_tmp_dir()
        if video:
            (d / "1AbCdEfGhJ.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096)
        for lang in subtitles:
            (d / f"1AbCdEfGhJ.{lang}.srt").write_text(SRT, encoding="utf-8")
        if danmaku:
            (d / "1AbCdEfGhJ.danmaku.xml").write_text(XML, encoding="utf-8")
        if cover:
            from PIL import Image
            Image.new("RGB", (16, 9), "red").save(d / "1AbCdEfGhJ.jpg")
        base = {"id": "1AbCdEfGhJ", "title": "测试视频：字幕与弹幕", "description": "简介第一行\n第二行", "uploader": "某UP",
                "uploader_id": "123456", "uploader_url": "https://space.bilibili.com/123456", "upload_date": "20260101",
                "timestamp": 1767225600, "duration": 171, "like_count": 10, "view_count": 200, "comment_count": 3,
                "tags": ["音乐", "翻唱"], "thumbnail": "https://i0.hdslb.com/x.jpg", "webpage_url": URL,
                "formats": [{"url": "https://cdn.example/x.m4s?deadline=1&SESSDATA=notreal"}]}
        base.update(info or {})
        (d / "1AbCdEfGhJ.info.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
        res = {"dir": d, "exit_code": exit_code, "argv": ["yt-dlp", url], "cookies_used": False, "stderr_tail": "",
               "duration_s": 1.0, "need_login_subtitle": False, "stdout_tail": ""}
        res.update(ytdlp.collect_files(d))
        return res

    run.calls = calls
    return run


def _probe_ok(path):
    return {"ok": True, "duration_sec": 171.2, "width": 1920, "height": 1080, "vcodec": "h264", "acodec": "aac", "has_audio": True, "error": None}


# ---- 识别 / 解析 ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    (URL, [URL]),
    (f"看这个 {URL}/?spm_id_from=333&p=2 不错", [f"{URL}/?spm_id_from=333&p=2"]),
    (f"https://m.bilibili.com/video/{BV}", [f"https://m.bilibili.com/video/{BV}"]),
    (f"存一下 {BV} 这个", [URL]),
    ("https://www.xiaohongshu.com/explore/0000000000000000deadbeef 没有 B 站", []),
    ("https://evil.example/bilibili.com/video/BV1AbCdEfGhJ", []),
    ("BV12345 不是合法 BV", []),
])
def test_find_urls(text, expected):
    assert bili.find_urls(text) == expected


def test_parse_identity_and_page():
    p = bili.parse(f"{URL}?p=3")
    assert (p["source"], p["source_id"], p["bvid"], p["page"]) == ("bilibili", f"{BV}_p3", BV, 3)
    assert p["canonical_url"] == f"{URL}?p=3"
    p1 = bili.parse(BV)
    assert p1["source_id"] == BV and p1["input_kind"] == "bvid" and p1["canonical_url"] == URL
    assert domain.item_id("bilibili", BV) == f"bili-{BV}"
    with pytest.raises(sources.SourceError):
        bili.parse("https://www.bilibili.com/read/cv123")


def test_detect_dispatches_to_both_sources():
    found = sources.detect(f"{URL} 和 https://www.xiaohongshu.com/explore/0000000000000000deadbeef")
    assert [(s.name, u) for s, u in found] == [
        ("xiaohongshu", "https://www.xiaohongshu.com/explore/0000000000000000deadbeef"), ("bilibili", URL)]


def test_registered_source_implements_protocol():
    src = sources.get("bilibili")
    for member in ("matches", "find_urls", "parse", "fetch", "normalize", "fingerprint", "media_plan", "meta_fields",
                   "source_open_url", "item_flags", "comment_view", "note_albums", "action_home"):
        assert callable(getattr(src, member))
    assert src.name == "bilibili" and "bilibili" in domain.PREFIX and src.visible_subdir == ("Web", "Bilibili")


# ---- 验真 ------------------------------------------------------------------------------------------------------------

def test_validators(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text(SRT, encoding="utf-8")
    assert ytdlp.validate_srt(srt) == {"ok": True, "cues": 2, "chars": 12, "error": None}
    assert ytdlp.srt_text(srt) == "第一句 字幕\n第二句 台词"
    bad = tmp_path / "b.srt"
    bad.write_text("1\n没有时间戳\n", encoding="utf-8")
    assert ytdlp.validate_srt(bad)["ok"] is False
    xml = tmp_path / "d.xml"
    xml.write_text(XML, encoding="utf-8")
    assert ytdlp.validate_danmaku(xml) == {"ok": True, "count": 2, "error": None}
    empty = tmp_path / "e.xml"
    empty.write_text("<i></i>", encoding="utf-8")
    assert ytdlp.validate_danmaku(empty)["count"] == 0 and ytdlp.validate_danmaku(empty)["ok"]
    broken = tmp_path / "f.xml"
    broken.write_text("<i><d>", encoding="utf-8")
    assert ytdlp.validate_danmaku(broken)["ok"] is False
    assert ytdlp.probe_video(tmp_path / "missing.mp4")["ok"] is False


def test_sanitize_hides_cookies_and_signed_urls():
    text = "ERROR: x SESSDATA=abc123; bili_jct=def https://cdn.example/v.m4s?deadline=1&sign=zzz"
    out = ytdlp.sanitize(text)
    assert "abc123" not in out and "def" not in out.split("bili_jct=")[1][:3] and "sign=zzz" not in out
    info = ytdlp.sanitize_info({"id": "x", "formats": [{"url": "https://a?b=1"}], "http_headers": {"Cookie": "SESSDATA=1"},
                                "subtitles": {"zh-CN": [{"ext": "srt", "data": "..."}], "danmaku": [{"ext": "xml", "url": "u"}]}})
    assert "formats" not in info and "http_headers" not in info
    assert info["subtitles"] == {"zh-CN": ["srt"], "danmaku": ["xml"]}


# ---- 全链路（下载器替身）----------------------------------------------------------------------------------------------

def _ingest(monkeypatch, run, probe=_probe_ok, **kw):
    monkeypatch.setattr(ytdlp, "run", run)
    monkeypatch.setattr(ytdlp, "probe_video", probe)
    return ingest.ingest_url(URL, **kw)


def test_ingest_publishes_video_subtitle_danmaku(vault, monkeypatch):
    run = _fake_run()
    out = _ingest(monkeypatch, run)
    assert out["item_id"] == f"bili-{BV}" and out["version"] == 1 and out["exit_code"] == 0
    obj = storage.object_dir("bilibili", BV)
    raw = obj / "raw" / "v0001"
    manifest = storage.read_json(raw / "manifest.json")
    by_role = {m["role"]: m for m in manifest["media"]}
    assert set(by_role) == {"video", "video_cover", "subtitle", "danmaku"}
    for role in ("video", "subtitle", "danmaku", "video_cover"):
        m = by_role[role]
        assert m["download_status"] == "ok" and m["error"] is None
        assert m["file"].startswith("raw/v0001/assets/") and "\\" not in m["file"]
        assert (obj / m["file"]).is_file() and m["bytes"] == (obj / m["file"]).stat().st_size and len(m["sha256"]) == 64
    assert by_role["video"]["file"].endswith("/video.mp4") and by_role["video"]["duration_sec"] == 171.2
    assert by_role["subtitle"]["lang"] == "zh-CN" and by_role["subtitle"]["file"].endswith("/subtitle.zh-CN.srt") and by_role["subtitle"]["cues"] == 2
    assert by_role["danmaku"]["file"].endswith("/danmaku.xml") and by_role["danmaku"]["count"] == 2
    assert manifest["images_complete"] is True
    # 原样返回只留白名单：没有签名地址 / cookie
    raw_text = (raw / "ytdlp_info.json").read_text(encoding="utf-8")
    assert "SESSDATA" not in raw_text and "deadline" not in raw_text and "formats" not in raw_text
    src = storage.read_json(raw / "source.json")
    assert src["note"]["kind"] == "video" and src["note"]["title"] == "测试视频：字幕与弹幕"
    assert src["note"]["author"]["nickname"] == "某UP" and src["note"]["video"]["downloaded"] is True
    assert src["note"]["subtitles"][0]["status"] == "ok" and src["note"]["danmaku"]["status"] == "ok"
    assert src["capture"]["login"] == "anonymous"
    meta = storage.read_json(obj / "meta.json")
    assert meta["kind"] == "video" and meta["source"] == "bilibili" and meta["canonical_url"] == URL
    # 站点字幕 → transcript.json（渲染 / 检索读它）
    tr = storage.read_json(obj / "derived" / "transcript.json")
    assert tr["status"] == "ok" and tr["engine"] == "bilibili-cc" and "第二句 台词" in tr["text"]
    # 临时目录已清
    assert not any(p.is_dir() for p in ytdlp.tmp_root().iterdir()) if ytdlp.tmp_root().is_dir() else True
    # 渲染：可见笔记在 Web/Bilibili，机读版带文字稿
    from link_brain import render
    got = render.render_object("bilibili", BV)
    assert got["visible_note"].startswith("Web/Bilibili/")
    note_text = (storage.vault_root() / got["visible_note"]).read_text(encoding="utf-8")
    assert f"item_id: bili-{BV}" in note_text and "video.mp4" in note_text and URL in note_text
    agent = (obj / "derived" / "agent.md").read_text(encoding="utf-8")
    assert "## 视频文字稿" in agent and "第一句 字幕" in agent
    # 第二次导入：命中索引，不再调下载器
    again = ingest.ingest_url(URL)
    assert again["hit"] is True and len(run.calls) == 1
    assert storage.existing_versions("bilibili", BV) == [1]


def test_ingest_without_subtitles_records_unavailable_and_no_asr(vault, monkeypatch):
    out = _ingest(monkeypatch, _fake_run(subtitles=(), danmaku=False))
    obj = storage.object_dir("bilibili", BV)
    manifest = storage.read_json(obj / "raw" / "v0001" / "manifest.json")
    by_role = {m["role"]: m for m in manifest["media"]}
    assert by_role["subtitle"]["download_status"] == "unavailable" and by_role["subtitle"]["file"] is None
    assert "未登录" in by_role["subtitle"]["error"]
    assert by_role["danmaku"]["download_status"] == "failed" and by_role["danmaku"]["file"] is None
    assert by_role["video"]["download_status"] == "ok"
    assert out["exit_code"] == ingest.EXIT_MISSING_CONTENT   # 弹幕没拿到是失败；字幕 unavailable 不算
    tr = storage.read_json(obj / "derived" / "transcript.json")
    assert tr["status"] == "no_subtitle" and tr["text"] == ""
    from link_brain import videos
    assert "no_subtitle" in videos.DONE_STATUSES
    assert not list((obj / "raw" / "v0001" / "assets").glob("*.srt"))


def test_ingest_video_invalid_does_not_publish(vault, monkeypatch):
    def bad_probe(path):
        return {"ok": False, "error": "读不出时长（可能是半截文件）", "duration_sec": None}
    with pytest.raises(sources.SourceError, match="半截"):
        _ingest(monkeypatch, _fake_run(), probe=bad_probe)
    assert not (storage.object_dir("bilibili", BV) / "meta.json").exists()
    assert storage.existing_versions("bilibili", BV) == []
    conn = index_mod.connect()
    try:
        assert index_mod.find_object(conn, "bilibili", BV) is None
    finally:
        conn.close()


def test_ingest_no_video_file_maps_login_error(vault, monkeypatch):
    def run(url, **kw):
        d = ytdlp.new_tmp_dir()
        return {"dir": d, "exit_code": 1, "argv": [], "cookies_used": False, "duration_s": 0.1, "need_login_subtitle": False,
                "stderr_tail": "ERROR: [BiliBili] x: This video is for premium members only. Login required", "stdout_tail": "",
                **ytdlp.collect_files(d)}
    with pytest.raises(sources.AccountBlocked) as ei:
        _ingest(monkeypatch, run)
    assert ei.value.code == "NOT_LOGGED_IN"


def test_expired_login_stops_before_download(vault, monkeypatch):
    monkeypatch.setattr(login, "has_cookies", lambda: True)
    monkeypatch.setattr(login, "status", lambda **kw: {"state": "logged_out", "detail": "失效", "mid_masked": ""})
    run = _fake_run()
    with pytest.raises(sources.AccountBlocked):
        _ingest(monkeypatch, run)
    assert run.calls == []


def test_login_status_never_exposes_cookie_values(vault, monkeypatch):
    p = login.cookies_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t9999999999\tSESSDATA\tsecret-value-xyz\n", encoding="utf-8")
    monkeypatch.setattr(login, "has_cookies", lambda: True)

    class Resp:
        status_code = 200

        def json(self):
            return {"data": {"isLogin": True, "mid": 1234567, "uname": "真名", "vipStatus": 0}}

    class Client:
        def get(self, url):
            return Resp()

        def close(self):
            pass

    st = login.status(client=Client())
    text = json.dumps(st, ensure_ascii=False)
    assert st["state"] == "logged_in" and "secret-value" not in text and "真名" not in text and st["mid_masked"] == "12***67"
    assert "1234567" not in text


def test_catch_handles_bilibili_without_account_lock(vault, monkeypatch):
    from link_brain import catch, accounts
    monkeypatch.setattr(ytdlp, "run", _fake_run())
    monkeypatch.setattr(ytdlp, "probe_video", _probe_ok)

    def no_lock(*a, **kw):
        raise AssertionError("B 站导入不该拿小红书账号锁")
    monkeypatch.setattr(accounts, "account_session", no_lock)
    monkeypatch.setattr(catch.enrich_mod if hasattr(catch, "enrich_mod") else __import__("link_brain.enrich", fromlist=["x"]),
                        "enrich_one", lambda *a, **k: None)
    out = catch.catch_message(f"收一下 {URL}", origin="cli", actor="human")
    assert out["found"] == 1 and out["items"][0]["status"] == "new" and out["items"][0]["item_id"] == f"bili-{BV}"
    assert out["items"][0]["visible_note"] and "Web" in out["items"][0]["visible_note"]


def test_ytdlp_argv_uses_plugin_chunk_and_lang_url(vault):
    """1029 实测：出口 IP 被风控时只有带语言前缀的页面能解析；CDN 整文件 GET 回 567 要分段；插件由我们生成到 ~/.link-brain。"""
    assert ytdlp.download_url("BV1AbCdEfGhJ") == "https://www.bilibili.com/zh-Hans/video/BV1AbCdEfGhJ/"
    assert ytdlp.download_url("BV1AbCdEfGhJ", 3).endswith("/?p=3")
    argv = ytdlp.build_argv(ytdlp.download_url(BV), Path("out"), cookies=None)
    assert "--plugin-dirs" in argv and "--http-chunk-size" in argv and "--cookies" not in argv
    plug = Path(argv[argv.index("--plugin-dirs") + 1]) / "lwa-bilibili" / "yt_dlp_plugins" / "extractor" / "bilibili_lang.py"
    assert plug.is_file() and "BiliBiliIE" in plug.read_text(encoding="utf-8")
    assert str(storage.link_brain_home()) in str(plug)
    with_cookie = ytdlp.build_argv(URL, Path("out"), cookies=Path("c.txt"))
    assert with_cookie[with_cookie.index("--cookies") + 1] == "c.txt"
