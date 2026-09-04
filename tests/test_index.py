"""Lot 2：SQLite 索引、去重 HIT、`--refresh` 版本比对。

用 `tests/fixtures/mcp_raw_sanitized.json`（脱敏样本），全程 monkeypatch `fetch_detail`，
不碰网络、不碰真 vault（`LINK_BRAIN_VAULT` 指到 tmp_path）。
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from link_brain import cli, index as index_mod, ingest, storage
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fake_parsed(text: str = "https://example.invalid/share") -> dict:
    return {
        "note_id": NOTE_ID,
        "xsec_token": "FAKE_TOKEN_FOR_TESTS",
        "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
        "input_url": text,
        "input_kind": "url",
    }


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: fake_parsed(text))


# --------------------------------------------------------------------------
# 唯一约束
# --------------------------------------------------------------------------


def test_objects_unique_constraint(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    conn = index_mod.connect()
    source = load_fixture()
    normalized = xhs.normalize(source, fake_parsed(), captured_at="2026-01-01T00:00:00+08:00")
    meta = {
        "item_id": f"xhs-{NOTE_ID}",
        "source": xhs.SOURCE,
        "source_id": NOTE_ID,
        "canonical_url": normalized["note"]["canonical_url"],
        "kind": normalized["note"]["kind"],
        "title": normalized["note"]["title"],
        "author": {
            k: normalized["note"]["author"][k] for k in ("user_id", "nickname", "profile_url")
        },
        "published_at": normalized["note"]["published_at"],
        "first_archived_at": "2026-01-01T00:00:00+08:00",
        "last_checked_at": "2026-01-01T00:00:00+08:00",
        "current_version": 1,
        "visible_note": None,
        "images_complete": True,
        "comments_complete": normalized["capture"]["comments_complete"],
        "attachments_status": "none",
    }
    index_mod.upsert_object(conn, meta, normalized)
    index_mod.upsert_object(conn, meta, normalized)  # 第二次是 UPDATE，不炸唯一约束
    rows = conn.execute("SELECT * FROM objects WHERE source_id = ?", (NOTE_ID,)).fetchall()
    assert len(rows) == 1

    # 手工插入第二条撞 (source, source_id) 唯一约束才是真正验证
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO objects (item_id, source, source_id, canonical_url, kind, title,"
            " author_nickname, author_id, body, tags, published_at, first_archived_at,"
            " last_checked_at, current_version, object_dir, images_complete,"
            " comments_complete, attachments_status) VALUES"
            " ('other-item', ?, ?, 'u', 'text', 't', 'n', 'a', 'b', '[]', 'p', 'f', 'l', 1,"
            " 'd', 1, 'unknown', 'none')",
            (xhs.SOURCE, NOTE_ID),
        )
    conn.close()


# --------------------------------------------------------------------------
# HIT 路径
# --------------------------------------------------------------------------


def test_second_ingest_is_hit_no_network(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_fetch(*a, **k):
        calls["n"] += 1
        return load_fixture()

    monkeypatch.setattr(xhs, "fetch_detail", fake_fetch)

    code1 = cli.main(["ingest", "https://example.invalid/share"])
    assert code1 in (ingest.EXIT_OK, ingest.EXIT_MISSING_CONTENT)  # 图片下载因无网络可能不全，不影响本测试关注点
    assert calls["n"] == 1

    code2 = cli.main(["--verbose", "ingest", "https://example.invalid/share"])
    assert code2 == ingest.EXIT_OK
    assert calls["n"] == 1  # 第二次没有再调 MCP

    raw_root = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "raw"
    versions = sorted(p.name for p in raw_root.iterdir())
    assert versions == ["v0001"]


# --------------------------------------------------------------------------
# refresh：无变化不产生新版本
# --------------------------------------------------------------------------


def test_refresh_no_change_keeps_single_version(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())

    cli.main(["ingest", "https://example.invalid/share"])
    v0001_path = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "raw" / "v0001" / "source.json"
    before_sha = hashlib.sha256(v0001_path.read_bytes()).hexdigest()

    code = cli.main(["ingest", "https://example.invalid/share", "--refresh"])
    assert code == ingest.EXIT_OK

    raw_root = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "raw"
    versions = sorted(p.name for p in raw_root.iterdir())
    assert versions == ["v0001"]
    after_sha = hashlib.sha256(v0001_path.read_bytes()).hexdigest()
    assert before_sha == after_sha


# --------------------------------------------------------------------------
# refresh：有变化产生 v0002，v0001 字节不变
# --------------------------------------------------------------------------


def test_refresh_with_change_writes_v0002(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)

    original = load_fixture()
    changed = copy.deepcopy(original)
    changed["data"]["note"]["title"] = changed["data"]["note"].get("title", "") + "（已编辑）"

    responses = [original, changed]
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: responses.pop(0))

    cli.main(["ingest", "https://example.invalid/share"])
    v0001_path = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "raw" / "v0001" / "source.json"
    v0001_sha_before = hashlib.sha256(v0001_path.read_bytes()).hexdigest()

    code = cli.main(["ingest", "https://example.invalid/share", "--refresh"])
    assert code in (ingest.EXIT_OK, ingest.EXIT_MISSING_CONTENT)

    raw_root = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "raw"
    versions = sorted(p.name for p in raw_root.iterdir())
    assert versions == ["v0001", "v0002"]

    v0001_sha_after = hashlib.sha256(v0001_path.read_bytes()).hexdigest()
    assert v0001_sha_before == v0001_sha_after

    meta = json.loads(
        (tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["current_version"] == 2


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------


def test_search_matches_title(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    cli.main(["ingest", "https://example.invalid/share"])
    capsys.readouterr()

    title = load_fixture()["data"]["note"].get("title") or ""
    keyword = title[:4] if len(title) >= 4 else title
    assert keyword, "fixture 标题为空，换个关键词片段"
    code = cli.main(["search", keyword])
    out = capsys.readouterr().out
    assert code == 0
    assert f"xhs-{NOTE_ID}" in out
