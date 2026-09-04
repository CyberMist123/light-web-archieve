"""Lot「附件」：字节下载的落盘契约。

`fetch_bytes` 会真的开浏览器，这里一律 monkeypatch 掉——测试不碰 agent-browser、不联网。
"""

from __future__ import annotations

import json
from pathlib import Path

from link_brain import attachments as att_mod, cli, index as index_mod, render as render_mod, storage
from link_brain import vision as vision_mod
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"
DOC_ID = "7658854832003020032"

RELATED_FILE = {
    "name": "教程.pdf",
    "docId": DOC_ID,
    "icon": "https://example.invalid/icon",
    "bizExtra": '{"download_num":644,"page_num":19,"view_num":1468}',
}


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(
        xhs, "parse_input",
        lambda text, client=None: {
            "note_id": NOTE_ID,
            "xsec_token": "FAKE_TOKEN_FOR_TESTS",
            "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
            "input_url": text,
            "input_kind": "url",
        },
    )
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: json.loads(FIXTURE.read_text(encoding="utf-8")))
    monkeypatch.setattr(
        vision_mod, "run_ocr", lambda path, timeout=120: {"status": "ok", "ocr": "t", "error": None}
    )
    # 探测成功 → 附件条目带真 doc_id
    monkeypatch.setattr(
        xhs, "fetch_related_file",
        lambda note_id, xsec_token, **kw: {
            "ok": True, "related_file": RELATED_FILE, "url": "https://example.invalid/n", "error": None
        },
    )


def _ids():
    conn = index_mod.connect()
    try:
        row = conn.execute("SELECT item_id, source, source_id FROM objects").fetchone()
        return row["item_id"], row["source"], row["source_id"]
    finally:
        conn.close()


def fake_fetch(payload: bytes = b"%PDF-1.6 fake\n%%EOF\n", *, calls: list | None = None):
    def _fetch(*, doc_id, note_id, xsec_token, file_name, staging_dir, verbose=False):
        if calls is not None:
            calls.append(doc_id)
        staging_dir.mkdir(parents=True, exist_ok=True)
        path = staging_dir / "教程.pdf"
        path.write_bytes(payload)
        return path

    return _fetch


# --------------------------------------------------------------------------


def test_download_button_regex_picks_ref_from_snapshot():
    line = '- button " 下载" [ref=e1]'
    assert att_mod.DOWNLOAD_BUTTON_RE.search(line).group(1) == "e1"


def test_download_lands_object_level_and_keeps_raw_sealed(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, source, source_id = _ids()

    raw_dir = storage.raw_dir(source, source_id, 1)
    before = {p.name: p.read_bytes() for p in raw_dir.iterdir() if p.is_file()}

    monkeypatch.setattr(att_mod, "fetch_bytes", fake_fetch())
    out = att_mod.download_for_object(source, source_id)

    assert [r["status"] for r in out["results"]] == ["downloaded"]
    stored = storage.object_dir(source, source_id) / "attachments" / "教程.pdf"
    assert stored.exists() and stored.read_bytes().startswith(b"%PDF")

    doc = json.loads(att_mod.attachments_path(source, source_id).read_text(encoding="utf-8"))
    entry = doc["files"][0]
    assert entry["doc_id"] == DOC_ID and entry["bytes"] == stored.stat().st_size
    assert len(entry["sha256"]) == 64

    meta = storage.read_json(storage.object_dir(source, source_id) / "meta.json")
    assert meta["attachments_status"] == "downloaded"

    # RAW 版本一个字节都不许动
    after = {p.name: p.read_bytes() for p in raw_dir.iterdir() if p.is_file()}
    assert after == before


def test_second_run_skips_unless_force(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    calls: list[str] = []
    monkeypatch.setattr(att_mod, "fetch_bytes", fake_fetch(calls=calls))

    att_mod.download_for_object(source, source_id)
    out = att_mod.download_for_object(source, source_id)
    assert [r["status"] for r in out["results"]] == ["already"]
    assert len(calls) == 1, "已经下过就不该再开浏览器"

    att_mod.download_for_object(source, source_id, force=True)
    assert len(calls) == 2


def test_attachment_without_doc_id_is_skipped(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    # 探测失败 → 只有正文线索、没有 doc_id
    monkeypatch.setattr(
        xhs, "fetch_related_file",
        lambda note_id, xsec_token, **kw: {"ok": False, "related_file": None, "url": "u", "error": "连不上"},
    )
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()

    def _boom(**kw):
        raise AssertionError("没有 doc_id 时不该开浏览器")

    monkeypatch.setattr(att_mod, "fetch_bytes", _boom)
    out = att_mod.download_for_object(source, source_id)
    assert [r["status"] for r in out["results"]] == ["skipped"]
    assert not att_mod.attachments_path(source, source_id).exists()


def test_visible_note_links_local_file_after_download(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    monkeypatch.setattr(att_mod, "fetch_bytes", fake_fetch())
    att_mod.download_for_object(source, source_id)

    render_mod.render_object(source, source_id)
    text = list(storage.visible_dir().glob("*.md"))[0].read_text(encoding="utf-8")
    assert "已存本地" in text
    assert f"_archive/xiaohongshu/{NOTE_ID}/attachments/教程.pdf" in text
