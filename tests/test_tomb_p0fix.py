"""1024 第一波返修（复审 tomb）：pending 状态下彻底删除 / 清空；已删完却报没删掉；读函数不偷偷提交别人的事务；
对账不吃掉别的进程刚写的屏蔽。"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from link_brain import index as index_mod, remove
from test_tomb_p0_1024 import ITEM_ID, NOTE_ID, _ingested, _jsonl, vault  # noqa: F401 - fixture


def _crash_on_object_move(monkeypatch, obj):
    real_move = shutil.move
    monkeypatch.setattr(remove.shutil, "move",
                        lambda s, d: (_ for _ in ()).throw(OSError("被占用")) if Path(s) == obj else real_move(s, d))
    return real_move


def _events(vault):
    return [json.loads(x) for x in _jsonl(vault).read_text(encoding="utf-8").splitlines() if x.strip()]


def test_purge_pending_delete_finishes_delete_first(vault, monkeypatch):
    """tomb#2：删到一半（对象目录没挪走）点「彻底删除」：要把对象目录也删掉，objects 行也没了，之后不再冒回回收站。"""
    obj = _ingested(vault)
    real_move = _crash_on_object_move(monkeypatch, obj)
    remove.delete_items([ITEM_ID])
    assert obj.is_dir()
    monkeypatch.setattr(remove.shutil, "move", real_move)
    conn = index_mod.connect()
    try:
        assert remove.purge_item(conn, ITEM_ID)["status"] == "purged"
        assert not obj.exists(), "修前：purge 只删了回收站目录，对象还留在 _archive"
        assert index_mod.get_object(conn, ITEM_ID) is None
        assert conn.execute("SELECT state FROM tombstones WHERE item_id = ?", (ITEM_ID,)).fetchone()[0] == "done"
        remove.finish_pending(conn)
    finally:
        conn.close()
    assert not (vault / "_trash" / "xiaohongshu" / NOTE_ID).exists(), "彻底删除后不能又以可恢复的样子回到回收站"


def test_purge_pending_still_locked_says_failed(vault, monkeypatch):
    """对象目录还是挪不动：彻底删除如实报失败，不报成功。"""
    obj = _ingested(vault)
    _crash_on_object_move(monkeypatch, obj)
    remove.delete_items([ITEM_ID])
    conn = index_mod.connect()
    try:
        out = remove._one(remove.purge_item, conn, ITEM_ID)
    finally:
        conn.close()
    assert out["status"] == "failed"
    assert obj.is_dir()


def test_done_line_write_fails_after_commit_reports_deleted(vault, monkeypatch):
    """tomb#6：④ 已提交、jsonl 的 done 行写不上：这篇其实已经删了，报 deleted 并说下次自动补；下次真能补上（tomb#7 缺口）。"""
    obj = _ingested(vault)
    real = index_mod.append_tombstone_event

    def fail_done(conn, event):
        if event.get("state") == "done":
            raise OSError("模拟：done 行写不进去")
        return real(conn, event)

    monkeypatch.setattr(index_mod, "append_tombstone_event", fail_done)
    out = remove.delete_items([ITEM_ID])
    assert out["ok"] is True and out["results"][0]["status"] == "deleted", out
    assert "下次" in (out["results"][0].get("warning") or "")
    assert not obj.exists()
    assert _events(vault)[-1]["state"] == "pending"
    monkeypatch.setattr(index_mod, "append_tombstone_event", real)
    conn = index_mod.connect()  # jsonl 最后一行是 pending → 缓存对齐成 pending → 续删走 _finish_without_row
    try:
        assert [r["status"] for r in remove.finish_pending(conn)] == ["deleted"]
        assert conn.execute("SELECT state FROM tombstones WHERE item_id = ?", (ITEM_ID,)).fetchone()[0] == "done"
    finally:
        conn.close()
    assert _events(vault)[-1]["state"] == "done"


def test_latest_source_sha256_does_not_commit_callers_transaction(vault):
    """tomb#5：调用方事务进行到一半时调它，不能把半截事务提交掉。"""
    _ingested(vault)
    conn = index_mod.connect()
    try:
        conn.execute("UPDATE sources SET source_sha256 = 'stale' WHERE item_id = ?", (ITEM_ID,))
        conn.execute("UPDATE objects SET title = '半截事务' WHERE item_id = ?", (ITEM_ID,))
        assert conn.in_transaction
        index_mod.latest_source_sha256(conn, ITEM_ID)
        assert conn.in_transaction, "修前：读函数里 commit 了，调用方的半截写也被提交"
        conn.rollback()
        assert index_mod.get_object(conn, ITEM_ID)["title"] != "半截事务"
    finally:
        conn.close()


def test_sync_tombstones_does_not_drop_row_written_concurrently(vault, monkeypatch):
    """tomb#3：A 读 jsonl（forget 在最后）之后、比对缓存之前，B 追加了新的 delete 并写好缓存：A 不能删掉 B 的屏蔽。"""
    _ingested(vault)
    conn = index_mod.connect()
    row = {"source": "xiaohongshu", "source_id": NOTE_ID, "item_id": ITEM_ID}
    index_mod.write_tombstone(conn, {**row, "title": "t", "trash_dir": "_trash/x"})
    index_mod.clear_tombstone(conn, row, "forget")
    conn.close()

    real_read = index_mod._read_events
    fired = threading.Event()

    def racy_read(path):
        events = real_read(path)
        if not fired.is_set():
            fired.set()
            other = index_mod.connect()  # B：在 A 读完 jsonl 之后删这篇
            try:
                index_mod.write_tombstone(other, {**row, "title": "t", "trash_dir": "_trash/x", "state": "pending"})
            finally:
                other.close()
        return events

    monkeypatch.setattr(index_mod, "_read_events", racy_read)
    conn = index_mod.connect()  # A
    monkeypatch.setattr(index_mod, "_read_events", real_read)
    try:
        got = conn.execute("SELECT state FROM tombstones WHERE item_id = ?", (ITEM_ID,)).fetchone()
        assert got is not None and got[0] == "pending", "修前：A 拿旧的 jsonl 判「已解除」，把 B 刚写的屏蔽删了"
    finally:
        conn.close()
