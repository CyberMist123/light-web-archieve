"""`read` / `search` 子命令。Lot 2：`read` 打印 `meta.json`；`search` 按标题/正文 LIKE 查询。"""

from __future__ import annotations

import json
import sys

from . import index as index_mod, storage
from .adapters import xiaohongshu as xhs

EXIT_OK = 0
EXIT_ERROR = 1


def _resolve_source_id(conn, target: str) -> tuple[str, str] | None:
    """target 是 item_id（`xhs-<id>`）或 URL/短链/分享文本 → `(source, source_id)`。"""
    if target.startswith("xhs-"):
        row = index_mod.get_object(conn, target)
        if row:
            return row["source"], row["source_id"]
        return xhs.SOURCE, target[len("xhs-") :]
    try:
        parsed = xhs.parse_input(target)
        return xhs.SOURCE, parsed["note_id"]
    except Exception:  # noqa: BLE001 - 不是能解析的链接，就当作原始 item_id 再试一次
        return None


def run(args) -> int:
    conn = index_mod.connect()
    try:
        resolved = _resolve_source_id(conn, args.target)
        if resolved is None:
            print(f"解析不出对象: {args.target}", file=sys.stderr)
            return EXIT_ERROR
        source, source_id = resolved
        meta_path = storage.object_dir(source, source_id) / "meta.json"
        if not meta_path.exists():
            print(f"没有归档过: {args.target}", file=sys.stderr)
            return EXIT_ERROR
        meta = storage.read_json(meta_path)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return EXIT_OK
    finally:
        conn.close()


def run_search(args) -> int:
    conn = index_mod.connect()
    try:
        rows = index_mod.search(conn, args.query, limit=args.limit)
        for row in rows:
            print(f"{row['item_id']} | {row['title'] or '(无标题)'} | {row['first_archived_at']}")
        return EXIT_OK
    finally:
        conn.close()
