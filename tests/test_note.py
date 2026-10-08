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


# ── 批次 D · C3 / CM3：note star 一次接多个 id，catalog-data 整批只改一次，结果里报回写完那一刻的 stat ──

def test_set_stars_patches_catalog_once_and_reports_stat(tmp_path, monkeypatch):
    item_id = _ingest(tmp_path, monkeypatch)
    from link_brain import catalog
    calls = []

    def fake_patch(updates, vault=None, *, wait_s=5, report=None):
        calls.append(dict(updates))
        if report is not None:
            report["catalog_stat"] = {"mtime": 1234, "size": 56}
        return len(updates)

    monkeypatch.setattr(catalog, "patch_items", fake_patch)
    out = note.set_stars([item_id, "nope", NOTE_ID], True)
    assert len(calls) == 1, "整批只 patch 一次"
    assert list(calls[0]) == [item_id]   # 第三个是同一篇的裸 source_id：同一个 item_id，只出现一次
    assert [r["status"] for r in out["results"]] == ["ok", "missing", "ok"]
    assert out["results"][1]["error"]
    assert out["ok"] is False and out["count_ok"] == 2
    assert out["catalog_patched"] is True
    assert out["catalog_stat"] == {"mtime": 1234, "size": 56}
    assert "item_id" not in out, "多个 target 时不带旧的顶层键"


def test_note_star_cli_multi_exit_code_and_single_compat(tmp_path, monkeypatch, capsys):
    item_id = _ingest(tmp_path, monkeypatch)
    capsys.readouterr()
    from link_brain import catalog
    seen = []
    monkeypatch.setattr(catalog, "patch_items", lambda updates, vault=None, *, wait_s=5, report=None: seen.append(updates) or 0)
    code = cli.main(["note", "star", item_id, "nope"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 1 and out["count_ok"] == 1 and len(seen) == 1
    assert out["catalog_patched"] is False and "catalog_stat" not in out, "patch 返回 0：catalog_patched 跟着它"
    code = cli.main(["note", "star", item_id, "--off"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    # 单个 target：旧的顶层键照旧（批注块的 starNote 只看这些）
    assert out["item_id"] == item_id and out["status"] == "ok" and out["starred"] is False
    assert out["ok"] is True and out["message"].startswith("已取消收藏 1 篇")


def test_patch_items_reports_stat_inside_lock(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    from link_brain import catalog
    data_path = tmp_path / "_archive" / catalog.DATA_NAME
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps({"built_at": "2026-10-08T05:09:12", "items": [{"id": "x1", "starred": False}]}), encoding="utf-8")
    report = {}
    assert catalog.patch_items({"x1": {"starred": True}}, report=report) == 1
    st = data_path.stat()
    assert report["catalog_stat"] == {"mtime": round(st.st_mtime_ns / 1e6), "size": st.st_size}
    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert data["built_at"] == "2026-10-08T05:09:12", "patch_items 不改 built_at（F4）"
    report2 = {}
    assert catalog.patch_items({"x1": {"starred": True}}, report=report2) == 0
    assert report2 == {}, "没改就不写、不报 stat"
