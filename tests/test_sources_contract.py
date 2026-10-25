"""来源接口兼容性；所有抓取和下载均由测试替身完成。"""
import copy
import importlib
import json
from pathlib import Path
from typing import get_type_hints

import pytest

from link_brain import ai_config, domain, index, ingest, sources, videos
from link_brain.adapters import xiaohongshu as xhs

catch = importlib.import_module("link_brain.catch")
URL = "https://www.xiaohongshu.com/explore/0000000000000000deadbeef?xsec_token=FAKE_TOKEN_FOR_TESTS"
CAPTURED = "2026-10-25T12:00:00+11:00"


@pytest.fixture
def raw():
    return json.loads((Path(__file__).parent / "fixtures/mcp_raw_sanitized.json").read_text(encoding="utf-8"))


def test_registered_sources_implement_protocol():
    members = set(get_type_hints(sources.Source)) | {
        key for key, value in vars(sources.Source).items() if not key.startswith("_") and callable(value)
    }
    assert sources.names() == ["xiaohongshu"]
    for name in sources.names():
        src = sources.get(name)
        assert all(hasattr(src, member) for member in members)
        assert src.name == name and name in domain.PREFIX
        assert src.version == xhs.ADAPTER_VERSION
        assert src.capabilities == frozenset({"account", "favorites_sync", "comments_fill", "attachments", "albums"})
        for method in ("matches", "find_urls", "parse", "fetch", "normalize", "fingerprint", "media_plan"):
            assert callable(getattr(src, method))
            assert get_type_hints(getattr(src, method))
    with pytest.raises(sources.SourceError, match="未知来源"):
        sources.get("unknown")


def test_parse_normalize_fingerprint_match_old_functions(raw):
    src = sources.get("xiaohongshu")
    old_parsed = xhs.parse_input(URL)
    parsed = src.parse(URL)
    assert parsed == {**old_parsed, "source": "xiaohongshu", "source_id": old_parsed["note_id"]}
    for probe in (None, {"ok": True, "files": [], "url": URL}):
        fetched = sources.Fetched({"mcp_raw.json": raw}, {"web_probe": probe})
        expected = xhs.normalize(raw, old_parsed, captured_at=CAPTURED, web_probe=probe)
        actual = src.normalize(fetched, parsed, captured_at=CAPTURED)
        assert actual == expected
        assert src.fingerprint(actual) == index.normalized_source_sha256(expected)


def test_fetch_forwards_options(monkeypatch, raw):
    """PR⑤b：小红书 fetch 自己做重试抓取 + 网页探附件（从 ingest 搬来）；选项照转，原样返回进 raw_files。"""
    src = sources.get("xiaohongshu")
    parsed = src.parse(URL)
    calls = []
    probe = {"ok": True, "attachments": []}
    monkeypatch.setattr(xhs, "_fetch_with_retry", lambda p, **kw: calls.append((p, kw)) or raw)
    monkeypatch.setattr(src, "_web_probe", lambda p, log: probe)
    opts = sources.FetchOptions(comment_floors=20, budget_left=lambda: 120, progress=lambda *a: None,
                                log=lambda m: None, extra={"expand_floors": ["c0001"]})
    fetched = src.fetch(parsed, opts)
    assert calls == [(parsed, dict(log=opts.log, comment_floors=20, budget_left=opts.budget_left,
                                  expand_floors=["c0001"], fill_budget_s=None, progress=opts.progress,
                                  expand_resume=None, floors_resume=None))]
    assert fetched.raw_files == {"mcp_raw.json": raw, "web_raw.json": probe}
    assert fetched.context["web_probe"] is probe


def test_fetch_resolves_service_problems_before_web_probe(monkeypatch, raw):
    """复审：抓到详情就算读取服务好了，要在网页探测（可能抛登录问题）之前清掉旧的步骤级问题，和搬家前一致。"""
    from link_brain import problems
    src = sources.get("xiaohongshu")
    order = []
    monkeypatch.setattr(xhs, "_fetch_with_retry", lambda p, **kw: raw)
    monkeypatch.setattr(problems, "resolve", lambda step, code: order.append(("resolve", step, code)))

    def blocked(p, log):
        order.append(("probe",))
        raise xhs.AccountBlockedError("读取账号需要处理")
    monkeypatch.setattr(src, "_web_probe", blocked)
    with pytest.raises(xhs.AccountBlockedError):
        src.fetch(src.parse(URL), sources.FetchOptions(log=lambda m: None))
    assert order == [("resolve", "ingest", None), ("probe",)]


def test_fetch_expand_skips_merge_when_previous_version_missing(monkeypatch, raw):
    """复审：meta 在但 current_version 目录不完整（待重建索引）→ 不合并上一版，照常存，别读不存在的 source.json 报错。"""
    from link_brain import storage
    src = sources.get("xiaohongshu")
    parsed = src.parse(URL)
    storage.write_json(storage.object_dir("xiaohongshu", parsed["note_id"]) / "meta.json", {"current_version": 3})
    monkeypatch.setattr(xhs, "_fetch_with_retry", lambda p, **kw: raw)
    monkeypatch.setattr(src, "_web_probe", lambda p, log: {"ok": True, "attachments": []})
    fetched = src.fetch(parsed, sources.FetchOptions(log=lambda m: None, extra={"expand_floors": ["c0001"]}))
    assert "previous_source" not in fetched.context and "expand_floors" not in fetched.context


@pytest.mark.parametrize("old,new", [
    (xhs.AdapterError, sources.SourceError), (xhs.NeedsHumanError, sources.NeedsHuman),
    (xhs.AccountBlockedError, sources.AccountBlocked), (xhs.ServiceDownError, sources.ServiceDown),
    (xhs.NoteRestrictedError, sources.ItemRestricted),
])
def test_exception_aliases(old, new):
    assert old is new
    assert isinstance(old("x"), new) and isinstance(new("x"), old)


def test_exception_hierarchy():
    assert isinstance(xhs.ServiceDownError("x"), sources.NeedsHuman)
    assert isinstance(sources.ServiceDown("x"), xhs.NeedsHumanError)
    assert sources.ItemRestricted.code == "NOTE_RESTRICTED"
    assert not isinstance(sources.ItemRestricted("x"), sources.NeedsHuman)


@pytest.mark.parametrize("text", [
    "", "没有链接", URL + "增加的内容", f"（{URL}），再次 {URL}",
    "分享口令 ABC123 复制后打开小红书 https://xhslink.cn/a/test-token 查看笔记！",
    "https://xhslink.com/a/demo https://www.rednote.com/discovery/item/0000000000000000deadbeef",
    f"https://example.invalid/a {URL} https://evilxiaohongshu.com/a https://xiaohongshu.com.evil.invalid/a",
    "https://WWW.XIAOHONGSHU.COM/explore/0000000000000000deadbeef https://xhslink.cn/a/demo\n后续文字",
])
def test_find_urls_matches_catch(text):
    src = sources.get("xiaohongshu")
    expected = catch.find_xhs_urls(text)
    assert src.find_urls(text) == expected
    assert sources.detect(text) == [(src, url) for url in expected]


@pytest.mark.parametrize("url,expected", [
    (URL, True), ("https://xhslink.cn/a/demo", True), ("https://sub.rednote.com/a", True),
    ("https://evilxiaohongshu.com/a", False), ("https://xiaohongshu.com.evil.invalid/a", False),
    ("https://example.invalid/?next=xiaohongshu.com", False),
])
def test_matches_host(url, expected):
    assert sources.get("xiaohongshu").matches(url) is expected


def test_shared_code_catches_source_errors(monkeypatch):
    def unavailable(*a, **kw):
        raise sources.ServiceDown("fixture service unavailable")

    reports = []
    monkeypatch.setattr(xhs, "fetch_detail", unavailable)
    monkeypatch.setattr(xhs, "SERVICE_RETRIES", 1)
    monkeypatch.setattr(catch.accounts, "pace", lambda *a, **kw: None)
    monkeypatch.setattr(catch.accounts, "pace_done", lambda: None)
    monkeypatch.setattr(catch.problems, "report_blocked", lambda *a, **kw: reports.append((a, kw)))
    result = catch._catch_one(URL, message=URL, origin="cli", actor="human", verbose=False)
    assert result["status"] == "blocked"
    assert result["error"] == "fixture service unavailable"
    assert reports and reports[0][1]["service"] is True


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("images,video", [(True, True), (False, True), (True, False), (False, False)])
def test_media_plan_matches_downloads(monkeypatch, tmp_path, raw, kind, images, video):
    src = sources.get("xiaohongshu")
    doc = src.normalize(sources.Fetched({"mcp_raw.json": raw}), src.parse(URL), captured_at=CAPTURED)
    doc = copy.deepcopy(doc)
    doc["note"]["kind"] = kind
    doc["note"]["video"] = {"video_url": "https://example.invalid/video.mp4"}
    parent, child = doc["comments"][0], doc["comments"][0]["sub_comments"][0]
    for group in (parent, child):
        group["images"] = [{"url": f"https://example.invalid/{group['comment_id']}.jpg"}]
        group["audio"] = {"url": f"https://example.invalid/{group['comment_id']}.m4a"}
    opts = {"downloadImages": images, "downloadVideo": video}
    monkeypatch.setattr(ai_config, "sync_options", lambda: opts)
    downloads = []

    def image_download(url, assets, stem, **kw):
        downloads.append((url, stem, "image"))
        return {"file": None, "download_status": "failed"}

    def audio_download(audio, cid, *args):
        downloads.append((audio["url"], f"comment-{cid}-audio", "audio"))
        return {"role": "comment_audio", "comment_id": cid, "original_url": audio["url"]}

    def video_download(v, *args):
        downloads.append((v["video_url"], "video", "video"))
        return {"role": "video", "index": 1, "original_url": v["video_url"]}

    monkeypatch.setattr(ingest, "download_image", image_download)
    monkeypatch.setattr(ingest, "_download_comment_audio", audio_download)
    monkeypatch.setattr(videos, "download", video_download)
    manifest = ingest.download_media(doc, tmp_path / "v0001", "raw/v0001")
    tasks = src.media_plan(doc, opts)
    assert [(t["url"], t["stem"], t["kind"]) for t in tasks] == downloads
    def identity(entry, url_key):
        return entry["role"], entry.get("index"), entry.get("comment_id"), entry[url_key]
    assert {identity(t, "url") for t in tasks} == {identity(m, "original_url") for m in manifest["media"]}
    assert all(t["headers"] == ingest.DOWNLOAD_HEADERS for t in tasks)
