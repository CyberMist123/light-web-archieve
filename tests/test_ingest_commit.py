"""第二波 PR⑤a：ingest 写新版本走暂存、单篇锁里提交；崩一半的孤儿版本收编不重抓；抓的时候被删不发布；并发只出一个版本。

网络无关：parse_input / fetch_detail 换成假的，样本是 tests/fixtures/mcp_raw_sanitized.json（图片地址是 example.invalid，下载失败属预期）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import domain, index as index_mod, ingest, storage
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"
SRC = xhs.SOURCE
ITEM = domain.item_id(SRC, NOTE_ID)


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _parsed(text="https://example.invalid/share"):
    return {"note_id": NOTE_ID, "xsec_token": "FAKE_TOKEN", "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
            "input_url": text, "input_kind": "url", "resolved_url": text}


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: _parsed(text))
    calls = {"fetch": 0}

    def fetch(*a, **k):
        calls["fetch"] += 1
        hook = calls.get("hook")
        if hook:
            calls["hook"] = None
            hook()
        return _fixture()

    monkeypatch.setattr(xhs, "fetch_detail", fetch)
    return tmp_path, calls


def _raw(tmp):
    return tmp / "_archive" / SRC / NOTE_ID / "raw"


def _staging_left(tmp):
    base = _raw(tmp)
    return [p for p in base.iterdir() if p.name.startswith(storage.STAGING_PREFIX)] if base.is_dir() else []


def _meta(tmp):
    return storage.read_json(tmp / "_archive" / SRC / NOTE_ID / "meta.json")


class Boom(Exception):
    pass


def test_normal_ingest_publishes_retargeted_manifest(vault):
    tmp, calls = vault
    out = ingest.ingest_url("https://example.invalid/share")
    assert out["version"] == 1 and calls["fetch"] == 1
    v1 = _raw(tmp) / "v0001"
    assert storage.is_complete_version(v1) and not _staging_left(tmp)
    text = (v1 / "manifest.json").read_text(encoding="utf-8")
    assert storage.STAGING_PREFIX not in text
    assert json.loads(text)["version"] == 1
    assert _meta(tmp)["versions"] == [1] and _meta(tmp)["current_version"] == 1


def test_retarget_only_touches_staging_paths(vault):
    tmp, _ = vault
    with storage.stage_version(SRC, NOTE_ID) as stg:
        m = {"version": None, "media": [{"file": f"raw/{stg.path.name}/assets/a.jpg"}, {"file": "raw/v0001/assets/b.jpg"},
                                         {"file": None}]}
        out = ingest._retarget(m, stg, 7)
    assert [x["file"] for x in out["media"]] == ["raw/v0007/assets/a.jpg", "raw/v0001/assets/b.jpg", None]
    assert out["version"] == 7


def test_crash_mid_download_leaves_no_version(vault, monkeypatch):
    tmp, _ = vault
    monkeypatch.setattr(ingest, "download_media", lambda *a, **k: (_ for _ in ()).throw(Boom("下到一半进程被杀")))
    with pytest.raises(Boom):
        ingest.ingest_url("https://example.invalid/share")
    assert storage.version_dirs(SRC, NOTE_ID) == {} and not _staging_left(tmp)
    assert not (tmp / "_archive" / SRC / NOTE_ID / "meta.json").exists()


def test_orphan_version_is_adopted_not_refetched(vault, monkeypatch):
    """第一次崩在「发布之后、写 meta 之前」：再入库一次不联网、不出 v0002，meta 指向 v0001（修前会重抓并写 v0002）。"""
    tmp, calls = vault
    real = ingest._write_meta
    monkeypatch.setattr(ingest, "_write_meta", lambda *a, **k: (_ for _ in ()).throw(Boom("写 meta 前崩了")))
    with pytest.raises(Boom):
        ingest.ingest_url("https://example.invalid/share")
    assert storage.existing_versions(SRC, NOTE_ID) == [1] and calls["fetch"] == 1
    monkeypatch.setattr(ingest, "_write_meta", real)

    out = ingest.ingest_url("https://example.invalid/share")
    assert calls["fetch"] == 1, "孤儿版本应该收编，不该再联网抓"
    assert out["adopted"] is True and out["hit"] is False and out["version"] == 1
    assert storage.version_dirs(SRC, NOTE_ID).keys() == {1}
    assert _meta(tmp)["current_version"] == 1 and _meta(tmp)["versions"] == [1]
    conn = index_mod.connect()
    try:
        assert index_mod.get_object(conn, ITEM) is not None
    finally:
        conn.close()


def test_index_row_lost_is_reindexed_not_refetched(vault):
    tmp, calls = vault
    ingest.ingest_url("https://example.invalid/share")
    conn = index_mod.connect()
    try:
        conn.execute("DELETE FROM objects WHERE item_id = ?", (ITEM,))
        conn.commit()
    finally:
        conn.close()
    out = ingest.ingest_url("https://example.invalid/share")
    assert calls["fetch"] == 1 and out["adopted"] is True and storage.existing_versions(SRC, NOTE_ID) == [1]


def test_deleted_during_fetch_is_not_published(vault):
    tmp, calls = vault

    def delete_now():
        conn = index_mod.connect()
        try:
            index_mod.write_tombstone(conn, {"source": SRC, "source_id": NOTE_ID, "item_id": ITEM,
                                             "deleted_at": "2026-10-25T00:00:00+11:00", "trash_dir": "_trash/x"})
        finally:
            conn.close()

    calls["hook"] = delete_now
    out = ingest.ingest_url("https://example.invalid/share")
    assert out["status"] == "trashed" and out["item_id"] == ITEM
    assert storage.version_dirs(SRC, NOTE_ID) == {} and not _staging_left(tmp)


def test_concurrent_ingest_single_version(vault):
    """抓的时候另一个入口把同一篇存好了：这边不再出第二个版本，按已在库返回（修前两个版本）。"""
    tmp, calls = vault
    calls["hook"] = lambda: ingest.ingest_url("https://example.invalid/share")
    out = ingest.ingest_url("https://example.invalid/share")
    assert calls["fetch"] == 2
    assert storage.existing_versions(SRC, NOTE_ID) == [1] and not _staging_left(tmp)
    assert out["hit"] is True and out["version"] == 1


def test_refresh_same_content_writes_no_version(vault):
    tmp, calls = vault
    ingest.ingest_url("https://example.invalid/share")
    out = ingest.ingest_url("https://example.invalid/share", refresh=True)
    assert out["refreshed_unchanged"] is True and storage.existing_versions(SRC, NOTE_ID) == [1]
    assert not _staging_left(tmp)
