r"""笔记批注 + ⭐ 收藏（Owner 2026-09-16）。

- 批注/收藏状态存在对象目录的 `notes.json`（sidecar），**绝不写进可见正文 md**，
  所以重渲染不丢、也不改原文渲染。前端 annotate-view.js 直接读写这个 sidecar。
- ⭐ 只更新收藏状态，由星标收藏目录聚合，不再复制或删除正文。
- `@fable` 开头的批注只打标存着（to_fable=true），先不真发给 Fable。

前端只在「点⭐」时喊后端（同步收藏状态）；纯批注前端自己写 sidecar，不劳 Python。
CLI 保留 add/list 主要给测试和手动用。
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import storage

EXIT_OK = 0


def notes_path(source: str, source_id: str) -> Path:
    return storage.object_dir(source, source_id) / "notes.json"


class NotesCorrupt(ValueError):
    """notes.json 在、但读不了（写到一半 / 同步软件正替换 / 手改坏了）。"""


def load_notes(source: str, source_id: str) -> dict[str, Any]:
    """文件不在 = 还没有批注（空）。文件在但读不了就报错——

    1001（审计 note-9）：以前坏了也当空的，set_star / add_annotation 接着把空数据写回去，所有批注就没了。
    """
    path = notes_path(source, source_id)
    if not path.is_file():
        return {"starred": False, "annotations": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NotesCorrupt(f"批注文件读不了，没动它：{path}（{type(exc).__name__}: {exc}）") from exc
    if not isinstance(data, dict):
        raise NotesCorrupt(f"批注文件不是对象，没动它：{path}")
    data.setdefault("starred", False)
    if not isinstance(data.get("annotations"), list):
        data["annotations"] = []
    return data


def annotation_text(data: Any) -> str:
    """批注全文（第 10 批进检索）：没删的、非空的，一条一行。删除墓碑和 annotate-view.js 的 akey 同一认法；草稿不算。"""
    if not isinstance(data, dict) or not isinstance(data.get("annotations"), list):
        return ""
    tomb = set(data.get("deleted") or []) if isinstance(data.get("deleted"), list) else set()
    out = []
    for a in data["annotations"]:
        if not isinstance(a, dict):
            continue
        key = a.get("id") or f"ts:{a.get('ts') or ''}|{a.get('text') or ''}"
        text = str(a.get("text") or "").strip()
        if text and key not in tomb:
            out.append(text)
    return "\n".join(out)


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


def set_star(target: str, on: bool) -> dict[str, Any]:
    obj = _resolve(target)
    if obj is None:
        return {"target": target, "status": "missing"}
    data = load_notes(obj["source"], obj["source_id"])
    data["starred"] = bool(on)
    # ★ 是「某天引起过注意」的痕迹，不是结论：只记时刻，取消就抹掉
    if on:
        data["starred_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    else:
        data.pop("starred_at", None)
    save_notes(obj["source"], obj["source_id"], data)
    # 第 2 批：目录页以 catalog-data 的 starred 为准（不再每次读几百份 notes.json），这里顺手把这一篇改进去
    try:
        from . import catalog

        catalog.patch_items({obj["item_id"]: {"starred": data["starred"], "starred_at": data.get("starred_at")}})
    except Exception:  # noqa: BLE001 - fail-open：星标已写进 notes.json，下次重建目录也会读到
        pass
    return {
        "item_id": obj["item_id"],
        "status": "ok",
        "starred": data["starred"],
        "starred_at": data.get("starred_at"),
        "copy_path": None,
        "copied": False,
        "removed": False,
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
        # 和 annotate-view.js 同一套：每条一个 id，两端合并 / 删除墓碑都按它认
        "id": "a" + uuid.uuid4().hex[:12],
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
    try:
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
    except NotesCorrupt as exc:
        print(str(exc), file=sys.stderr)
        out = {"target": args.target, "status": "corrupt", "error": str(exc)}
    print(json.dumps(out, ensure_ascii=False))
    return EXIT_OK if out.get("status") == "ok" else 1
