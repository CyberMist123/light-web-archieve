"""Shared rendering/catalog/logging dispatch, with offline sanitized inputs."""
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from link_brain import actionlog, catalog, render, sources, storage
from link_brain.sources.xiaohongshu import adapter
from tests.tools import import_scan


def test_render_has_no_xhs_import():
    assert not [b for a, b in import_scan.edges()
                if a == "link_brain.render" and b.startswith(import_scan.XHS)]


def test_catalog_enumerates_sources_and_optional_albums(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "names", lambda: ["example", "other"])
    monkeypatch.setattr(sources, "get", lambda name: SimpleNamespace(
        capabilities=frozenset(), item_flags=lambda obj: [], source_open_url=lambda note, meta: None))
    for name in sources.names():
        obj = tmp_path / "_archive" / name / "sample"
        obj.mkdir(parents=True)
        storage.write_json(obj / "meta.json", {"source": name, "item_id": name + "-sample", "current_version": 1})
    items = catalog.collect(tmp_path)
    assert [it["source"] for it in items] == ["example", "other"]
    assert all(it["albums"] == [] for it in items)
    assert [it["source"] for it in catalog.collect(tmp_path, "other")] == ["other"]


def test_catalog_source_flags(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "get", lambda name: SimpleNamespace(
        item_flags=lambda obj: calls.append((name, obj)) or [
            {"code": "PERMANENT.NOTE_GONE", "detail": "example unavailable"}]))
    monkeypatch.setattr(catalog, "_problem", lambda code, reason, action=None, next_at=None: {"code": code, "hover": reason})
    obj = tmp_path / "_archive/example/sample"
    obj.mkdir(parents=True)
    storage.write_json(obj / "meta.json", {"source": "example"})
    out = catalog.item_problems(obj, {}, {}, {}, {})
    assert calls == [("example", obj)]
    assert any("example unavailable" in p["hover"] for p in out)


def test_actionlog_source_route_and_home(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "names", lambda: ["example"])
    monkeypatch.setattr(sources, "get", lambda name: SimpleNamespace(
        action_for_route=lambda route: "example_action" if route == "/example" else "",
        action_home=lambda: tmp_path, action_lock_holder=lambda: {"owner": "example owner"}))
    monkeypatch.delenv("LWA_TRIGGER", raising=False)
    assert actionlog.action_for_route("/example") == "example_action"
    assert actionlog.path() == tmp_path / actionlog.FILE
    assert actionlog.trigger() == "example owner"


def snapshot(render_mod=render):
    raw = json.loads((Path(__file__).parent / "fixtures/mcp_raw_sanitized.json").read_text(encoding="utf-8"))
    source = adapter.normalize(raw, {"note_id": "0000000000000000deadbeef",
        "canonical_url": "https://example.org/note", "input_url": "https://example.org/note",
        "input_kind": "url"}, captured_at="2026-09-04T12:00:00+10:00")
    # Normalization reads the OS timezone; rendering parity uses an explicit fixture date.
    source["note"]["published_at"] = "2026-09-04T12:00:00+10:00"
    source["comments"][0]["sub_comment_count"] = len(source["comments"][0].get("sub_comments") or []) + 3
    meta = {"source": "xiaohongshu", "source_id": "0000000000000000deadbeef",
        "item_id": "xhs-0000000000000000deadbeef", "canonical_url": "https://example.org/note",
        "current_version": 1, "first_archived_at": "2026-09-04T12:00:00+10:00"}
    source["capture"]["comment_load"] = {"replies_missing": 3, "floors_loaded": 2,
        "gaps": [{"comment_id": source["comments"][0]["comment_id"], "missing": 3, "reason": "stalled"}]}
    args = dict(source=source, meta=meta, object_rel="_archive/xiaohongshu/0000000000000000deadbeef")
    return render_mod.render_visible_md(**args, manifest={"media": []}, existing_text=None) + "\n<!-- AGENT -->\n" + render_mod.render_agent_md(source=source, meta=meta, vision={})


def test_single_source_markdown_is_unchanged():
    expected = json.loads((Path(__file__).parent / "fixtures/shared-sources-render.json").read_text(encoding="utf-8"))["markdown"]
    assert snapshot() == expected


def catalog_log_snapshot(tmp_path, monkeypatch, catalog_mod=catalog, log_mod=actionlog):
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LWA_TRIGGER", "manual")
    obj = tmp_path / "_archive/xiaohongshu/sample"
    storage.write_json(obj / "meta.json", {"source": "xiaohongshu", "source_id": "sample",
        "item_id": "xhs-sample", "title": "Sample", "current_version": 1,
        "first_archived_at": "2026-09-04T12:00:00+10:00"})
    storage.write_json(obj / "raw/v0001/source.json", {"note": {"body": "Sample body"}})
    items = catalog_mod.collect(tmp_path)
    monkeypatch.setattr(log_mod, "_now", lambda: datetime.fromisoformat("2026-09-04T12:00:00+10:00"))
    row = log_mod.record(log_mod.action_for_route("/api/v1/favorites?limit=1"), ok=False,
                         detail="[ACCOUNT_RISK] error_code=300011 触发接口=sub_comments")
    return {"catalog": items, "actionlog": row}


def test_single_source_catalog_and_log_are_unchanged(tmp_path, monkeypatch):
    expected = json.loads((Path(__file__).parent / "fixtures/shared-sources-catalog-log.json").read_text(encoding="utf-8"))
    assert catalog_log_snapshot(tmp_path, monkeypatch) == expected
