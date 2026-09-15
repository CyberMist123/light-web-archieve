r"""笔记批注 + ⭐ 收藏（Owner 2026-09-16）。

- 批注/收藏状态存在对象目录的 `notes.json`（sidecar），**绝不写进可见正文 md**，
  所以重渲染不丢、也不改原文渲染。前端 annotate-view.js 直接读写这个 sidecar。
- ⭐ 点亮 = 收藏：把整篇可见笔记复制一份到 `vault\<标题>.md`（根下单个 md，
  Owner 看完可随手删、删了不碰源件）；熄灭 = 删掉那份副本。
- `@fable` 开头的批注只打标存着（to_fable=true），先不真发给 Fable。

前端只在「点⭐」时喊后端（要拷文件）；纯批注前端自己写 sidecar，不劳 Python。
CLI 保留 add/list 主要给测试和手动用。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import storage

EXIT_OK = 0


def notes_path(source: str, source_id: str) -> Path:
    return storage.object_dir(source, source_id) / "notes.json"


def load_notes(source: str, source_id: str) -> dict[str, Any]:
    """fail-open：文件缺了/坏了都当空批注，不炸。"""
    path = notes_path(source, source_id)
    if not path.is_file():
        return {"starred": False, "annotations": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"starred": False, "annotations": []}
    data.setdefault("starred", False)
    data.setdefault("annotations", [])
    return data


def save_notes(source: str, source_id: str, data: dict[str, Any]) -> Path:
    return storage.write_json(notes_path(source, source_id), data)


def _resolve(target: str):
    """item_id（xhs-…）优先；退一步按裸 source_id 扫一遍，方便命令行手敲。"""
    from . import index as index_mod

    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, target)
        if row is None:
            row = conn.execute(
                "SELECT * FROM objects WHERE source_id = ?", (target,)
            ).fetchone()
        if row is None:
            return None
        # 可见笔记路径/标题以 meta.json 为准（index 里可能没回填 visible_note）
        meta = {}
        meta_path = storage.object_dir(row["source"], row["source_id"]) / "meta.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        return {
            "item_id": row["item_id"],
            "source": row["source"],
            "source_id": row["source_id"],
            "visible_note": meta.get("visible_note") or row["visible_note"],
            "title": meta.get("title") or row["title"],
        }
    finally:
        conn.close()


def _copy_target(title: str) -> Path:
    from . import render as render_mod

    stem = render_mod.sanitize_title(title or "未命名收藏")
    return storage.vault_root() / f"{stem}.md"


def set_star(target: str, on: bool) -> dict[str, Any]:
    obj = _resolve(target)
    if obj is None:
        return {"target": target, "status": "missing"}
    data = load_notes(obj["source"], obj["source_id"])
    data["starred"] = bool(on)
    copy_path = _copy_target(obj["title"])
    copied = False
    removed = False
    if on:
        # 收藏：复制整篇可见笔记到 vault 根。已存在就别覆盖 Owner 可能改过的副本。
        visible = obj.get("visible_note")
        src = storage.vault_root() / visible if visible else None
        if src and src.is_file() and not copy_path.exists():
            copy_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            copied = True
        elif copy_path.exists():
            copied = True  # 已经有副本，算收藏态
    else:
        # 取消收藏：删掉副本（Owner 若手动挪走就删不到，忽略）
        if copy_path.exists():
            try:
                copy_path.unlink()
                removed = True
            except OSError:
                pass
    save_notes(obj["source"], obj["source_id"], data)
    return {
        "item_id": obj["item_id"],
        "status": "ok",
        "starred": data["starred"],
        "copy_path": str(copy_path),
        "copied": copied,
        "removed": removed,
    }


def add_annotation(target: str, text: str) -> dict[str, Any]:
    obj = _resolve(target)
    if obj is None:
        return {"target": target, "status": "missing"}
    text = (text or "").strip()
    if not text:
        return {"item_id": obj["item_id"], "status": "empty"}
    to_fable = text.lstrip().lower().startswith("@fable")
    entry = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "text": text,
        "to_fable": to_fable,
    }
    data = load_notes(obj["source"], obj["source_id"])
    data["annotations"].append(entry)
    save_notes(obj["source"], obj["source_id"], data)
    return {"item_id": obj["item_id"], "status": "ok", "annotation": entry, "count": len(data["annotations"])}


def list_notes(target: str) -> dict[str, Any]:
    obj = _resolve(target)
    if obj is None:
        return {"target": target, "status": "missing"}
    data = load_notes(obj["source"], obj["source_id"])
    return {"item_id": obj["item_id"], "status": "ok", **data}


def run(args) -> int:
    sub = getattr(args, "note_command", None)
    if sub == "star":
        on = not getattr(args, "off", False)
        out = set_star(args.target, on)
    elif sub == "add":
        out = add_annotation(args.target, args.text)
    elif sub == "list":
        out = list_notes(args.target)
    else:
        print("需要子命令：star / add / list", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return EXIT_OK if out.get("status") == "ok" else 1
