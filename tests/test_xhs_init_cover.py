"""r5 补测：小红书来源接口（纯转发层；fetch/normalize/fingerprint 打桩，不出网——短链解析会真联网，绝不在测试里碰）。"""
from __future__ import annotations

import pytest

from link_brain import ingest
from link_brain.sources import FetchOptions, Fetched, xiaohongshu as x


def test_module_surface():
    assert x.name == "xiaohongshu" and x.version == "xiaohongshu/1"
    assert x.capabilities == frozenset({"account", "favorites_sync", "comments_fill", "attachments", "albums"})


def test_find_urls_hosts_and_trailing():
    assert x.find_urls(None) == [] and x.find_urls("") == []
    text = ("a https://www.xiaohongshu.com/explore/6512abc123def456abc123de，"
            " b https://xhslink.com/Zz9y"
            " c https://m.rednote.com/x/6512abc123def456abc123de"
            " d https://example.com/6512abc123def456abc123de")
    assert x.find_urls(text) == [
        "https://www.xiaohongshu.com/explore/6512abc123def456abc123de",
        "https://xhslink.com/Zz9y",
        "https://m.rednote.com/x/6512abc123def456abc123de",
    ]  # 四个域名族都认（含子域）；全角逗号这种尾部标点剥掉；非小红书域名不收


def test_matches_whitelist_no_lookalikes():
    assert x.matches("https://www.xiaohongshu.com/explore/abc") is True
    assert x.matches("https://a.b.rednote.com/x") is True and x.matches("https://xhslink.cn/A") is True
    assert x.matches("https://evil-xiaohongshu.com/x") is False  # 前缀拼花的域名不认
    assert x.matches("https://example.com/x") is False


def test_parse_note_url_and_reject_non_url():
    p = x.parse("看这篇 https://www.xiaohongshu.com/explore/6512abc123def456abc123de?xsec_token=AB12&other=1 谢谢")
    assert p["source"] == "xiaohongshu" and p["source_id"] == "6512abc123def456abc123de"
    assert p["note_id"] == "6512abc123def456abc123de" and p["xsec_token"] == "AB12"
    assert p["canonical_url"] == "https://www.xiaohongshu.com/explore/6512abc123def456abc123de"  # 规范链接不带查询串
    assert p["input_kind"] == "share_text"  # 带前后文的分享文案；裸 URL 才是 "url"
    # 不是 URL 的输入（纯笔记 id / 纯文本）直接 SourceError，不猜
    with pytest.raises(Exception, match="找不到 URL"):
        x.parse("6512abc123def456abc123de")


def test_fetch_delegates_to_adapter_with_options(monkeypatch):
    # ⑤b（#46）后重试抓取搬进 adapter，网页探附件随之进 web_raw.json：两处都打桩，不出网
    from link_brain.sources.xiaohongshu import adapter
    seen = {}

    def fake_retry(parsed, *, log, comment_floors, budget_left, progress, expand_floors, **kw):
        seen.update(parsed=parsed, comment_floors=comment_floors, budget_left=budget_left,
                    progress=progress, expand_floors=expand_floors, extra=kw)
        return {"note": "raw"}

    monkeypatch.setattr(adapter, "_fetch_with_retry", fake_retry)
    monkeypatch.setattr(x, "_web_probe", lambda parsed, log: {"probe": 1})
    budget = lambda: 1.0
    progress = lambda *a, **k: None
    opts = FetchOptions(comment_floors=5, budget_left=budget, progress=progress, extra={})
    parsed = {"source_id": "n1", "note_id": "n1"}
    f = x.fetch(parsed, opts)
    assert isinstance(f, Fetched)
    assert f.raw_files == {"mcp_raw.json": {"note": "raw"}, "web_raw.json": {"probe": 1}}
    assert f.context["web_probe"] == {"probe": 1} and "previous_source" not in f.context
    assert seen["parsed"] == parsed and seen["comment_floors"] == 5 and seen["expand_floors"] is None
    assert seen["budget_left"] is budget and seen["progress"] is progress
    assert seen["extra"]["fill_budget_s"] is None


def test_normalize_passes_raw_and_web_probe(monkeypatch):
    from link_brain.sources.xiaohongshu import adapter
    seen = {}
    adapter_normalize = lambda raw, parsed, *, captured_at, web_probe: seen.update(
        raw=raw, parsed=parsed, captured_at=captured_at, web_probe=web_probe) or {"ok": 1}
    monkeypatch.setattr(adapter, "normalize", adapter_normalize)
    raw = {"note": "raw"}
    parsed = {"note_id": "n1"}
    out = x.normalize(Fetched(raw_files={"mcp_raw.json": raw}, context={"web_probe": {"hint": 1}}), parsed,
                      captured_at="2026-10-26T00:00:00+11:00")
    assert out == {"ok": 1}
    assert seen == {"raw": raw, "parsed": parsed, "captured_at": "2026-10-26T00:00:00+11:00",
                    "web_probe": {"hint": 1}}
    # context 里没有 web_probe 就传 None
    monkeypatch.setattr(adapter, "normalize", lambda raw, parsed, *, captured_at, web_probe: web_probe)
    assert x.normalize(Fetched(raw_files={"mcp_raw.json": raw}), parsed, captured_at="t") is None


def test_media_plan_image_note_and_comments():
    doc = {"note": {"kind": "image", "images": [{"index": 1, "url": "http://img/1"}, {"index": 2, "url": "http://img/2"}],
                    "video": {}},
           "comments": [{"comment_id": "c1", "images": [{"url": "http://img/c1"}], "audio": {"url": "http://a/c1"},
                         "sub_comments": [{"comment_id": "c1s", "images": [{"url": "http://img/c1s"}]}]}]}
    tasks = x.media_plan(doc, {"downloadImages": True, "downloadVideo": True})
    assert [(t["role"], t.get("index"), t.get("comment_id"), t["stem"], t["kind"]) for t in tasks] == [
        ("note_image", 1, None, "image-001", "image"),
        ("note_image", 2, None, "image-002", "image"),
        ("comment_image", 1, "c1", "comment-c1-001", "image"),      # 主评论：序号从 1 重排
        ("comment_audio", None, "c1", "comment-c1-audio", "audio"),
        ("comment_image", 1, "c1s", "comment-c1s-001", "image"),    # 子评论同样展开
    ]
    assert all(t.get("headers") is (ingest.DOWNLOAD_HEADERS if t["kind"] == "image" else None) for t in tasks)  # 只有图片带头（语音 / 视频历来不带）
    # 关掉 downloadImages 只影响笔记图；评论图 / 音频照拿
    roles = [t["role"] for t in x.media_plan(doc, {"downloadImages": False, "downloadVideo": False})]
    assert roles == ["comment_image", "comment_audio", "comment_image"]


def test_media_plan_video_note_cover_and_video_toggle():
    doc = {"note": {"kind": "video", "images": [{"index": 3, "url": "http://img/vc"}],
                    "video": {"video_url": "http://v/1"}}, "comments": []}
    on = x.media_plan(doc, {"downloadImages": True, "downloadVideo": True})
    assert [(t["role"], t["index"], t["stem"]) for t in on] == [
        ("video_cover", 3, "cover-003"),  # 视频笔记的图当封面，stem 换 cover-…
        ("video", 1, "video"),
    ]
    off = x.media_plan(doc, {"downloadImages": True, "downloadVideo": False})
    assert [t["role"] for t in off] == ["video_cover"]  # 不下视频只留封面


def test_fingerprint_delegates_to_index(monkeypatch):
    from link_brain import index
    monkeypatch.setattr(index, "normalized_source_sha256", lambda doc: "sha-of-" + doc["note"]["id"])
    assert x.fingerprint({"note": {"id": "n1"}}) == "sha-of-n1"
