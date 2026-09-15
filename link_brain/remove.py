"""删除收藏（Owner 2026-09-16 要的右键删除 / 多选删除的后端）。

删一个对象 = 删可见笔记 + 删 `_archive/<source>/<id>/` 整个对象目录 + 删索引行
（sources/relations 靠外键 ON DELETE CASCADE 跟着走）。**不可逆**，调用方（插件）负责先确认。
留言层里她手写的话也会随可见笔记一起没——删收藏本就是整条抹掉，符合预期。
"""

from __future__ import annotations

import shutil
from typing import Any

from . import index as index_mod, storage
from .read import EXIT_ERROR, EXIT_OK, dump_json


def delete_item(conn, item_id: str) -> dict[str, Any]:
    row = index_mod.get_object(conn, item_id)
    if row is None:
        return {"item_id": item_id, "status": "missing"}
    source, source_id = row["source"], row["source_id"]
    visible = row["visible_note"]

    vault = storage.vault_root()
    if visible:
        note_path = vault / visible
        try:
            note_path.unlink(missing_ok=True)
        except OSError:
            pass

    object_dir = storage.object_dir(source, source_id)
    if object_dir.is_dir():
        shutil.rmtree(object_dir, ignore_errors=True)

    conn.execute("DELETE FROM objects WHERE item_id = ?", (item_id,))
    conn.commit()
    return {"item_id": item_id, "status": "deleted", "note": visible}


def delete_items(item_ids: list[str]) -> dict[str, Any]:
    conn = index_mod.connect()
    try:
        results = [delete_item(conn, i) for i in item_ids]
    finally:
        conn.close()
    deleted = [r for r in results if r["status"] == "deleted"]
    return {"deleted": len(deleted), "results": results}


def run(args) -> int:
    outcome = delete_items(list(getattr(args, "item_ids", []) or []))
    # 删完顺手重建目录，让目录页数据同步（纯程序、不联网）
    if outcome["deleted"]:
        from . import catalog as catalog_mod

        catalog_mod.build()
    dump_json(outcome)
    return EXIT_OK if outcome["deleted"] else EXIT_ERROR
