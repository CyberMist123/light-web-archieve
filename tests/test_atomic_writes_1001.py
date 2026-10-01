"""1001 审计 ingest/io-11、media/raw-1：覆盖写一律「同目录临时文件 → fsync → os.replace」。

写到一半被杀（计划任务上限 / lwa 超时 / 关 Obsidian）时，目标文件只能是旧的完整版或新的完整版。
"""

from __future__ import annotations

import json
import os

import pytest

from link_brain import cli, index as index_mod, render as render_mod, storage

from test_attachments import setup_env


def test_write_json_killed_midway_keeps_old_file(tmp_path, monkeypatch):
    target = tmp_path / "meta.json"
    storage.write_json(target, {"v": 1})

    def killed(src, dst):
        raise KeyboardInterrupt("进程在 replace 前被杀")

    monkeypatch.setattr(storage.os, "replace", killed)
    with pytest.raises(KeyboardInterrupt):
        storage.write_json(target, {"v": 2, "big": "x" * 100000})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["meta.json"], "临时文件要清掉"


def test_atomic_write_retries_when_target_briefly_locked(tmp_path, monkeypatch):
    target = tmp_path / "a.md"
    target.write_text("old", encoding="utf-8")
    real, calls = os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("Obsidian 正在读")
        return real(src, dst)

    monkeypatch.setattr(storage.os, "replace", flaky)
    storage.atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new" and len(calls) == 3


def test_render_crash_during_visible_write_keeps_previous_note(tmp_path, monkeypatch):
    """生产路径：render_object 写可见 md 时被杀，她的旧笔记（含手写留言）原样还在。"""
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    conn = index_mod.connect()
    try:
        row = conn.execute("SELECT source, source_id FROM objects").fetchone()
    finally:
        conn.close()
    visible = next(storage.visible_dir().glob("*.md"))
    before = visible.read_text(encoding="utf-8")

    real = storage.atomic_write_bytes

    def killed(path, data):
        if str(path).endswith(".md"):
            raise KeyboardInterrupt("写可见 md 时被杀")
        return real(path, data)

    monkeypatch.setattr(storage, "atomic_write_bytes", killed)
    with pytest.raises(KeyboardInterrupt):
        render_mod.render_object(row["source"], row["source_id"])
    assert visible.read_text(encoding="utf-8") == before
    assert not list(storage.visible_dir().glob(".*.tmp"))
