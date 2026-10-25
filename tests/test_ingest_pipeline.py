"""第二波 PR⑤b：ingest_url 只认来源接口。注册一个假来源（不是小红书），整条入库流程照样跑通——
证明 ingest 不再认识小红书的数据结构（认来源 / 解析 / 抓 / 规范化 / 指纹 / 下载计划 / meta 里来源那几项都问来源）。"""
from __future__ import annotations

import sys
import types

import pytest

from link_brain import domain, index as index_mod, ingest, sources, storage
from link_brain.adapters import xiaohongshu as xhs

NAME = "fakesite"
SID = "item42"


def _fake_module(calls: dict):
    m = types.ModuleType("fake_source_for_tests")
    m.name, m.version, m.capabilities = NAME, "fake-1", frozenset()
    m.matches = lambda url: "fake.invalid" in url
    m.find_urls = lambda text: [w for w in (text or "").split() if "fake.invalid" in w]

    def parse(text):
        return {"source": NAME, "source_id": SID, "canonical_url": f"https://fake.invalid/{SID}",
                "input_url": text, "input_kind": "url", "resolved_url": text}

    def fetch(parsed, opts):
        calls["fetch"] += 1
        hook = calls.pop("hook", None)
        if hook:
            hook()
        return sources.Fetched(raw_files={"page.json": {"html": "<p>hi</p>", "n": calls["fetch"]}},
                               context={"body": calls.get("body", "hello")})

    def normalize(fetched, parsed, *, captured_at):
        return {"schema_version": 1, "source": NAME, "source_id": parsed["source_id"],
                "note": {"kind": "text", "title": "假帖", "body": fetched.context["body"], "hashtags": [],
                         "images": [{"index": 1, "url": "https://fake.invalid/a.jpg"}]},
                "comments": [], "capture": {"captured_at": captured_at, "comments_complete": True}}

    m.parse, m.fetch, m.normalize = parse, fetch, normalize
    m.fingerprint = lambda doc: "sha-" + doc["note"]["body"]
    m.media_plan = lambda doc, opts: [dict(role="note_image", index=1, url="https://fake.invalid/a.jpg",
                                           stem="image-001", kind="image", headers={"User-Agent": "fake"})]
    m.meta_fields = lambda doc: {"kind": "text", "title": doc["note"]["title"],
                                 "author": {"user_id": "u1", "nickname": "某人", "profile_url": None},
                                 "published_at": None, "comments_complete": True, "attachments_status": "none",
                                 "tool_versions": {"adapter": "fake-1"}}
    return m


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    calls = {"fetch": 0}
    mod = _fake_module(calls)
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    monkeypatch.setitem(sources._REGISTRY, NAME, mod.__name__)
    monkeypatch.setitem(domain.PREFIX, NAME, "fake")
    monkeypatch.setitem(domain._SOURCE_OF, "fake", NAME)

    def no_xhs(*a, **k):
        raise AssertionError("ingest 碰了小红书")
    monkeypatch.setattr(xhs, "parse_input", no_xhs)
    monkeypatch.setattr(xhs, "fetch_detail", no_xhs)
    monkeypatch.setattr(xhs, "fetch_related_file", no_xhs)
    seen = []
    monkeypatch.setattr(ingest, "download_image", lambda url, dest, stem, client: seen.append((url, client.headers.get("user-agent"))) or {
        "file": None, "requested_url": url, "mime": None, "width": None, "height": None, "bytes": None,
        "sha256": None, "download_status": "failed", "error": "离线"})
    return tmp_path, calls, seen


def test_fake_source_runs_whole_pipeline(fake):
    tmp, calls, seen = fake
    out = ingest.ingest_url("看这个 https://fake.invalid/item42")
    assert out["version"] == 1 and out["item_id"] == "fake-item42" and calls["fetch"] == 1
    v1 = storage.raw_dir(NAME, SID, 1)
    assert storage.read_json(v1 / "page.json")["html"] == "<p>hi</p>"          # 来源的原样返回照写
    assert storage.read_json(v1 / "source.json")["note"]["body"] == "hello"
    manifest = storage.read_json(v1 / "manifest.json")
    assert [m["role"] for m in manifest["media"]] == ["note_image"] and manifest["version"] == 1
    assert seen == [("https://fake.invalid/a.jpg", "fake")]                     # 下载计划的请求头带上了
    meta = storage.read_json(storage.object_dir(NAME, SID) / "meta.json")
    assert meta["source"] == NAME and meta["title"] == "假帖" and meta["tool_versions"]["adapter"] == "fake-1"
    conn = index_mod.connect()
    try:
        assert index_mod.get_object(conn, "fake-item42")["title"] == "假帖"
    finally:
        conn.close()


def test_fake_source_hit_and_refresh_unchanged(fake):
    _, calls, _ = fake
    ingest.ingest_url("https://fake.invalid/item42")
    assert ingest.ingest_url("https://fake.invalid/item42")["hit"] is True and calls["fetch"] == 1
    out = ingest.ingest_url("https://fake.invalid/item42", refresh=True)
    assert out["refreshed_unchanged"] is True and storage.existing_versions(NAME, SID) == [1]
    calls["body"] = "changed"
    out = ingest.ingest_url("https://fake.invalid/item42", refresh=True)
    assert out["version"] == 2 and storage.existing_versions(NAME, SID) == [1, 2]


def test_fake_source_deleted_during_fetch_not_published(fake):
    _, calls, _ = fake

    def delete_now():
        conn = index_mod.connect()
        try:
            index_mod.write_tombstone(conn, {"source": NAME, "source_id": SID, "item_id": "fake-item42",
                                             "deleted_at": "2026-10-25T00:00:00+11:00", "trash_dir": "_trash/x"})
        finally:
            conn.close()

    calls["hook"] = delete_now
    out = ingest.ingest_url("https://fake.invalid/item42")
    assert out["status"] == "trashed" and storage.version_dirs(NAME, SID) == {}


def test_unknown_link_with_several_sources_is_refused(fake):
    with pytest.raises(sources.SourceError):
        ingest.recognize("https://nowhere.invalid/x")
