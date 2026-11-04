"""1104：一个坏对象不能拖垮整批——只记它失败、接着下一个。

每组都是「好—坏—好」三篇：两篇好的照常完成，坏的那篇进失败 / 跳过清单。覆盖：
缺作者 user_id（可缺省，照常进）、缺身份字段、非法版本号、非对象 JSON、不可读笔记、坏媒体条目。全部走 tmp vault，不联网。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import catalog, cli, enrich, storage
from link_brain import index as index_mod
from tests.test_catalog import _make_object


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "_archive").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(storage.ENV_VAULT, str(v))
    monkeypatch.delenv("LINK_BRAIN_OBSIDIAN_DIR", raising=False)
    return v


# ── reindex ──

def _archived(vault: Path, sid: str, *, meta_patch: dict | None = None, drop: tuple[str, ...] = (),
              source_doc=None) -> None:
    """落一篇最小的归档（meta.json + raw/v0001/{manifest,source}.json），给 reindex 读。"""
    obj = vault / "_archive" / "xiaohongshu" / sid
    raw = obj / "raw" / "v0001"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "manifest.json").write_text(json.dumps({"media": []}), encoding="utf-8")
    doc = source_doc if source_doc is not None else {
        "source": "xiaohongshu", "source_id": sid,
        "note": {"title": f"标题{sid}", "body": "正文", "hashtags": []},
        "capture": {"captured_at": "2026-11-01T10:00:00+10:00", "adapter": "test",
                    "input_url": None, "input_kind": None},
    }
    (raw / "source.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    meta = {
        "item_id": f"xhs-{sid}", "source": "xiaohongshu", "source_id": sid,
        "canonical_url": f"https://example.invalid/{sid}", "kind": "image", "title": f"标题{sid}",
        "author": {"nickname": "某人", "user_id": "u1"}, "published_at": None,
        "first_archived_at": "2026-11-01T10:00:00+10:00", "last_checked_at": "2026-11-01T10:00:00+10:00",
        "current_version": 1, "images_complete": True, "comments_complete": "unknown",
        "attachments_status": "none",
    }
    meta.update(meta_patch or {})
    for k in drop:
        meta.pop(k, None)
    (obj / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _reindex():
    conn = index_mod.connect()
    try:
        done = index_mod.reindex_all(conn)
        rows = {r["item_id"]: dict(r) for r in conn.execute("SELECT * FROM objects")}
    finally:
        conn.close()
    return done, rows


def test_reindex_missing_author_id_is_ok(vault):
    _archived(vault, "a1", meta_patch={"author": {"nickname": "某人"}})
    _archived(vault, "a2", drop=("author",))
    done, rows = _reindex()
    assert sorted(done) == ["xhs-a1", "xhs-a2"] and done.failed == []
    assert rows["xhs-a1"]["author_id"] == "" and rows["xhs-a2"]["author_nickname"] == ""


@pytest.mark.parametrize("bad", [
    {"drop": ("source_id",)},
    {"drop": ("item_id",)},
    {"meta_patch": {"current_version": "abc"}},
    {"meta_patch": {"current_version": 0}},
    {"source_doc": ["不是对象"]},
], ids=["no-source-id", "no-item-id", "version-str", "version-zero", "source-not-object"])
def test_reindex_good_bad_good(vault, bad):
    _archived(vault, "g1")
    _archived(vault, "g2bad", **bad)
    _archived(vault, "g3")
    done, rows = _reindex()
    assert list(done) == ["xhs-g1", "xhs-g3"]
    assert set(rows) == {"xhs-g1", "xhs-g3"}
    assert len(done.failed) == 1
    f = done.failed[0]
    assert f["status"] == "failed" and f["path"] == "_archive/xiaohongshu/g2bad" and f["error"]


def test_reindex_meta_not_object(vault):
    _archived(vault, "g1")
    _archived(vault, "g2bad")
    (vault / "_archive" / "xiaohongshu" / "g2bad" / "meta.json").write_text("[1, 2]", encoding="utf-8")
    _archived(vault, "g3")
    done, _ = _reindex()
    assert list(done) == ["xhs-g1", "xhs-g3"]
    assert done.failed[0]["item_id"] == "" and "不是对象" in done.failed[0]["error"]


def test_reindex_cli_exit_code(vault, capsys):
    _archived(vault, "g1")
    assert cli.main(["reindex"]) == cli.EXIT_OK
    _archived(vault, "g2bad", meta_patch={"current_version": "x"})
    assert cli.main(["reindex"]) == cli.EXIT_ERROR
    assert "g2bad" in capsys.readouterr().err


# ── catalog ──

def _three(vault):
    _make_object(vault, "c1", title="好一", tags=["a"], summary="x", stem="好一")
    _make_object(vault, "c2", title="坏的", tags=["a"], summary="x", stem="坏的")
    _make_object(vault, "c3", title="好三", tags=["a"], summary="x", stem="好三")
    return vault / "_archive" / "xiaohongshu" / "c2"


def _break_version(obj, vault):
    meta = json.loads((obj / "meta.json").read_text(encoding="utf-8"))
    (obj / "meta.json").write_text(json.dumps({**meta, "current_version": "v2"}), encoding="utf-8")


def _break_meta(obj, vault):
    (obj / "meta.json").write_text('"字符串"', encoding="utf-8")


def _break_source(obj, vault):
    (obj / "raw" / "v0001" / "source.json").write_text("[1, 2, 3]", encoding="utf-8")


def _break_note(obj, vault):
    (vault / "Web" / "Xiaohongshu" / "坏的.md").write_bytes(b"---\ntags: [a]\n---\n\xff\xfe\xfa")


@pytest.mark.parametrize("breaker", [_break_version, _break_meta, _break_source, _break_note],
                         ids=["bad-version", "meta-not-object", "source-not-object", "note-unreadable"])
def test_catalog_good_bad_good(vault, breaker):
    breaker(_three(vault), vault)
    skipped: list = []
    items = catalog.collect(vault, skipped=skipped)
    assert sorted(it["title"] for it in items) == ["好一", "好三"]
    assert len(skipped) == 1 and skipped[0]["path"] == "_archive/xiaohongshu/c2"
    assert skipped[0]["status"] == "skipped" and skipped[0]["error"]


def test_catalog_derived_not_object_is_tolerated(vault):
    obj = _three(vault)
    (obj / "derived" / "extracted.json").write_text("[]", encoding="utf-8")
    (obj / "derived" / "vision.json").write_text('"x"', encoding="utf-8")
    skipped: list = []
    items = catalog.collect(vault, skipped=skipped)
    assert len(items) == 3 and skipped == []


def test_catalog_run_reports_skipped(vault, capsys):
    _break_source(_three(vault), vault)

    class Args:
        print_cats = False
        if_dirty = False

    assert catalog.run(Args()) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True and out["total"] == 2
    assert [x["item_id"] for x in out["skipped"]] == ["xhs-c2"]
    assert "1 篇数据有问题" in out["message"]


# ── enrich ──

def _index_rows(vault, sids):
    conn = index_mod.connect()
    try:
        for sid in sids:
            conn.execute(
                "INSERT INTO objects (item_id, source, source_id, canonical_url, kind, first_archived_at, "
                "last_checked_at, current_version, object_dir) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"xhs-{sid}", "xiaohongshu", sid, "https://example.invalid", "image",
                 "2026-11-01T10:00:00+10:00", "2026-11-01T10:00:00+10:00", 1, f"_archive/xiaohongshu/{sid}"))
        conn.commit()
    finally:
        conn.close()


def test_enrich_needs_tolerates_bad_media(vault):
    _three(vault)
    obj = vault / "_archive" / "xiaohongshu" / "c2"
    (obj / "raw" / "v0001" / "manifest.json").write_text(json.dumps({"media": [
        "不是对象", {"file": 123}, {"file": None}, {"file": "raw/v0001/assets/image-001.webp"}]}), encoding="utf-8")
    (obj / "derived" / "vision.json").write_text("[]", encoding="utf-8")
    assert "vision" in enrich.needs("xiaohongshu", "c2", llm=False)
    (obj / "raw" / "v0001" / "manifest.json").write_text("[1]", encoding="utf-8")
    assert enrich.needs("xiaohongshu", "c2", llm=False) == []
    (obj / "meta.json").write_text("[]", encoding="utf-8")
    assert enrich.needs("xiaohongshu", "c2", llm=False) == []


def test_enrich_candidates_good_bad_good(vault, monkeypatch):
    _index_rows(vault, ["e1", "e2", "e3"])

    def fake_needs(key, sid, **kw):
        if sid == "e2":
            raise KeyError("media")
        return ["vision"]

    monkeypatch.setattr(enrich, "needs", fake_needs)
    bad: list = []
    got = enrich.candidates(bad=bad)
    assert [sid for _, sid, _, _ in got] == ["e1", "e3"]
    assert bad[0]["item_id"] == "xhs-e2" and bad[0]["status"] == "failed"


def test_enrich_items_good_bad_good(vault, monkeypatch):
    def fake_one(key, sid, **kw):
        if sid == "e2":
            raise TypeError("坏数据")
        return {"item_id": f"xhs-{sid}", "status": "done"}

    monkeypatch.setattr(enrich, "enrich_one", fake_one)
    out = enrich.enrich_items([("xiaohongshu", s) for s in ("e1", "e2", "e3")], verbose=False)
    assert out["done"] == ["xhs-e1", "xhs-e3"]
    assert out["failed"][0]["item_id"] == "xhs-e2" and "坏数据" in out["failed"][0]["error"]


def test_enrich_run_pending_reports_bad_and_finishes_good(vault, monkeypatch, capsys):
    _index_rows(vault, ["e1", "e2", "e3"])
    monkeypatch.setattr(enrich, "needs", lambda key, sid, **kw: (_ for _ in ()).throw(KeyError("x")) if sid == "e2" else ["vision"])
    monkeypatch.setattr(enrich, "enrich_one", lambda key, sid, **kw: {"item_id": f"xhs-{sid}", "status": "done"})

    class Args:
        pending = True
        item = None
        limit = 0
        budget_min = 0

    assert enrich.run(Args()) == enrich.EXIT_ERROR
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["done"] == ["xhs-e1", "xhs-e3"]
    assert [f["item_id"] for f in out["failed"]] == ["xhs-e2"]
