"""SQLite 索引（objects / sources / relations 三表）。表结构见 docs/FORMAT.md §8。

去重只认 `(source, source_id)`；`ingest` 命中就直接返回已有对象，不联网不下载。

1024（p0-tomb）：删除屏蔽的权威来源是 `vault/_archive/tombstones.jsonl`（只追加），
index.db 的 tombstones 表只是缓存——每次 `connect` 都按 jsonl 对一遍，删掉 index.db 重建也不丢。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import storage

TOMBSTONES_JSONL = "tombstones.jsonl"
TOMB_FIELDS = ("source", "source_id", "item_id", "title", "url", "cover", "deleted_at", "trash_dir", "state")
# relations 去重口径：同一篇、同一来源 / 谁 / 怎么进来 / 附言算同一条（created_at 不算，留最早那条）
_RELATION_KEY = "item_id, origin, actor, COALESCE(actor_id, ''), ingest_kind, COALESCE(note, '')"
_DB_VERSION = 1  # PRAGMA user_version：1 = relations 已去过重

SCHEMA = """
CREATE TABLE IF NOT EXISTS tombstones (
    source TEXT NOT NULL, source_id TEXT NOT NULL, item_id TEXT PRIMARY KEY,
    title TEXT, url TEXT, cover TEXT, deleted_at TEXT NOT NULL, trash_dir TEXT NOT NULL,
    UNIQUE(source, source_id)
);
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
    try:
        _migrate(conn)
        sync_tombstones(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库原地升级，幂等：tombstones 补 state 列；relations 去重一次（user_version 记住做过）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tombstones)")}
    if "state" not in cols:
        conn.execute("ALTER TABLE tombstones ADD COLUMN state TEXT NOT NULL DEFAULT 'done'")
        conn.commit()
    if conn.execute("PRAGMA user_version").fetchone()[0] < _DB_VERSION:
        conn.execute(f"DELETE FROM relations WHERE id NOT IN (SELECT MIN(id) FROM relations GROUP BY {_RELATION_KEY})")
        conn.execute(f"PRAGMA user_version = {_DB_VERSION}")
        conn.commit()


# ---------------------------------------------------------------------------
# 删除屏蔽（tombstones.jsonl 为准，index.db 是缓存）。格式见 docs/FORMAT.md。
# 一行一个事件：{"op":"delete","state":"pending|done",<TOMB_FIELDS>,"at"} 或 {"op":"forget|restore",source,source_id,item_id,"at"}
# 同一 (source, source_id) 以最后一行为准；delete=屏蔽，forget / restore=解除屏蔽。
# ---------------------------------------------------------------------------


def _db_file(conn: sqlite3.Connection) -> Path | None:
    row = next((r for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
    return Path(row[2]) if row and row[2] else None


def tombstones_path(conn: sqlite3.Connection) -> Path:
    db = _db_file(conn)
    return (db.parent if db else storage.archive_root()) / TOMBSTONES_JSONL


def _read_events(path: Path) -> list[dict[str, Any]]:
    rows, _bad = storage.read_jsonl(path)  # 崩在半行（含截在汉字中间）：跳过那一行，不影响别的行
    return [e for e in rows if e.get("source") and e.get("source_id")]


def append_tombstone_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    """追加一行并 fsync；上一行要是崩在半截没换行，先补个换行，新行不会粘上去。"""
    path = tombstones_path(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**event, "at": event.get("at") or datetime.now(timezone.utc).isoformat()},
                      ensure_ascii=False) + "\n"
    with path.open("a+b") as fh:
        if fh.tell() > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                line = "\n" + line
        fh.write(line.encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


def _tomb_row(record: dict[str, Any]) -> tuple:
    return tuple(record.get(k) or ("done" if k == "state" else "") for k in TOMB_FIELDS)


def _upsert_tomb_cache(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    # item_id 是主键、(source, source_id) 也唯一：两边都可能撞上旧行，先清再插
    conn.execute("DELETE FROM tombstones WHERE source = ? AND source_id = ? AND item_id != ?",
                 (record["source"], record["source_id"], record.get("item_id") or ""))
    conn.execute(f"INSERT OR REPLACE INTO tombstones ({','.join(TOMB_FIELDS)}) VALUES ({','.join('?' * len(TOMB_FIELDS))})",
                 _tomb_row(record))


def write_tombstone(conn: sqlite3.Connection, record: dict[str, Any], *, commit: bool = True) -> None:
    """屏蔽一篇：先追加 jsonl（权威），再写 index.db 缓存。record 带 TOMB_FIELDS；state 缺省 done。"""
    record = {**record, "state": record.get("state") or "done"}
    append_tombstone_event(conn, {"op": "delete", **{k: record.get(k) for k in TOMB_FIELDS}})
    _upsert_tomb_cache(conn, record)
    if commit:
        conn.commit()


def clear_tombstone(conn: sqlite3.Connection, row: Any, op: str, *, commit: bool = True) -> None:
    """解除屏蔽（op = forget / restore）：先追加 jsonl，再删缓存行。"""
    append_tombstone_event(conn, {"op": op, "source": row["source"], "source_id": row["source_id"],
                                  "item_id": row["item_id"]})
    conn.execute("DELETE FROM tombstones WHERE source = ? AND source_id = ?", (row["source"], row["source_id"]))
    if commit:
        conn.commit()


def sync_tombstones(conn: sqlite3.Connection) -> None:
    """index.db 缓存对齐 jsonl。

    - jsonl 里没出现过、index.db 里有的屏蔽（1024 之前只存在 index.db）→ 导出成 jsonl，只导一次（导完就出现过了）；
    - 其余以 jsonl 每篇最后一行为准：屏蔽的补进 / 改正缓存，解除的从缓存删掉。
    """
    path = tombstones_path(conn)
    events = _read_events(path)
    final: dict[tuple[str, str], dict[str, Any] | None] = {}
    for event in events:
        key = (str(event["source"]), str(event["source_id"]))
        final[key] = event if event.get("op") == "delete" else None
    cached = {(r["source"], r["source_id"]): dict(r) for r in conn.execute("SELECT * FROM tombstones")}
    for key, row in cached.items():
        if key not in final:
            append_tombstone_event(conn, {"op": "delete", **{k: row.get(k) for k in TOMB_FIELDS}, "via": "migrate"})
            final[key] = row
    changed = False
    for key, record in final.items():
        have = cached.get(key)
        if record is None:
            if have is not None:
                conn.execute("DELETE FROM tombstones WHERE source = ? AND source_id = ?", key)
                changed = True
        elif have is None or _tomb_row(have) != _tomb_row(record):
            _upsert_tomb_cache(conn, record)
            changed = True
    if changed:
        conn.commit()


def relpath_from_vault(path: Path) -> str:
    return str(Path(path).resolve().relative_to(storage.vault_root().resolve())).replace("\\", "/")


def _media_key(url: Any) -> str:
    """图 / 视频地址只取稳定的那段：去掉 ?query 和 !样式后缀，只留最后一段路径。
    小红书 CDN 地址前面带时间戳 / 签名段，每次抓都不一样，整串比会把同一张图当成新图。"""
    if not url:
        return ""
    tail = str(url).split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return tail.split("!", 1)[0]


def _images_key(images: Any) -> list[str]:
    return [_media_key(i.get("url") or i.get("original_url")) for i in images or [] if isinstance(i, dict)]


def _comment_key(c: dict[str, Any]) -> dict[str, Any]:
    audio = c.get("audio") if isinstance(c.get("audio"), dict) else {}
    return {
        "id": c.get("comment_id"),
        "author": (c.get("author") or {}).get("user_id"),
        "text": c.get("text"),
        "created_at": c.get("created_at"),
        "images": _images_key(c.get("images")),
        "audio": [audio.get("audio_id"), audio.get("asr_text")] if audio else None,
        "subs": [_comment_key(s) for s in c.get("sub_comments") or [] if isinstance(s, dict)],
    }


def content_fingerprint(source: dict[str, Any]) -> dict[str, Any]:
    """判「内容变没变」只看内容：标题、正文、作者、发布时间、图 / 视频清单、附件、评论（文字 / 图 / 语音 / 楼中楼）。

    1024 起不再算进来的（会自然变、不代表内容变了）：xsec_token、输入网址、抓取时间、评论加载耗时 / 游标、
    网页探测结果、点赞收藏数、头像、IP 属地、附件下载状态、CDN 签名段。
    """
    note = source.get("note") or {}
    video = note.get("video") if isinstance(note.get("video"), dict) else None
    return {
        "source": source.get("source"),
        "source_id": source.get("source_id"),
        "kind": note.get("kind"),
        "title": note.get("title"),
        "body": note.get("body"),
        "author": (note.get("author") or {}).get("user_id"),
        "published_at": note.get("published_at"),
        "images": _images_key(note.get("images")),
        "video": [_media_key(video.get("video_url")), video.get("duration_sec")] if video else None,
        "attachments": [[a.get("doc_id"), a.get("name")] for a in note.get("attachments") or [] if isinstance(a, dict)],
        "comments": [_comment_key(c) for c in source.get("comments") or [] if isinstance(c, dict)],
    }


def normalized_source_sha256(source: dict[str, Any]) -> str:
    """source.json 的内容指纹 sha256（口径见 content_fingerprint）。"""
    payload = json.dumps(content_fingerprint(source), ensure_ascii=False, sort_keys=True)
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
    from .catalog import mark_dirty  # 1023：入库改了目录的输入（ARCH-AUDIT 第 1 批）
    mark_dirty("入库")


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
    """最新版本的内容指纹。

    1024 换了口径：库里存的可能是旧口径（混了口令 / 耗时）的值，直接拿来比会让首次刷新多出一个版本。
    所以这里按新口径从那一版的 source.json 重算；和库里存的不一样就顺手改掉。读不到文件才退回存的值。
    """
    row = conn.execute(
        "SELECT id, raw_dir, source_sha256 FROM sources WHERE item_id = ? ORDER BY version DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    if not row:
        return None
    try:
        sha = normalized_source_sha256(storage.read_json(storage.vault_root() / row["raw_dir"] / "source.json"))
    except (OSError, ValueError):
        return row["source_sha256"]
    if sha != row["source_sha256"]:
        conn.execute("UPDATE sources SET source_sha256 = ? WHERE id = ?", (sha, row["id"]))
        conn.commit()
    return sha


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
    commit: bool = True,
) -> None:
    # 1024：已经有同一条（同一篇 + 同一来源 / 谁 / 怎么进来 / 附言）就不再插——以前每次同步都多一行。
    # 判断和插入在同一条语句里，别的进程同时写也不会插出两行。
    conn.execute(
        f"""
        INSERT INTO relations (item_id, origin, actor, actor_id, ingest_kind, note, created_at)
        SELECT ?,?,?,?,?,?,?
        WHERE NOT EXISTS (SELECT 1 FROM relations WHERE ({_RELATION_KEY}) = (?,?,?,COALESCE(?, ''),?,COALESCE(?, '')))
        """,
        (item_id, origin, actor, actor_id, ingest_kind, note, created_at,
         item_id, origin, actor, actor_id, ingest_kind, note),
    )
    if commit:
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
    sync_tombstones(conn)  # 1024：屏蔽从 tombstones.jsonl 恢复（connect 已对过一遍，这里保险再对一次）
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
