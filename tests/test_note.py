"""笔记批注 + ⭐ 收藏 + 手动挂附件 的网络无关单测（note.py / attachments.manual_attach）。"""

from __future__ import annotations

import json
from pathlib import Path

from link_brain import (
    attachments,
    cli,
    index as index_mod,
    note,
    render,
    storage,
)
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"


def _fake_parsed(text="https://example.invalid/share"):
    return {
        "note_id": NOTE_ID,
        "xsec_token": "FAKE_TOKEN",
        "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
        "input_url": text,
        "input_kind": "url",
        "resolved_url": text,
    }


def _ingest(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: _fake_parsed(text))
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: json.loads(FIXTURE.read_text(encoding="utf-8")))
    cli.main(["ingest", "https://example.invalid/share"])
    conn = index_mod.connect()
    item_id = index_mod.find_object(conn, xhs.SOURCE, NOTE_ID)["item_id"]
    conn.close()
    return item_id


def test_annotation_and_fable_flag(tmp_path, monkeypatch):
    item_id = _ingest(tmp_path, monkeypatch)
    assert note.add_annotation(item_id, "普通批注")["annotation"]["to_fable"] is False
    assert note.add_annotation(item_id, "@fable 你看看这个")["annotation"]["to_fable"] is True
    listed = note.list_notes(item_id)
    assert listed["status"] == "ok"
    assert len(listed["annotations"]) == 2
    # sidecar 落在对象目录，且没写进可见正文
    sidecar = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "notes.json"
    assert sidecar.is_file()


def test_empty_annotation_ignored(tmp_path, monkeypatch):
    item_id = _ingest(tmp_path, monkeypatch)
    assert note.add_annotation(item_id, "   ")["status"] == "empty"
    assert note.list_notes(item_id)["annotations"] == []


def test_star_tracks_state_without_root_copies(tmp_path, monkeypatch):
    item_id = _ingest(tmp_path, monkeypatch)
    meta = json.loads((tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "meta.json").read_text(encoding="utf-8"))
    copy_path = tmp_path / f"{render.sanitize_title(meta['title'])}.md"

    on = note.set_star(item_id, True)
    assert on["starred"] is True and on["copied"] is False
    assert not copy_path.exists()
    assert note.list_notes(item_id)["starred"] is True

    off = note.set_star(item_id, False)
    assert off["starred"] is False and off["removed"] is False
    assert not copy_path.exists()


def test_star_does_not_clobber_edited_copy(tmp_path, monkeypatch):
    item_id = _ingest(tmp_path, monkeypatch)
    meta = json.loads((tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "meta.json").read_text(encoding="utf-8"))
    copy_path = tmp_path / f"{render.sanitize_title(meta['title'])}.md"
    copy_path.write_text("我自己改过的副本", encoding="utf-8")
    note.set_star(item_id, True)
    note.set_star(item_id, False)
    # 取消收藏也不删除用户编辑过的历史副本
    assert copy_path.read_text(encoding="utf-8") == "我自己改过的副本"


def test_manual_attach_flips_badge(tmp_path, monkeypatch):
    item_id = _ingest(tmp_path, monkeypatch)
    conn = index_mod.connect()
    row = index_mod.get_object(conn, item_id)
    source, source_id = row["source"], row["source_id"]
    conn.close()

    local = tmp_path / "我自己下的.pdf"
    local.write_bytes(b"%PDF-1.4 fake bytes")
    out = attachments.manual_attach(source, source_id, str(local))
    assert out["file"] == "我自己下的.pdf"

    obj_dir = storage.object_dir(source, source_id)
    assert (obj_dir / "attachments" / "我自己下的.pdf").is_file()
    meta = json.loads((obj_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["attachments_status"] == "downloaded"
    from link_brain import render
    rendered = render.render_object(source, source_id)
    visible = (tmp_path / rendered["visible_note"]).read_text(encoding="utf-8")
    assert "我自己下的.pdf" in visible
    assert "已存本地" in visible



def test_note_missing_target(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    index_mod.connect().close()
    assert note.set_star("nope", True)["status"] == "missing"
    assert note.add_annotation("nope", "x")["status"] == "missing"
