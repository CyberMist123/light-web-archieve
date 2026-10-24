"""1024 p0-tomb：删掉的不回来（屏蔽以 tombstones.jsonl 为准）+ 判重只看内容 + relations 不重复。

全程隔离 vault（LINK_BRAIN_VAULT → tmp_path），fetch_detail 全 mock，不联网。
"""

from __future__ import annotations

import copy
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from link_brain import cli, index as index_mod, ingest, remove, storage
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"
ITEM_ID = "xhs-" + NOTE_ID


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _parsed(text="https://example.invalid/share", token="FAKE_TOKEN_A"):
    return {
        "note_id": NOTE_ID,
        "xsec_token": token,
        "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
        "input_url": text,
        "input_kind": "url",
    }


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: _parsed(text))
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _fixture())
    return tmp_path


def _ingested(vault):
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)  # 2 = 假图下不到
    return vault / "_archive" / "xiaohongshu" / NOTE_ID


def _jsonl(vault) -> Path:
    return vault / "_archive" / "tombstones.jsonl"


def _no_network(monkeypatch):
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: pytest.fail("已删除的帖不应联网"))


# ---------------------------------------------------------------------------
# 1. 屏蔽的权威来源是 jsonl：删 index.db 重建后仍屏蔽
# ---------------------------------------------------------------------------


def test_tombstone_survives_index_rebuild(vault, monkeypatch):
    _ingested(vault)
    assert remove.delete_items([ITEM_ID])["deleted"] == 1
    assert _jsonl(vault).exists()

    (vault / "_archive" / "index.db").unlink()
    conn = index_mod.connect()
    try:
        index_mod.reindex_all(conn)
        row = conn.execute("SELECT * FROM tombstones WHERE item_id = ?", (ITEM_ID,)).fetchone()
        assert row is not None and row["state"] == "done"
        assert index_mod.get_object(conn, ITEM_ID) is None
    finally:
        conn.close()
    _no_network(monkeypatch)
    assert ingest.ingest_url("https://example.invalid/share")["status"] == "trashed"
    assert ingest.ingest_url("https://example.invalid/share", refresh=True)["status"] == "trashed"


def test_forget_is_recorded_in_jsonl(vault):
    _ingested(vault)
    remove.delete_items([ITEM_ID])
    conn = index_mod.connect()
    remove.purge_item(conn, ITEM_ID)
    assert remove.forget_item(conn, ITEM_ID)["status"] == "forgotten"
    conn.close()
    (vault / "_archive" / "index.db").unlink()
    conn = index_mod.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0] == 0
    finally:
        conn.close()
    ops = [json.loads(line)["op"] for line in _jsonl(vault).read_text(encoding="utf-8").splitlines()]
    assert ops[-1] == "forget"


def test_restore_is_recorded_in_jsonl(vault):
    obj = _ingested(vault)
    remove.delete_items([ITEM_ID])
    conn = index_mod.connect()
    assert remove.restore_item(conn, ITEM_ID)["status"] == "restored"
    conn.close()
    assert obj.is_dir()
    (vault / "_archive" / "index.db").unlink()
    conn = index_mod.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 兼容：旧库只有 index.db 里有屏蔽 → 首次运行导出 jsonl，幂等
# ---------------------------------------------------------------------------


def _legacy_db(vault, *, tombstones=(), relations=()):
    path = vault / "_archive" / "index.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(path))
    raw.executescript("""
    CREATE TABLE tombstones (
        source TEXT NOT NULL, source_id TEXT NOT NULL, item_id TEXT PRIMARY KEY,
        title TEXT, url TEXT, cover TEXT, deleted_at TEXT NOT NULL, trash_dir TEXT NOT NULL,
        UNIQUE(source, source_id));
    """)
    raw.executescript(index_mod.SCHEMA.replace("CREATE TABLE IF NOT EXISTS tombstones", "CREATE TABLE IF NOT EXISTS _unused"))
    for t in tombstones:
        raw.execute("INSERT INTO tombstones VALUES (?,?,?,?,?,?,?,?)", t)
    for r in relations:
        raw.execute("INSERT INTO relations (item_id, origin, actor, actor_id, ingest_kind, note, created_at) VALUES (?,?,?,?,?,?,?)", r)
    raw.commit()
    raw.close()


def test_legacy_tombstones_exported_once(vault, monkeypatch):
    _legacy_db(vault, tombstones=[
        ("xiaohongshu", NOTE_ID, ITEM_ID, "旧删", "https://example.invalid", "", "2026-09-01T00:00:00+00:00",
         "_trash/xiaohongshu/" + NOTE_ID),
    ])
    assert not _jsonl(vault).exists()
    index_mod.connect().close()
    first = _jsonl(vault).read_text(encoding="utf-8")
    events = [json.loads(line) for line in first.splitlines()]
    assert len(events) == 1
    assert events[0]["op"] == "delete" and events[0]["source_id"] == NOTE_ID
    assert events[0]["deleted_at"] == "2026-09-01T00:00:00+00:00"
    index_mod.connect().close()
    assert _jsonl(vault).read_text(encoding="utf-8") == first

    # 删掉 index.db 重建也还在
    (vault / "_archive" / "index.db").unlink()
    conn = index_mod.connect()
    try:
        assert conn.execute("SELECT title FROM tombstones WHERE source_id = ?", (NOTE_ID,)).fetchone()[0] == "旧删"
    finally:
        conn.close()
    _no_network(monkeypatch)
    assert ingest.ingest_url("https://example.invalid/share")["status"] == "trashed"


def test_jsonl_half_written_line_is_skipped(vault):
    _ingested(vault)
    remove.delete_items([ITEM_ID])
    with _jsonl(vault).open("a", encoding="utf-8") as fh:
        fh.write('{"op": "forget", "source": "xiaohon')  # 崩在半行
    (vault / "_archive" / "index.db").unlink()
    conn = index_mod.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0] == 1
        index_mod.append_tombstone_event(conn, {"op": "forget", "source": "xiaohongshu", "source_id": "other", "item_id": "xhs-other"})
    finally:
        conn.close()
    lines = _jsonl(vault).read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["source_id"] == "other"  # 新行不会粘在半行后面


# ---------------------------------------------------------------------------
# 2. 删除顺序：先写屏蔽、再挪文件、最后标完成
# ---------------------------------------------------------------------------


def test_delete_crash_while_moving_keeps_tombstone_and_resumes(vault, monkeypatch):
    obj = _ingested(vault)
    real_move = shutil.move

    def boom(src, dst):
        if Path(src) == obj:
            raise OSError("模拟：挪对象目录时崩了")
        return real_move(src, dst)

    monkeypatch.setattr(remove.shutil, "move", boom)
    out = remove.delete_items([ITEM_ID])
    assert out["ok"] is False and out["results"][0]["status"] == "failed"
    assert obj.is_dir()  # 文件没挪完
    conn = index_mod.connect()
    try:
        row = conn.execute("SELECT * FROM tombstones WHERE item_id = ?", (ITEM_ID,)).fetchone()
        assert row is not None and row["state"] == "pending"  # 屏蔽在
    finally:
        conn.close()
    events = [json.loads(x) for x in _jsonl(vault).read_text(encoding="utf-8").splitlines()]
    assert events[-1]["state"] == "pending"

    # 同步不会把它拉回来
    _no_network(monkeypatch)
    assert ingest.ingest_url("https://example.invalid/share", refresh=True)["status"] == "trashed"

    # 再删一次能接着做完
    monkeypatch.setattr(remove.shutil, "move", real_move)
    assert remove.delete_items([ITEM_ID])["deleted"] == 1
    assert not obj.exists()
    trash = vault / "_trash" / "xiaohongshu" / NOTE_ID
    assert (trash / "object" / "meta.json").exists()
    snapshot = json.loads((trash / "restore.json").read_text(encoding="utf-8"))
    assert snapshot["files"], "续删不能把第一次已挪走的可见笔记从恢复清单里丢掉"
    conn = index_mod.connect()
    try:
        assert conn.execute("SELECT state FROM tombstones WHERE item_id = ?", (ITEM_ID,)).fetchone()[0] == "done"
        # 也能恢复回去
        assert remove.restore_item(conn, ITEM_ID)["status"] == "restored"
    finally:
        conn.close()
    assert obj.is_dir()
    for f in snapshot["files"]:
        assert (vault / f["original"]).exists()


def test_delete_tombstone_write_fails_files_untouched(vault, monkeypatch):
    obj = _ingested(vault)

    def fail(*a, **k):
        raise OSError("模拟：屏蔽写不进去")

    monkeypatch.setattr(index_mod, "append_tombstone_event", fail)
    out = remove.delete_items([ITEM_ID])
    assert out["ok"] is False
    assert obj.is_dir() and (obj / "meta.json").exists()
    conn = index_mod.connect()
    try:
        assert index_mod.get_object(conn, ITEM_ID) is not None
    finally:
        conn.close()


def test_restore_finishes_pending_delete_first(vault, monkeypatch):
    obj = _ingested(vault)
    real_move = shutil.move
    monkeypatch.setattr(remove.shutil, "move",
                        lambda s, d: (_ for _ in ()).throw(OSError("崩")) if Path(s) == obj else real_move(s, d))
    remove.delete_items([ITEM_ID])
    monkeypatch.setattr(remove.shutil, "move", real_move)
    conn = index_mod.connect()
    try:
        assert remove.restore_item(conn, ITEM_ID)["status"] == "restored"
        assert conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0] == 0
        assert index_mod.get_object(conn, ITEM_ID) is not None
    finally:
        conn.close()
    assert obj.is_dir()


# ---------------------------------------------------------------------------
# 3. 判重指纹只看内容
# ---------------------------------------------------------------------------


def _normalize(token="T1", input_url="https://a.invalid/1", captured_at="2026-10-01T00:00:00+00:00", seconds=1.0):
    src = xhs.normalize(_fixture(), _parsed(input_url, token), captured_at=captured_at,
                        web_probe={"ok": False, "error": "x", "url": None})
    src["capture"]["comment_load"] = {"seconds": seconds}
    return src


def test_hash_ignores_token_url_and_timing():
    a = _normalize()
    b = _normalize(token="T2", input_url="https://b.invalid/2", captured_at="2026-10-24T00:00:00+00:00", seconds=9.5)
    assert index_mod.normalized_source_sha256(a) == index_mod.normalized_source_sha256(b)
    # 图片地址里的签名 / 时间戳段变了也不算内容变
    for img in b["note"]["images"]:
        if img.get("url"):
            img["url"] = img["url"] + "?sign=zzz"
    assert index_mod.normalized_source_sha256(a) == index_mod.normalized_source_sha256(b)


def test_hash_still_sees_content_changes():
    a = _normalize()
    base = index_mod.normalized_source_sha256(a)
    for mutate in (
        lambda s: s["note"].__setitem__("title", "改了标题"),
        lambda s: s["note"].__setitem__("body", s["note"]["body"] + "补一句"),
        lambda s: s["note"]["images"].pop(),
        lambda s: s["comments"].append({"comment_id": "new", "text": "新评论", "author": {"user_id": "u9"}}),
        lambda s: s["comments"][0].__setitem__("text", "评论被改"),
    ):
        b = copy.deepcopy(a)
        mutate(b)
        assert index_mod.normalized_source_sha256(b) != base


def test_refresh_with_new_token_writes_no_new_version(vault, monkeypatch):
    obj = _ingested(vault)
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: _parsed("https://other.invalid/x", "FAKE_TOKEN_B"))
    assert cli.main(["ingest", "https://other.invalid/x", "--refresh"]) in (0, 2)
    assert storage.existing_versions(xhs.SOURCE, NOTE_ID) == [1]
    assert not (obj / "raw" / "v0002").exists()


def test_old_caliber_hash_does_not_cause_extra_version(vault, monkeypatch):
    obj = _ingested(vault)
    # 模拟旧口径存下的哈希（旧口径把口令 / 输入网址 / 耗时都算进去，和新口径对不上）
    conn = index_mod.connect()
    conn.execute("UPDATE sources SET source_sha256 = ? WHERE item_id = ?", ("0" * 64, ITEM_ID))
    conn.commit()
    conn.close()
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: _parsed("https://other.invalid/x", "FAKE_TOKEN_B"))
    assert cli.main(["ingest", "https://other.invalid/x", "--refresh"]) in (0, 2)
    assert not (obj / "raw" / "v0002").exists()
    conn = index_mod.connect()
    try:
        stored = conn.execute("SELECT source_sha256 FROM sources WHERE item_id = ?", (ITEM_ID,)).fetchone()[0]
    finally:
        conn.close()
    assert stored != "0" * 64  # 顺手改成新口径


# ---------------------------------------------------------------------------
# 4. relations 不重复
# ---------------------------------------------------------------------------


def _relations(item_id=ITEM_ID):
    conn = index_mod.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM relations WHERE item_id = ?", (item_id,)).fetchone()[0]
    finally:
        conn.close()


def test_same_post_synced_twice_keeps_one_relation(vault):
    _ingested(vault)
    n = _relations()
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)  # 2 = 假图下不到
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)  # 2 = 假图下不到
    assert _relations() == n == 1


def test_different_origin_still_adds_relation(vault):
    _ingested(vault)
    conn = index_mod.connect()
    try:
        index_mod.add_relation(conn, item_id=ITEM_ID, origin="telegram", actor="human", ingest_kind="shared",
                               note="她分享时说的话", created_at="2026-10-24T00:00:00+00:00")
    finally:
        conn.close()
    assert _relations() == 2


def test_legacy_duplicate_relations_deduped_idempotent(vault):
    dup = (ITEM_ID, "favorites", "human", None, "favorite", None)
    other = ("xhs-2", "cli", "human", None, "shared", "附言")
    _legacy_db(vault, relations=[dup + ("2026-09-01",), dup + ("2026-09-02",), dup + ("2026-09-03",),
                                 other + ("2026-09-01",), other + ("2026-09-05",)])
    # 旧库 objects 里没有这两篇：FK 只在插入时查，这里用裸连接插的，模拟真库历史
    conn = index_mod.connect()
    try:
        rows = conn.execute("SELECT item_id, created_at FROM relations ORDER BY item_id").fetchall()
        assert [tuple(r) for r in rows] == [(ITEM_ID, "2026-09-01"), ("xhs-2", "2026-09-01")]  # 留最早那条
    finally:
        conn.close()
    conn = index_mod.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 2
    finally:
        conn.close()


def test_restore_old_snapshot_with_duplicate_relations(vault):
    _ingested(vault)
    remove.delete_items([ITEM_ID])
    restore_json = vault / "_trash" / "xiaohongshu" / NOTE_ID / "restore.json"
    snap = json.loads(restore_json.read_text(encoding="utf-8"))
    rel = snap["tables"]["relations"][0]
    snap["tables"]["relations"] = [dict(rel, id=i, created_at=f"2026-09-0{i}") for i in range(1, 4)]  # 旧快照带重复
    restore_json.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    conn = index_mod.connect()
    try:
        assert remove.restore_item(conn, ITEM_ID)["status"] == "restored"
    finally:
        conn.close()
    assert _relations() == 1
