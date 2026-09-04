"""SQLite 索引（objects / sources / relations 三表）。表结构见 docs/FORMAT.md §8。

去重只认 `(source, source_id)`；`ingest` 命中就直接返回已有对象，不联网不下载。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from . import storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    item_id            TEXT PRIMARY KEY,
    source             TEXT NOT NULL,
    source_id          TEXT NOT NULL,
    canonical_url      TEXT NOT NULL,
    kind               TEXT NOT NULL,
    title              TEXT,
    author_nickname    TEXT,
    author_id          TEXT,
    body               TEXT,
    tags               TEXT,
    published_at       TEXT,
    first_archived_at  TEXT NOT NULL,
    last_checked_at    TEXT NOT NULL,
    current_version    INTEGER NOT NULL,
    object_dir         TEXT NOT NULL,
    visible_note       TEXT,
    images_complete    INTEGER NOT NULL DEFAULT 1,
    comments_complete  TEXT NOT NULL DEFAULT 'unknown',
    attachments_status TEXT NOT NULL DEFAULT 'none',
    summary            TEXT,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       TEXT NOT NULL REFERENCES objects(item_id) ON DELETE CASCADE,
    version       INTEGER NOT NULL,
    raw_dir       TEXT NOT NULL,
    captured_at   TEXT NOT NULL,
    adapter       TEXT NOT NULL,
    input_url     TEXT,
    input_kind    TEXT,
    source_sha256 TEXT NOT NULL,
    UNIQUE (item_id, version)
);

CREATE TABLE IF NOT EXISTS relations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL REFERENCES objects(item_id) ON DELETE CASCADE,
    origin       TEXT NOT NULL,
    actor        TEXT NOT NULL,
    actor_id     TEXT,
    ingest_kind  TEXT NOT NULL,
    note         TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_objects_title ON objects(title);
CREATE INDEX IF NOT EXISTS idx_relations_item ON relations(item_id);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or storage.index_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def relpath_from_vault(path: Path) -> str:
    return str(Path(path).resolve().relative_to(storage.vault_root().resolve())).replace("\\", "/")


def normalized_source_sha256(source: dict[str, Any]) -> str:
    """source.json 规范化后的 sha256：忽略 engagement 数字（点赞/收藏等会自然波动的字段）。"""
    clone = json.loads(json.dumps(source))
    note = clone.get("note") or {}
    note.pop("engagement", None)
    clone.get("capture", {}).pop("captured_at", None)
    payload = json.dumps(clone, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_object(conn: sqlite3.Connection, source: str, source_id: str) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT * FROM objects WHERE source = ? AND source_id = ?", (source, source_id)
    )
    return cur.fetchone()


def get_object(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM objects WHERE item_id = ?", (item_id,))
    return cur.fetchone()


def upsert_object(conn: sqlite3.Connection, meta: dict[str, Any], source_doc: dict[str, Any]) -> None:
    note = source_doc["note"]
    object_dir = storage.object_dir(meta["source"], meta["source_id"])
    conn.execute(
        """
        INSERT INTO objects (
            item_id, source, source_id, canonical_url, kind, title,
            author_nickname, author_id, body, tags, published_at,
            first_archived_at, last_checked_at, current_version, object_dir,
            visible_note, images_complete, comments_complete, attachments_status, summary
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(item_id) DO UPDATE SET
            canonical_url=excluded.canonical_url,
            kind=excluded.kind,
            title=excluded.title,
            author_nickname=excluded.author_nickname,
            author_id=excluded.author_id,
            body=excluded.body,
            tags=excluded.tags,
            published_at=excluded.published_at,
            last_checked_at=excluded.last_checked_at,
            current_version=excluded.current_version,
            visible_note=excluded.visible_note,
            images_complete=excluded.images_complete,
            comments_complete=excluded.comments_complete,
            attachments_status=excluded.attachments_status
        """,
        (
            meta["item_id"],
            meta["source"],
            meta["source_id"],
            meta["canonical_url"],
            meta["kind"],
            meta["title"],
            meta["author"]["nickname"],
            meta["author"]["user_id"],
            note.get("body"),
            json.dumps(note.get("hashtags") or [], ensure_ascii=False),
            meta["published_at"],
            meta["first_archived_at"],
            meta["last_checked_at"],
            meta["current_version"],
            relpath_from_vault(object_dir),
            meta.get("visible_note"),
            1 if meta["images_complete"] else 0,
            meta["comments_complete"],
            meta["attachments_status"],
            meta.get("summary"),
        ),
    )
    conn.commit()


def add_source_version(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    version: int,
    raw_dir: Path,
    captured_at: str,
    adapter: str,
    input_url: str | None,
    input_kind: str | None,
    source_sha256: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO sources (
            item_id, version, raw_dir, captured_at, adapter, input_url, input_kind, source_sha256
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            item_id,
            version,
            relpath_from_vault(raw_dir),
            captured_at,
            adapter,
            input_url,
            input_kind,
            source_sha256,
        ),
    )
    conn.commit()


def latest_source_sha256(conn: sqlite3.Connection, item_id: str) -> str | None:
    cur = conn.execute(
        "SELECT source_sha256 FROM sources WHERE item_id = ? ORDER BY version DESC LIMIT 1",
        (item_id,),
    )
    row = cur.fetchone()
    return row["source_sha256"] if row else None


def add_relation(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    origin: str,
    actor: str,
    ingest_kind: str,
    note: str | None,
    created_at: str,
    actor_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO relations (item_id, origin, actor, actor_id, ingest_kind, note, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (item_id, origin, actor, actor_id, ingest_kind, note, created_at),
    )
    conn.commit()


def set_attachments_status(conn: sqlite3.Connection, item_id: str, status: str) -> None:
    """附件字节下完之后把索引里的状态也拨过来。

    2026-09-05 踩到：只改了 meta.json，索引还停在 metadata_only，
    于是 `pdf2md --all` 按索引挑对象，一个都没挑中。
    """
    conn.execute(
        "UPDATE objects SET attachments_status = ? WHERE item_id = ?", (status, item_id)
    )
    conn.commit()


def search(conn: sqlite3.Connection, query: str, *, limit: int = 20) -> list[sqlite3.Row]:
    like = f"%{query}%"
    cur = conn.execute(
        """
        SELECT item_id, title, body, tags, kind, canonical_url, first_archived_at FROM objects
        WHERE title LIKE ? OR body LIKE ?
        ORDER BY first_archived_at DESC
        LIMIT ?
        """,
        (like, like, limit),
    )
    return cur.fetchall()


def reindex_all(conn: sqlite3.Connection, *, verbose: bool = False) -> list[str]:
    """从已有的 `vault/_archive/<source>/<id>/{meta.json,raw/vNNNN/source.json}` 回填索引。

    不重抓、不联网。用于 Lot 1 已落盘但 `index.db` 还没建 / 被删掉重建的场景。
    已存在的对象会被跳过（`INSERT OR IGNORE`），不会覆盖当前 relations 历史。
    返回本次回填的 item_id 列表。
    """
    root = storage.archive_root()
    reindexed: list[str] = []
    if not root.is_dir():
        return reindexed
    for source_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        source = source_dir.name
        for object_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            meta_path = object_dir / "meta.json"
            if not meta_path.exists():
                continue
            meta = storage.read_json(meta_path)
            item_id = meta["item_id"]
            source_id = meta["source_id"]
            versions = storage.existing_versions(source, source_id)
            if not versions:
                continue
            current_raw = storage.raw_dir(source, source_id, meta["current_version"]) / "source.json"
            if not current_raw.exists():
                continue
            # 先插 objects（FK 目标），再补 sources 各版本
            upsert_object(conn, meta, storage.read_json(current_raw))
            for version in versions:
                raw_dir = storage.raw_dir(source, source_id, version)
                source_json = raw_dir / "source.json"
                if not source_json.exists():
                    continue
                source_doc = storage.read_json(source_json)
                sha = normalized_source_sha256(source_doc)
                add_source_version(
                    conn,
                    item_id=item_id,
                    version=version,
                    raw_dir=raw_dir,
                    captured_at=source_doc["capture"]["captured_at"],
                    adapter=source_doc["capture"]["adapter"],
                    input_url=source_doc["capture"]["input_url"],
                    input_kind=source_doc["capture"]["input_kind"],
                    source_sha256=sha,
                )
            already_has_relation = conn.execute(
                "SELECT 1 FROM relations WHERE item_id = ? LIMIT 1", (item_id,)
            ).fetchone()
            if not already_has_relation:
                add_relation(
                    conn,
                    item_id=item_id,
                    origin=meta.get("origin", "cli"),
                    actor=meta.get("actor", "human"),
                    ingest_kind=meta.get("ingest_kind", "shared"),
                    note=meta.get("note"),
                    created_at=meta.get("first_archived_at") or meta.get("last_checked_at"),
                )
            reindexed.append(item_id)
            if verbose:
                print(f"[reindex] {item_id}")
    return reindexed


def resolve_item_id(conn: sqlite3.Connection, target: str) -> str | None:
    """`read`/`search` 的 target 可以是 item_id 或 URL；这里统一解析成 item_id。"""
    if target.startswith("xhs-") or "-" not in target and get_object(conn, target):
        row = get_object(conn, target)
        if row:
            return row["item_id"]
    row = get_object(conn, target)
    if row:
        return row["item_id"]
    cur = conn.execute("SELECT item_id FROM objects WHERE canonical_url = ?", (target,))
    row = cur.fetchone()
    if row:
        return row["item_id"]
    # 兜底：target 里包含某条 canonical_url 的 note_id（短链/分享文本场景由调用方先跑 adapter 解析）
    return None
